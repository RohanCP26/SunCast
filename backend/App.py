"""
Flask Backend for Sunset Prediction App
========================================

This is a simple REST API that ties together:
  • Solar geometry calculations
  • Weather data fetching
  • ML model predictions
  • Image prompt generation

To run:
  1. pip install flask flask-cors requests python-dotenv
  2. python app.py
  3. API runs on http://localhost:5000
  
To test:
  curl -X POST http://localhost:5000/api/predict \
    -H "Content-Type: application/json" \
    -d '{"latitude": 30.2672, "longitude": -97.7431, "date": "2026-10-01"}'
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import traceback
import numpy as np
from werkzeug.utils import secure_filename

from model.sunset_data_pipeline import SunsetDataPipeline
from model.sunset_ml_models import SunsetGradientBoostingModel, SunsetPredictionPipeline
from model.image_generator import SunsetImageGenerator
from social_store import SocialStore
from viewpoints import ViewpointFinder

# ============================================================================
# SETUP
# ============================================================================

load_dotenv()

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests (for frontend on different port)

# Global objects (load once at startup)
DATA_PIPELINE = None
ML_MODEL = None
PREDICTION_PIPELINE = None
IMAGE_GENERATOR = None
SOCIAL = SocialStore()
VIEWPOINTS = ViewpointFinder()
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}


def _auth_user():
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer", "").strip() if auth else ""
    if not token:
        token = request.headers.get("X-Auth-Token", "")
    return SOCIAL.user_from_token(token)


def _require_user():
    user = _auth_user()
    if not user:
        return None, (jsonify({"success": False, "error": "Authentication required"}), 401)
    return user, None


def _save_image(file, prefix: str) -> str:
    if not file or not file.filename:
        raise ValueError("Photo required")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Invalid image type")
    filename = secure_filename(
        f"{prefix}_{int(datetime.utcnow().timestamp())}_{file.filename}"
    )
    path = os.path.join(UPLOAD_DIR, filename)
    file.save(path)
    return path

def initialize_models():
    """Load models at startup"""
    global DATA_PIPELINE, ML_MODEL, PREDICTION_PIPELINE, IMAGE_GENERATOR
    
    try:
        print("Initializing data pipeline...")
        DATA_PIPELINE = SunsetDataPipeline(
            api_key=os.getenv("OPENWEATHER_API_KEY")
        )
        
        print("Initializing ML model...")
        ML_MODEL = SunsetGradientBoostingModel()
        # Create this before loading so a bad pickle cannot leave the API with no pipeline.
        print("Initializing prediction pipeline...")
        PREDICTION_PIPELINE = SunsetPredictionPipeline(use_cnn=False)

        model_path = os.getenv("MODEL_PATH", "model/sunset_model_real_v1.pkl")
        if os.path.exists(model_path):
            print(f"Loading trained model from {model_path}...")
            try:
                ML_MODEL.load(model_path)
            except Exception as load_error:
                print(f"⚠️  Could not load {model_path}: {load_error}")
                traceback.print_exc()
        else:
            print(f"⚠️  Model file not found at {model_path}")
            print("    Will train a new model on first request")

        if not ML_MODEL.trained:
            train_model_if_needed()
        PREDICTION_PIPELINE.model = ML_MODEL

        print("Initializing image generator...")
        IMAGE_GENERATOR = SunsetImageGenerator()
        print(f"  Provider: {IMAGE_GENERATOR.provider}")
        
        print("✓ Models initialized successfully!")
        
    except Exception as e:
        print(f"❌ Error initializing models: {e}")
        traceback.print_exc()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def validate_coordinates(lat, lon):
    """Validate latitude and longitude"""
    if not (-90 <= lat <= 90):
        return False, "Latitude must be between -90 and 90"
    if not (-180 <= lon <= 180):
        return False, "Longitude must be between -180 and 180"
    return True, "OK"


def train_model_if_needed():
    """Train a new model if one isn't loaded"""
    global ML_MODEL
    
    if not ML_MODEL.trained:
        print("Training new model...")
        import pandas as pd
        import numpy as np
        
        # Create synthetic data for demo
        n_samples = 1000
        df = pd.DataFrame({
            'cloud_cover': np.random.uniform(0, 100, n_samples),
            'humidity': np.random.uniform(20, 90, n_samples),
            'wind_speed': np.random.uniform(0, 20, n_samples),
            'visibility': np.random.uniform(5, 16, n_samples),
            'aerosol_proxy': np.random.uniform(0, 100, n_samples),
            'solar_elevation': np.random.uniform(0, 15, n_samples),
            'sunset_azimuth': np.random.uniform(240, 300, n_samples),
            'season': np.random.randint(0, 4, n_samples),
            'hue_shift': np.random.uniform(0, 180, n_samples),
            'saturation': np.random.uniform(0.3, 1.0, n_samples),
            'brightness': np.random.uniform(0.5, 1.0, n_samples),
            'cloud_density': np.random.uniform(0, 1.0, n_samples),
        })
        
        ML_MODEL.train(df)
        print("✓ Model trained successfully!")


def _features_from_weather(weather: dict, prediction_date: datetime) -> dict:
    """Build the feature dict expected by the trained GB model."""
    return {
        'warmth': min(1.0, max(0.0, (float(weather.get('temperature', 70)) - 40) / 60)),
        'cloud_cover': float(weather.get('cloud_cover', 40)),
        'humidity': float(weather.get('humidity', 60)),
        'wind_speed': float(weather.get('wind_speed', 5)),
        # Clamp visibility into a range closer to training data
        'visibility': float(np.clip(weather.get('visibility', 10), 1, 20)),
        'temperature': float(weather.get('temperature', 70)),
        'pressure': float(weather.get('pressure', 1013)),
        'likes': 0,
        'downloads': 0,
        'season': (prediction_date.month % 12) // 3,
        'location_name': weather.get('location_name') or weather.get('location'),
    }


def _run_day_prediction(weather: dict, prediction_date: datetime):
    """Run ML + aesthetic score for a single day's weather snapshot."""
    if PREDICTION_PIPELINE is None:
        initialize_models()
    if PREDICTION_PIPELINE is None:
        raise RuntimeError("Sunset model failed to start")
    features = _features_from_weather(weather, prediction_date)
    prediction = PREDICTION_PIPELINE.predict_sunset_appearance(features)

    if prediction.get('cloud_density', 0) == 0 and 'cloud_cover' in weather:
        prediction['cloud_density'] = min(1.0, float(weather['cloud_cover']) / 100.0)

    aesthetic = PREDICTION_PIPELINE.aesthetic_score(prediction, weather)
    return prediction, aesthetic


# ============================================================================
# ROUTES
# ============================================================================

def _frontend_build_dir():
    """React production build, when this process is serving the hosted app."""
    configured = os.getenv("FRONTEND_BUILD")
    if configured and os.path.isdir(configured):
        return configured
    sibling = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "build"))
    if os.path.isdir(sibling):
        return sibling
    return None


@app.route('/', methods=['GET'])
def index():
    """The hosted app, or a JSON index when only the API is running."""
    build = _frontend_build_dir()
    if build and "text/html" in request.headers.get("Accept", ""):
        return send_from_directory(build, "index.html")
    return jsonify({
        'status': 'ok',
        'message': 'Sunset Prediction API',
        'endpoints': {
            'predict': 'POST /api/predict',
            'week': 'POST /api/week',
            'generate_image': 'POST /api/generate-image',
            'geocode': 'GET /api/geocode',
            'viewpoints': 'POST /api/viewpoints',
            'social_register': 'POST /api/social/register',
            'social_login': 'POST /api/social/login',
            'social_feed': 'GET /api/social/feed',
            'social_profile': 'PATCH /api/social/me',
            'social_posts': 'GET /api/social/me/posts',
            'health': 'GET /api/health',
            'info': 'GET /api/info'
        }
    })


@app.route('/api/health', methods=['GET'])
def health():
    """Check API and model status"""
    return jsonify({
        'status': 'healthy',
        'model_loaded': ML_MODEL.trained if ML_MODEL else False,
        'pipeline_ready': PREDICTION_PIPELINE is not None,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/info', methods=['GET'])
def info():
    """Get info about the model"""
    if not ML_MODEL or not ML_MODEL.trained:
        return jsonify({
            'error': 'Model not trained',
            'message': 'Call /api/predict to train model'
        }), 400
    
    importance = ML_MODEL.get_feature_importance()
    
    return jsonify({
        'model_type': 'Gradient Boosting',
        'outputs': ['hue_shift', 'saturation', 'brightness', 'cloud_density'],
        'inputs': ML_MODEL.feature_names,
        'feature_importance': {
            target: [
                {'feature': feat, 'importance': float(imp)}
                for feat, imp in feature_list[:5]
            ]
            for target, feature_list in importance.items()
        }
    })


@app.route('/api/predict', methods=['POST'])
def predict():
    """
    Main prediction endpoint
    
    Request body:
    {
        "latitude": 30.2672,
        "longitude": -97.7431,
        "date": "2026-10-01",  // Optional, defaults to tomorrow
        "location_name": "Austin, TX"  // Optional
    }
    
    Response:
    {
        "success": true,
        "location": {
            "latitude": 30.2672,
            "longitude": -97.7431,
            "name": "Austin, TX"
        },
        "date": "2026-10-01",
        "solar_geometry": {
            "sunset_time": "7:28 PM",
            "sunset_azimuth": 280.5,
            "solar_elevation": 5.0
        },
        "prediction": {
            "hue_shift": 85.3,
            "saturation": 0.65,
            "brightness": 0.72,
            "cloud_density": 0.42
        },
        "image_generation_prompt": "A stunning vibrant sunset...",
        "confidence": 0.95,
        "visual_description": "Vivid orange sunset with scattered clouds"
    }
    """
    
    try:
        # Parse request
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Request body is empty'}), 400
        
        # Extract parameters (lat/lon optional — default Austin, TX for weather-only UI)
        latitude = data.get('latitude', 30.2672)
        longitude = data.get('longitude', -97.7431)
        location_name = data.get('location_name', 'Austin, TX')
        date_str = data.get('date')
        
        is_valid, message = validate_coordinates(latitude, longitude)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Parse date (default to tomorrow)
        if date_str:
            try:
                prediction_date = datetime.fromisoformat(date_str)
            except:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
        else:
            prediction_date = datetime.now() + timedelta(days=1)
        
        # Train model if needed
        if not ML_MODEL.trained:
            train_model_if_needed()
        
        # ===== MAIN PREDICTION LOGIC =====
        
        # Step 1: Calculate solar geometry
        print(f"Calculating solar geometry for {location_name}...")
        solar_geo = DATA_PIPELINE.calculate_solar_geometry(
            latitude, longitude, prediction_date
        )
        
        # Step 2: Prefer weather from the request (frontend sliders); else simulate
        if all(k in data for k in ('cloud_cover', 'humidity', 'wind_speed', 'visibility')):
            print(f"Using weather from request...")
            weather_sim = {
                'cloud_cover': float(data.get('cloud_cover', 35)),
                'humidity': float(data.get('humidity', 65)),
                'wind_speed': float(data.get('wind_speed', 8)),
                'visibility': float(data.get('visibility', 12)),
                'temperature': float(data.get('temperature', 75)),
                'pressure': float(data.get('pressure', 1013)),
                'solar_elevation': solar_geo['peak_solar_elevation'],
                'sunset_azimuth': solar_geo['sunset_azimuth'],
            }
        else:
            print(f"Simulating weather forecast...")
            import random
            weather_sim = {
                'cloud_cover': random.uniform(10, 80),
                'humidity': random.uniform(30, 80),
                'wind_speed': random.uniform(0, 15),
                'visibility': random.uniform(8, 16),
                'temperature': random.uniform(50, 90),
                'pressure': random.uniform(1000, 1030),
                'solar_elevation': solar_geo['peak_solar_elevation'],
                'sunset_azimuth': solar_geo['sunset_azimuth'],
            }
        
        # Step 3: Build feature vector matching the trained model
        # Model expects: warmth, cloud_cover, humidity, wind_speed, visibility,
        # temperature, pressure, likes, downloads
        print(f"Engineering features...")
        features = {
            'warmth': min(1.0, max(0.0, (weather_sim['temperature'] - 40) / 60)),
            'cloud_cover': weather_sim['cloud_cover'],
            'humidity': weather_sim['humidity'],
            'wind_speed': weather_sim['wind_speed'],
            'visibility': weather_sim['visibility'],
            'temperature': weather_sim['temperature'],
            'pressure': weather_sim['pressure'],
            'likes': 0,
            'downloads': 0,
            'solar_elevation': weather_sim['solar_elevation'],
            'sunset_azimuth': weather_sim['sunset_azimuth'],
            'season': (prediction_date.month % 12) // 3,
        }
        
        # Step 4: Make prediction
        print(f"Making prediction...")
        if PREDICTION_PIPELINE is None:
            initialize_models()
        if PREDICTION_PIPELINE is None:
            raise RuntimeError("Sunset model failed to start")
        prediction = PREDICTION_PIPELINE.predict_sunset_appearance(features)

        # cloud_density was not in training labels — derive from cloud cover
        if prediction.get('cloud_density', 0) == 0 and 'cloud_cover' in weather_sim:
            prediction['cloud_density'] = min(1.0, weather_sim['cloud_cover'] / 100.0)
        
        # Step 5: Format response
        print(f"Formatting response...")
        
        # Convert sunset time to readable format
        sunset_hour = solar_geo['sunset_lst']
        sunset_hour_int = int(sunset_hour)
        sunset_min_int = int((sunset_hour - sunset_hour_int) * 60)
        sunset_time = f"{sunset_hour_int}:{sunset_min_int:02d}"
        
        response = {
            'success': True,
            'location': {
                'latitude': latitude,
                'longitude': longitude,
                'name': location_name
            },
            'date': prediction_date.strftime('%Y-%m-%d'),
            'solar_geometry': {
                'sunset_time': sunset_time,
                'sunset_azimuth': round(solar_geo['sunset_azimuth'], 1),
                'solar_elevation': round(solar_geo['peak_solar_elevation'], 1),
                'sunrise_time': f"{int(solar_geo['sunrise_lst'])}:{int((solar_geo['sunrise_lst'] - int(solar_geo['sunrise_lst'])) * 60):02d}"
            },
            'weather_simulation': {
                'cloud_cover': round(weather_sim['cloud_cover'], 1),
                'humidity': round(weather_sim['humidity'], 1),
                'wind_speed': round(weather_sim['wind_speed'], 1),
                'visibility': round(weather_sim['visibility'], 1),
            },
            'prediction': {
                'hue_shift': round(prediction['hue_shift'], 1),
                'saturation': round(prediction['saturation'], 3),
                'brightness': round(prediction['brightness'], 3),
                'cloud_density': round(prediction['cloud_density'], 3),
            },
            'aesthetic': PREDICTION_PIPELINE.aesthetic_score(prediction, weather_sim),
            'image_generation_prompt': prediction['image_generation_prompt'],
            'confidence': round(prediction['confidence'], 2),
            'visual_description': _get_visual_description(prediction),
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify(response)
    
    except Exception as e:
        print(f"Error in /api/predict: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'type': type(e).__name__
        }), 500


@app.route('/api/generate-image', methods=['POST'])
def generate_image():
    """
    Generate an AI rendition of the predicted sunset for a location.

    Body:
      {
        "prompt": "...",
        "location_name": "Austin, TX",
        "latitude": 30.2672,
        "longitude": -97.7431,
        "hue_shift": 45,
        "saturation": 0.7,
        "brightness": 0.8,
        "cloud_density": 0.4,
        "visual_description": "...",
        "width": 1024,
        "height": 768,
        "seed": 42
      }
    """
    try:
        if IMAGE_GENERATOR is None:
            return jsonify({'success': False, 'error': 'Image generator not initialized'}), 503

        data = request.get_json(silent=True) or {}
        location_name = (
            data.get('location_name')
            or data.get('location')
            or ''
        ).strip()
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        prompt = data.get('prompt') or data.get('image_generation_prompt')

        if not prompt:
            # Build from ML fields when caller only has prediction outputs
            hue = data.get('hue_shift', 45)
            sat = data.get('saturation', 0.65)
            bright = data.get('brightness', 0.7)
            clouds = data.get('cloud_density', 0.4)
            desc = data.get('visual_description', 'a vivid sunset')

            if hue < 30:
                color = "deep red and crimson"
            elif hue < 60:
                color = "fiery orange and gold"
            elif hue < 90:
                color = "warm golden yellow"
            else:
                color = "soft peach and lavender"

            vivid = "extremely vivid" if sat > 0.75 else "softly saturated" if sat > 0.45 else "muted"
            light = "brilliant" if bright > 0.75 else "gentle" if bright > 0.5 else "dim twilight"
            sky = (
                "clear horizon with thin wisps"
                if clouds < 0.3
                else "scattered dramatic clouds"
                if clouds < 0.6
                else "heavy layered cloud cover"
            )
            place = location_name or "an open landscape"
            prompt = (
                f"Sunset over {place}. {desc}. A {vivid} {color} sunset, {light} light, "
                f"{sky}, wide landscape photography of {place}"
            )

        # Always inject location into the AI prompt when provided
        prompt = _inject_location_into_prompt(prompt, location_name, latitude, longitude)

        result = IMAGE_GENERATOR.generate(
            prompt=prompt,
            width=int(data.get('width', 1024)),
            height=int(data.get('height', 768)),
            seed=data.get('seed'),
            hue_shift=float(data.get('hue_shift', 45)),
            saturation=float(data.get('saturation', 0.7)),
            brightness=float(data.get('brightness', 0.75)),
            cloud_density=float(data.get('cloud_density', 0.4)),
            location_name=location_name or None,
        )
        result['location_name'] = location_name or None
        result['prompt'] = prompt

        status = 200 if result.get('success') else 502
        return jsonify(result), status

    except Exception as e:
        print(f"Error in /api/generate-image: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'type': type(e).__name__,
        }), 500


def _inject_location_into_prompt(prompt: str, location_name: str, latitude=None, longitude=None) -> str:
    """Ensure the place name (and optional coords) appear in the image prompt."""
    prompt = " ".join((prompt or "").split())
    place = (location_name or "").strip()
    if not place:
        return prompt

    # Avoid duplicating if the week/ML prompt already named the place
    if place.lower() in prompt.lower():
        loc_bit = ""
    else:
        loc_bit = (
            f"Sunset over {place}, showing the distinctive landscape and skyline of {place}. "
        )

    coord_bit = ""
    if latitude is not None and longitude is not None:
        try:
            coord_bit = f" Location coordinates {float(latitude):.4f}, {float(longitude):.4f}."
        except (TypeError, ValueError):
            coord_bit = ""

    return f"{loc_bit}{prompt} Scene set specifically in {place}.{coord_bit}".strip()


@app.route('/api/geocode', methods=['GET', 'POST'])
def geocode():
    """Resolve a place name to latitude/longitude via Open-Meteo."""
    try:
        data = request.get_json(silent=True) or {}
        query = (
            data.get('q')
            or data.get('query')
            or request.args.get('q')
            or request.args.get('query')
        )
        if not query:
            return jsonify({'success': False, 'error': 'Missing query'}), 400
        if DATA_PIPELINE is None:
            return jsonify({'success': False, 'error': 'Pipeline not ready'}), 503
        places = DATA_PIPELINE.geocode_location(query)
        if not places:
            return jsonify({
                'success': False,
                'error': f'No results for "{query}"',
                'results': [],
            }), 404
        return jsonify({'success': True, 'results': places, 'best': places[0]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/reverse-geocode', methods=['GET', 'POST'])
def reverse_geocode():
    """Resolve latitude/longitude to a human-readable place label."""
    try:
        data = request.get_json(silent=True) or {}
        latitude = data.get('latitude', request.args.get('latitude'))
        longitude = data.get('longitude', request.args.get('longitude'))
        if latitude is None or longitude is None:
            return jsonify({'success': False, 'error': 'Missing latitude/longitude'}), 400
        if DATA_PIPELINE is None:
            return jsonify({'success': False, 'error': 'Pipeline not ready'}), 503
        place = DATA_PIPELINE.reverse_geocode(float(latitude), float(longitude))
        if not place:
            return jsonify({
                'success': True,
                'label': 'Current location',
                'best': None,
            })
        return jsonify({'success': True, 'label': place['label'], 'best': place})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/week', methods=['POST', 'GET'])
def week_forecast():
    """
    Fetch next-week weather near sunset and score each day 1–10 for aesthetics.

    Geocodes location_name by default so the weather matches the place label
    (avoids "Boston" with leftover Austin coordinates).
    """
    try:
        data = request.get_json(silent=True) or {}
        location_name = data.get(
            'location_name',
            request.args.get('location_name', 'Austin, TX'),
        )
        resolve_location = data.get('resolve_location', True)
        if isinstance(resolve_location, str):
            resolve_location = resolve_location.lower() not in ('0', 'false', 'no')

        latitude = data.get('latitude', request.args.get('latitude'))
        longitude = data.get('longitude', request.args.get('longitude'))
        geocoded = None

        if resolve_location and location_name:
            places = DATA_PIPELINE.geocode_location(location_name)
            if places:
                geocoded = places[0]
                latitude = geocoded['latitude']
                longitude = geocoded['longitude']
                location_name = geocoded.get('label') or location_name

        if latitude is None or longitude is None:
            latitude = 30.2672
            longitude = -97.7431

        latitude = float(latitude)
        longitude = float(longitude)
        days = int(data.get('days', request.args.get('days', 7)))
        days = min(max(days, 1), 7)

        is_valid, message = validate_coordinates(latitude, longitude)
        if not is_valid:
            return jsonify({'error': message}), 400

        if not ML_MODEL or not ML_MODEL.trained:
            train_model_if_needed()

        print(
            f"Fetching {days}-day forecast for {location_name} "
            f"({latitude}, {longitude})..."
        )
        forecast = DATA_PIPELINE.fetch_open_meteo_forecast(
            latitude, longitude, days=days
        )
        if not forecast:
            return jsonify({
                'success': False,
                'error': 'Could not fetch weather forecast. Check network connectivity.',
            }), 502

        daily_weather = DATA_PIPELINE.daily_sunset_weather(forecast, days=days)
        if not daily_weather:
            return jsonify({
                'success': False,
                'error': 'Forecast returned no daily weather snapshots.',
            }), 502

        results = []
        for day in daily_weather:
            prediction_date = datetime.fromisoformat(day['date'])
            day_with_place = {**day, 'location_name': location_name}
            prediction, aesthetic = _run_day_prediction(
                day_with_place, prediction_date
            )

            sunset_display = None
            if day.get('sunset_time'):
                try:
                    sunset_display = datetime.fromisoformat(
                        day['sunset_time']
                    ).strftime('%I:%M %p').lstrip('0')
                except Exception:
                    sunset_display = day['sunset_time']

            sample_display = None
            if day.get('sample_time'):
                try:
                    sample_display = datetime.fromisoformat(
                        day['sample_time']
                    ).strftime('%I:%M %p').lstrip('0')
                except Exception:
                    sample_display = day['sample_time']

            results.append({
                'date': day['date'],
                'weekday': prediction_date.strftime('%A'),
                'sunset_time': sunset_display,
                'sample_time': sample_display,
                'sample_note': day.get('sample_note'),
                'weather': {
                    'cloud_cover': round(day['cloud_cover'], 1),
                    'humidity': round(day['humidity'], 1),
                    'wind_speed': round(day['wind_speed'], 1),
                    'visibility': round(day['visibility'], 1),
                    'temperature': round(day['temperature'], 1),
                    'pressure': round(day['pressure'], 1),
                    'precip_probability': round(
                        day.get('precip_probability') or 0, 0
                    ),
                    'temp_max': (
                        round(day['temp_max'], 1)
                        if day.get('temp_max') is not None
                        else None
                    ),
                    'temp_min': (
                        round(day['temp_min'], 1)
                        if day.get('temp_min') is not None
                        else None
                    ),
                },
                'prediction': {
                    'hue_shift': round(prediction['hue_shift'], 1),
                    'saturation': round(prediction['saturation'], 3),
                    'brightness': round(prediction['brightness'], 3),
                    'cloud_density': round(prediction['cloud_density'], 3),
                },
                'aesthetic_score': aesthetic['score'],
                'aesthetic_label': aesthetic['label'],
                'visual_description': _get_visual_description(prediction),
                'image_generation_prompt': prediction.get(
                    'image_generation_prompt'
                ),
                'confidence': round(prediction.get('confidence', 0.8), 2),
            })

        best = max(results, key=lambda d: d['aesthetic_score'])

        return jsonify({
            'success': True,
            'location': {
                'latitude': latitude,
                'longitude': longitude,
                'name': location_name,
                'timezone': forecast.get('timezone'),
                'geocoded': bool(geocoded),
                'geocode': geocoded,
            },
            'source': forecast.get('source', 'open-meteo'),
            'timezone': forecast.get('timezone'),
            'weather_basis': 'near_sunset',
            'weather_basis_note': (
                'Weather values are Open-Meteo conditions around local sunset, '
                'not the current hour shown in Google Weather.'
            ),
            'days': results,
            'best_day': {
                'date': best['date'],
                'weekday': best['weekday'],
                'aesthetic_score': best['aesthetic_score'],
                'aesthetic_label': best['aesthetic_label'],
            },
            'timestamp': datetime.now().isoformat(),
        })

    except Exception as e:
        print(f"Error in /api/week: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'type': type(e).__name__,
        }), 500


@app.route('/api/viewpoints', methods=['POST', 'GET'])
def viewpoints():
    """Find high / scenic sunset spots near a location."""
    try:
        data = request.get_json(silent=True) or {}
        latitude = float(data.get('latitude', request.args.get('latitude', 30.2672)))
        longitude = float(data.get('longitude', request.args.get('longitude', -97.7431)))
        location_name = data.get('location_name', request.args.get('location_name', ''))
        radius_m = int(data.get('radius_m', request.args.get('radius_m', 25000)))
        is_valid, message = validate_coordinates(latitude, longitude)
        if not is_valid:
            return jsonify({'error': message}), 400
        spots = VIEWPOINTS.find_viewpoints(
            latitude, longitude, radius_m=radius_m, location_name=location_name
        )
        return jsonify({
            'success': True,
            'location': {
                'latitude': latitude,
                'longitude': longitude,
                'name': location_name,
            },
            'viewpoints': spots,
            'count': len(spots),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route('/api/social/register', methods=['POST'])
def social_register():
    data = request.get_json(silent=True) or {}
    try:
        session = SOCIAL.register(
            data.get('username'),
            data.get('password'),
            data.get('display_name'),
        )
        return jsonify({'success': True, **session})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/social/login', methods=['POST'])
def social_login():
    data = request.get_json(silent=True) or {}
    try:
        session = SOCIAL.login(data.get('username'), data.get('password'))
        return jsonify({'success': True, **session})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 401


@app.route('/api/social/me', methods=['GET'])
def social_me():
    user, err = _require_user()
    if err:
        return err
    return jsonify({'success': True, 'user': user})


@app.route('/api/social/me', methods=['PATCH'])
def social_update_me():
    user, err = _require_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        updated = SOCIAL.update_profile(
            user['id'],
            display_name=data.get('display_name'),
            username=data.get('username'),
        )
        return jsonify({'success': True, 'user': updated})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/social/me/avatar', methods=['POST'])
def social_update_avatar():
    user, err = _require_user()
    if err:
        return err
    try:
        path = _save_image(request.files.get('photo') or request.files.get('image'), f"avatar_{user['id']}")
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    updated = SOCIAL.set_avatar(user['id'], path)
    return jsonify({'success': True, 'user': updated})


@app.route('/api/social/me/posts', methods=['GET'])
def social_my_posts():
    user, err = _require_user()
    if err:
        return err
    return jsonify({'success': True, 'posts': SOCIAL.posts_for_user(user['id'])})


@app.route('/api/social/users', methods=['GET'])
def social_users():
    user, err = _require_user()
    if err:
        return err
    q = request.args.get('q', '')
    return jsonify({
        'success': True,
        'results': SOCIAL.search_users(q, exclude_user_id=user['id']),
    })


@app.route('/api/social/friends', methods=['GET'])
def social_friends():
    user, err = _require_user()
    if err:
        return err
    return jsonify({'success': True, **SOCIAL.list_friends(user['id'])})


@app.route('/api/social/friends/request', methods=['POST'])
def social_friend_request():
    user, err = _require_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        result = SOCIAL.request_friend(user['id'], data.get('username'))
        return jsonify({'success': True, **result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/social/friends/respond', methods=['POST'])
def social_friend_respond():
    user, err = _require_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        result = SOCIAL.respond_friend(
            user['id'],
            int(data.get('friendship_id')),
            bool(data.get('accept', True)),
        )
        return jsonify({'success': True, **result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/social/feed', methods=['GET'])
def social_feed():
    user, err = _require_user()
    if err:
        return err
    posts = SOCIAL.feed_for_user(user['id'])
    return jsonify({'success': True, 'posts': posts})


@app.route('/api/social/posts', methods=['POST'])
def social_create_post():
    user, err = _require_user()
    if err:
        return err

    try:
        path = _save_image(request.files.get('photo') or request.files.get('image'), str(user['id']))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    score = request.form.get('aesthetic_score')
    try:
        score = float(score) if score not in (None, '') else None
    except ValueError:
        score = None

    post = SOCIAL.create_post(
        user_id=user['id'],
        image_path=path,
        caption=request.form.get('caption', ''),
        location_name=request.form.get('location_name', ''),
        sunset_date=request.form.get('sunset_date', ''),
        aesthetic_score=score,
    )
    return jsonify({'success': True, 'post': post})


@app.route('/api/social/posts/<int:post_id>', methods=['PATCH'])
def social_update_post(post_id):
    user, err = _require_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        post = SOCIAL.update_post(
            user['id'],
            post_id,
            caption=data.get('caption', ''),
            location_name=data.get('location_name', ''),
            sunset_date=data.get('sunset_date', ''),
        )
        return jsonify({'success': True, 'post': post})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404


def _get_visual_description(prediction):
    """Generate human-readable description of predicted sunset"""
    hue = prediction['hue_shift']
    sat = prediction['saturation']
    bright = prediction['brightness']
    clouds = prediction['cloud_density']
    
    # Color
    if hue < 30:
        color = "Red and crimson"
    elif hue < 60:
        color = "Orange and gold"
    elif hue < 90:
        color = "Yellow"
    else:
        color = "Yellow-green"
    
    # Vividness
    if sat > 0.8:
        vividness = "extremely vivid"
    elif sat > 0.6:
        vividness = "vibrant"
    else:
        vividness = "muted"
    
    # Brightness
    if bright > 0.8:
        brightness = "very bright"
    elif bright > 0.6:
        brightness = "moderately bright"
    else:
        brightness = "dim"
    
    # Clouds
    if clouds < 0.3:
        cloud_desc = "clear skies"
    elif clouds < 0.6:
        cloud_desc = "scattered clouds"
    else:
        cloud_desc = "mostly cloudy"
    
    return f"{color} sunset with {vividness} colors, {brightness}, {cloud_desc}"


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.route('/<path:asset_path>', methods=['GET'])
def frontend_file(asset_path):
    """Static files from the React build. API routes stay on their own handlers."""
    build = _frontend_build_dir()
    if not build or asset_path.startswith('api/') or asset_path.startswith('uploads/'):
        return jsonify({'error': 'Endpoint not found'}), 404
    full = os.path.normpath(os.path.join(build, asset_path))
    if not full.startswith(os.path.normpath(build)) or not os.path.isfile(full):
        return jsonify({'error': 'Endpoint not found'}), 404
    return send_from_directory(build, asset_path)


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({'error': 'Internal server error'}), 500


# ============================================================================
# MAIN
# ============================================================================

# Load models on import so a process that imports App still has a pipeline.
initialize_models()

if __name__ == '__main__':
    # Run Flask app
    port = int(os.getenv("PORT", 5001))
    debug = os.getenv("DEBUG", "False") == "True"
    
    print(f"\n🌅 Sunset Prediction API starting...")
    print(f"   Running on http://localhost:{port}")
    print(f"   Debug mode: {debug}\n")
    
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)