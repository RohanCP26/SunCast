"""
Sunset ML Data Pipeline
Fetches NOAA weather data + forecasts for training and prediction
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from typing import Dict, List, Optional, Tuple
import math

class SunsetDataPipeline:
    """Fetch and structure atmospheric data for sunset prediction"""
    
    def __init__(self, api_key: str = None):
        """
        Initialize pipeline
        api_key: OpenWeatherMap API key (free tier available)
        """
        self.openweather_key = api_key
        self.noaa_base = "https://www.ncei.noaa.gov/cdo-web/api/v2"
        self.nws_base = "https://api.weather.gov"
        
    # ==================== SOLAR GEOMETRY ====================
    
    def calculate_solar_geometry(self, lat: float, lon: float, 
                                  date: datetime) -> Dict:
        """Calculate solar elevation angle, azimuth, and sunset time"""
        
        # Julian day
        j = date.timetuple().tm_yday
        
        # Solar declination (Equation of Time)
        B = (360 / 365) * (j - 81)
        B_rad = math.radians(B)
        
        # Equation of Time (in minutes)
        eot = 9.87 * math.sin(2 * B_rad) - 7.53 * math.cos(B_rad) - 1.5 * math.sin(B_rad)
        
        # Solar noon (UTC)
        solar_noon_utc = 12 - (lon / 15) - eot / 60
        
        # Sunset hour angle (when sun hits horizon)
        lat_rad = math.radians(lat)
        # Clamp to valid range for acos [-1, 1]
        cos_value = np.clip(-math.tan(lat_rad) * math.tan(B_rad), -1, 1)
        sunset_hour_angle = math.acos(cos_value)
        sunset_hour_angle_deg = math.degrees(sunset_hour_angle)
        
        # Sunset time in local solar time
        sunset_lst = solar_noon_utc + sunset_hour_angle_deg / 15
        
        # Sunrise time (mirror of sunset around solar noon)
        sunrise_lst = solar_noon_utc - sunset_hour_angle_deg / 15
        
        # Peak solar elevation angle at solar noon
        peak_elevation = 90 - math.degrees(lat_rad) + math.degrees(B_rad)
        peak_elevation = min(peak_elevation, 90)  # Can't go past zenith
        
        # Azimuth at sunset (degrees from north, clockwise)
        # At sunset/sunrise: azimuth ≈ 90° (east) for sunrise, 270° (west) for sunset
        sunset_azimuth = 180 + math.degrees(math.atan2(
            math.cos(B_rad),
            -math.sin(lat_rad) * math.sin(B_rad)
        ))
        
        return {
            "date": date.isoformat(),
            "lat": lat,
            "lon": lon,
            "solar_noon_utc": solar_noon_utc,
            "sunrise_lst": sunrise_lst,
            "sunset_lst": sunset_lst,
            "sunset_azimuth": sunset_azimuth % 360,  # 0-360
            "peak_solar_elevation": peak_elevation,
            "minutes_to_sunset": 0  # Will be computed relative to now
        }
    
    # ==================== NOAA HISTORICAL DATA ====================
    
    def fetch_noaa_history(self, station_id: str, start_date: datetime, 
                           end_date: datetime) -> pd.DataFrame:
        """
        Fetch NOAA historical weather data
        
        station_id examples:
            - GHCND:USW00012839 (Los Angeles)
            - GHCND:USW00014732 (New York)
            - See: www.ncei.noaa.gov/products/land-based-station-data-quality-controlled-local-climatological-data/
        
        Returns: DataFrame with daily observations
        """
        
        # This would require an API token from NOAA
        # For MVP, you can download CSV from:
        # https://www.ncei.noaa.gov/cdo-web/
        
        # Alternative: Use free NOAA ISD (Integrated Surface Database)
        # Let's show the structure
        
        print(f"Fetching NOAA data for {station_id}")
        print(f"Date range: {start_date} to {end_date}")
        print("Note: Requires NOAA CDO-Web token or local data file")
        
        # For demo, return empty DataFrame with expected structure
        return pd.DataFrame({
            'date': pd.date_range(start_date, end_date),
            'temp_mean': np.random.normal(70, 10, (end_date - start_date).days),
            'temp_max': np.random.normal(80, 10, (end_date - start_date).days),
            'temp_min': np.random.normal(60, 8, (end_date - start_date).days),
            'cloud_cover': np.random.uniform(0, 100, (end_date - start_date).days),
            'visibility_km': np.random.uniform(5, 16, (end_date - start_date).days),
            'wind_speed': np.random.uniform(0, 20, (end_date - start_date).days),
            'pressure_mb': np.random.normal(1013, 5, (end_date - start_date).days),
            'humidity': np.random.uniform(20, 90, (end_date - start_date).days),
        })
    
    # ==================== NWS GRID POINT FORECAST (NOAA) ====================
    
    def fetch_nws_forecast(self, lat: float, lon: float) -> Dict:
        """
        Fetch National Weather Service forecast for a location
        
        Returns: Hourly forecast for next 7 days including:
            - Cloud cover
            - Visibility
            - Relative humidity
            - Wind
            - Temperature
        """
        
        try:
            # Step 1: Get grid point metadata
            points_resp = requests.get(
                f"{self.nws_base}/points/{lat},{lon}",
                timeout=10
            )
            points_resp.raise_for_status()
            points_data = points_resp.json()
            
            # Step 2: Get forecast URL from grid point
            forecast_url = points_data['properties']['forecast']
            
            # Step 3: Fetch detailed forecast
            forecast_resp = requests.get(forecast_url, timeout=10)
            forecast_resp.raise_for_status()
            forecast = forecast_resp.json()
            
            # Parse periods into structured data
            forecast_data = []
            for period in forecast['properties']['periods']:
                forecast_data.append({
                    'time': period['startTime'],
                    'temperature': period['temperature'],
                    'wind_speed': int(period['windSpeed'].split()[0]) if 'windSpeed' in period else 0,
                    'wind_direction': period['windDirection'],
                    'short_forecast': period['shortForecast'],
                    'detailed_forecast': period['detailedForecast'],
                })
            
            return {
                'lat': lat,
                'lon': lon,
                'forecast': forecast_data,
                'fetched_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Error fetching NWS forecast: {e}")
            return None
    
    # ==================== GEOCODING ====================

    def geocode_location(self, query: str, count: int = 5) -> List[Dict]:
        """
        Resolve a place name to coordinates via Open-Meteo Geocoding API.
        https://open-meteo.com/en/docs/geocoding-api
        """
        query = (query or "").strip()
        if not query:
            return []
        try:
            resp = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={
                    "name": query,
                    "count": count,
                    "language": "en",
                    "format": "json",
                },
                timeout=12,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
            places = []
            for row in results:
                parts = [
                    row.get("name"),
                    row.get("admin1"),
                    row.get("country_code") or row.get("country"),
                ]
                label = ", ".join([p for p in parts if p])
                places.append({
                    "name": row.get("name"),
                    "label": label,
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    "timezone": row.get("timezone"),
                    "country": row.get("country"),
                    "admin1": row.get("admin1"),
                    "population": row.get("population"),
                })
            return places
        except Exception as e:
            print(f"Error geocoding '{query}': {e}")
            return []

    def reverse_geocode(self, lat: float, lon: float) -> Optional[Dict]:
        """Resolve coordinates to a place label (BigDataCloud, no API key)."""
        try:
            resp = requests.get(
                "https://api.bigdatacloud.net/data/reverse-geocode-client",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "localityLanguage": "en",
                },
                timeout=12,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            city = data.get("city") or data.get("locality") or data.get("principalSubdivision")
            region = data.get("principalSubdivisionCode") or data.get("principalSubdivision")
            country = data.get("countryName")
            parts = []
            if city:
                parts.append(city)
            if region and region != city:
                parts.append(region)
            if country and len(parts) < 2:
                parts.append(country)
            if not parts:
                return None
            label = ", ".join(parts)
            return {
                "name": city or label,
                "label": label,
                "latitude": lat,
                "longitude": lon,
                "country": country,
                "admin1": data.get("principalSubdivision"),
            }
        except Exception as e:
            print(f"Error reverse-geocoding ({lat}, {lon}): {e}")
            return None

    # ==================== OPEN-METEO (7-day, no API key) ====================

    def fetch_open_meteo_forecast(self, lat: float, lon: float, days: int = 7) -> Dict:
        """
        Fetch Open-Meteo hourly forecast + daily sunset times.

        Free, no API key. Returns up to `days` days of hourly weather.
        Docs: https://open-meteo.com/en/docs
        """
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "hourly": ",".join([
                    "temperature_2m",
                    "relative_humidity_2m",
                    "cloud_cover",
                    "visibility",
                    "wind_speed_10m",
                    "surface_pressure",
                    "precipitation_probability",
                    "weather_code",
                ]),
                "daily": ",".join([
                    "sunset",
                    "sunrise",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_probability_max",
                ]),
                "forecast_days": min(max(days, 1), 16),
                "timezone": "auto",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
            }
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            forecast_data = []
            for i, t in enumerate(times):
                # Open-Meteo visibility is meters; convert to km for display/model
                vis_m = hourly.get("visibility", [None])[i]
                visibility_km = (vis_m / 1000.0) if vis_m is not None else 10.0
                forecast_data.append({
                    "time": t,
                    "temperature": hourly.get("temperature_2m", [None])[i],
                    "humidity": hourly.get("relative_humidity_2m", [None])[i],
                    "cloud_cover": hourly.get("cloud_cover", [None])[i],
                    "visibility": visibility_km,
                    "wind_speed": hourly.get("wind_speed_10m", [None])[i],
                    "pressure": hourly.get("surface_pressure", [None])[i],
                    "precip_probability": hourly.get("precipitation_probability", [None])[i],
                    "weather_code": hourly.get("weather_code", [None])[i],
                })

            daily = data.get("daily", {})
            sunsets = {}
            daily_meta = {}
            for idx, date_str in enumerate(daily.get("time", [])):
                sunsets[date_str] = (daily.get("sunset") or [None])[idx]
                daily_meta[date_str] = {
                    "sunrise": (daily.get("sunrise") or [None])[idx],
                    "sunset": (daily.get("sunset") or [None])[idx],
                    "temp_max": (daily.get("temperature_2m_max") or [None])[idx],
                    "temp_min": (daily.get("temperature_2m_min") or [None])[idx],
                    "precip_probability_max": (
                        daily.get("precipitation_probability_max") or [None]
                    )[idx],
                }

            return {
                "lat": lat,
                "lon": lon,
                "source": "open-meteo",
                "timezone": data.get("timezone"),
                "forecast": forecast_data,
                "sunsets": sunsets,
                "daily_meta": daily_meta,
                "fetched_at": datetime.now().isoformat(),
            }
        except Exception as e:
            print(f"Error fetching Open-Meteo forecast: {e}")
            return None

    def daily_sunset_weather(self, forecast: Dict, days: int = 7) -> List[Dict]:
        """
        Collapse hourly forecast into one weather snapshot per day near sunset.

        Uses the hour closest to Open-Meteo's daily sunset (not daily high / "now").
        """
        if not forecast or not forecast.get("forecast"):
            return []

        sunsets = forecast.get("sunsets") or {}
        daily_meta = forecast.get("daily_meta") or {}
        by_date: Dict[str, List[Dict]] = {}
        for item in forecast["forecast"]:
            date_key = item["time"][:10]
            by_date.setdefault(date_key, []).append(item)

        daily = []
        for date_key in sorted(by_date.keys())[:days]:
            hours = by_date[date_key]
            sunset_iso = sunsets.get(date_key)
            meta = daily_meta.get(date_key) or {}

            def hour_of(t: str) -> int:
                try:
                    return int(t.split("T")[1][:2])
                except Exception:
                    return 18

            def minute_of(t: str) -> int:
                try:
                    parts = t.split("T")[1].split(":")
                    return int(parts[0]) * 60 + int(parts[1])
                except Exception:
                    return 18 * 60

            if sunset_iso:
                target_min = minute_of(sunset_iso)
                target_hour = target_min // 60
            else:
                target_hour = 18
                target_min = 18 * 60

            # Pick the single hour closest to sunset (more accurate than a wide average)
            chosen = min(
                hours,
                key=lambda h: abs(minute_of(h["time"]) - target_min),
            )

            # Average sunset hour ±1h for stability, but report the chosen hour
            nearby = [
                h for h in hours
                if abs(minute_of(h["time"]) - target_min) <= 60
            ] or [chosen]

            def avg(key, default=0.0):
                vals = [h.get(key) for h in nearby if h.get(key) is not None]
                return float(np.mean(vals)) if vals else default

            daily.append({
                "date": date_key,
                "sunset_time": sunset_iso,
                "sunrise_time": meta.get("sunrise"),
                "sample_time": chosen.get("time"),
                "sample_note": "Conditions near local sunset (not current hour / daily high)",
                "cloud_cover": avg("cloud_cover", 40),
                "humidity": avg("humidity", 60),
                "wind_speed": avg("wind_speed", 5),
                # Cap absurd visibility for display; still keep km
                "visibility": float(np.clip(avg("visibility", 10), 0.5, 50)),
                "temperature": avg("temperature", 70),
                "pressure": avg("pressure", 1013),
                "precip_probability": avg("precip_probability", 0),
                "temp_max": meta.get("temp_max"),
                "temp_min": meta.get("temp_min"),
                "precip_probability_max": meta.get("precip_probability_max"),
            })

        return daily

    # ==================== OPENWEATHERMAP (Backup) ====================
    
    def fetch_openweather_forecast(self, lat: float, lon: float) -> Dict:
        """
        Fetch OpenWeatherMap forecast (free tier available)
        
        Get API key at: https://openweathermap.org/api
        Free tier gives 5-day forecast, 3-hour steps
        """
        
        if not self.openweather_key:
            print("OpenWeatherMap API key not provided")
            return None
        
        try:
            url = "https://api.openweathermap.org/data/2.5/forecast"
            params = {
                'lat': lat,
                'lon': lon,
                'appid': self.openweather_key,
                'units': 'metric'
            }
            
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            forecast_data = []
            for item in data['list']:
                forecast_data.append({
                    'time': datetime.fromtimestamp(item['dt']).isoformat(),
                    'temperature': item['main']['temp'],
                    'humidity': item['main']['humidity'],
                    'pressure': item['main']['pressure'],
                    'clouds': item['clouds']['all'],  # % cloud cover
                    'visibility': item.get('visibility', 10000) / 1000,  # km
                    'wind_speed': item['wind']['speed'],
                    'description': item['weather'][0]['description'],
                })
            
            return {
                'lat': lat,
                'lon': lon,
                'forecast': forecast_data,
                'fetched_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Error fetching OpenWeatherMap data: {e}")
            return None
    
    # ==================== FEATURE ENGINEERING ====================
    
    def engineer_features(self, 
                         solar_geometry: Dict,
                         weather_forecast: Dict,
                         historical_weather: pd.DataFrame = None) -> Dict:
        """
        Convert raw weather data into ML features
        
        Returns: Feature vector ready for model input
        """
        
        features = {}
        
        # --- SOLAR FEATURES ---
        features['solar_elevation_angle'] = solar_geometry['peak_solar_elevation']
        features['sunset_azimuth'] = solar_geometry['sunset_azimuth']
        features['solar_noon_hour'] = solar_geometry['solar_noon_utc'] % 24
        
        # --- CURRENT WEATHER (near sunset time) ---
        if weather_forecast and 'forecast' in weather_forecast:
            forecast_items = weather_forecast['forecast']
            
            # Get forecast item closest to sunset time
            # For now, take average of last 3 hours before sunset
            current_conditions = {
                'avg_cloud_cover': np.mean([f.get('clouds', f.get('cloud_cover', 0)) 
                                            for f in forecast_items[-6:]]),  # Last 3 hours
                'avg_humidity': np.mean([f.get('humidity', 50) 
                                        for f in forecast_items[-6:]]),
                'avg_wind_speed': np.mean([f.get('wind_speed', 0) 
                                          for f in forecast_items[-6:]]),
                'avg_visibility': np.mean([f.get('visibility', 10) 
                                          for f in forecast_items[-6:]]),
            }
            
            features.update(current_conditions)
        
        # --- AEROSOL PROXY ---
        # Use visibility + humidity as proxy for aerosol optical depth
        if 'avg_visibility' in features and 'avg_humidity' in features:
            # Lower visibility + high humidity = more aerosols/moisture
            features['aerosol_proxy'] = (100 - features['avg_visibility'] * 10) * (features['avg_humidity'] / 100)
        
        # --- TEMPORAL FEATURES ---
        features['day_of_year'] = solar_geometry['date'].split('T')[0]
        month = int(solar_geometry['date'].split('-')[1])
        features['season'] = (month % 12) // 3  # 0=winter, 1=spring, 2=summer, 3=fall
        
        # --- HISTORICAL TRENDS (Optional) ---
        if historical_weather is not None and len(historical_weather) > 0:
            recent_temp_trend = np.polyfit(range(7), 
                                          historical_weather['temp_mean'].tail(7), 1)[0]
            features['temp_trend_7day'] = recent_temp_trend
            features['cloud_cover_7day_mean'] = historical_weather['cloud_cover'].tail(7).mean()
        
        return features
    
    # ==================== DATA EXPORT ====================
    
    def create_training_dataset(self, 
                               locations: List[Tuple[float, float, str]],
                               start_date: datetime,
                               end_date: datetime) -> pd.DataFrame:
        """
        Create training dataset from multiple locations
        
        locations: List of (lat, lon, location_name)
        
        Note: This is a pipeline template. In reality, you'd:
        1. Download NOAA CSV data
        2. Cross-reference with sunset photo metadata
        3. Extract visual features from photos (using pre-trained model)
        4. Pair features with sunset photos
        """
        
        training_rows = []
        
        for lat, lon, location_name in locations:
            print(f"Processing {location_name} ({lat}, {lon})")
            
            current_date = start_date
            while current_date <= end_date:
                # Calculate solar geometry
                solar_geo = self.calculate_solar_geometry(lat, lon, current_date)
                
                # In real scenario: fetch actual forecast data
                # For demo: generate synthetic data
                weather_forecast = {
                    'forecast': [
                        {
                            'clouds': np.random.uniform(0, 100),
                            'humidity': np.random.uniform(30, 80),
                            'wind_speed': np.random.uniform(0, 15),
                            'visibility': np.random.uniform(5, 15),
                        }
                        for _ in range(10)
                    ]
                }
                
                # Engineer features
                features = self.engineer_features(solar_geo, weather_forecast)
                features['location'] = location_name
                features['latitude'] = lat
                features['longitude'] = lon
                
                training_rows.append(features)
                
                current_date += timedelta(days=1)
        
        return pd.DataFrame(training_rows)
    
    def export_to_csv(self, df: pd.DataFrame, filename: str):
        """Export training data to CSV"""
        df.to_csv(filename, index=False)
        print(f"Exported {len(df)} rows to {filename}")
    
    def export_to_json(self, df: pd.DataFrame, filename: str):
        """Export training data to JSON"""
        df.to_json(filename, orient='records', indent=2)
        print(f"Exported {len(df)} rows to {filename}")


# ==================== EXAMPLE USAGE ====================

if __name__ == "__main__":
    
    pipeline = SunsetDataPipeline()
    
    # Example 1: Calculate solar geometry for tomorrow's sunset in NYC
    print("=" * 60)
    print("EXAMPLE 1: Solar Geometry Calculation")
    print("=" * 60)
    
    tomorrow = datetime.now() + timedelta(days=1)
    nyc_solar = pipeline.calculate_solar_geometry(
        lat=40.7128, 
        lon=-74.0060,  # NYC coordinates
        date=tomorrow
    )
    
    print(json.dumps(nyc_solar, indent=2, default=str))
    
    # Example 2: Fetch NWS forecast (requires internet)
    print("\n" + "=" * 60)
    print("EXAMPLE 2: NWS Forecast (Real Data)")
    print("=" * 60)
    
    # This will attempt to fetch real forecast data
    forecast = pipeline.fetch_nws_forecast(40.7128, -74.0060)
    if forecast:
        print(f"Forecast for NYC (next {len(forecast['forecast'])} periods):")
        print(json.dumps(forecast['forecast'][:3], indent=2, default=str))
    
    # Example 3: Create synthetic training dataset
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Training Dataset Creation")
    print("=" * 60)
    
    us_locations = [
        (40.7128, -74.0060, "New York"),
        (34.0522, -118.2437, "Los Angeles"),
        (41.8781, -87.6298, "Chicago"),
        (29.7604, -95.3698, "Houston"),
        (33.7490, -84.3880, "Atlanta"),
    ]
    
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2023, 1, 31)
    
    training_df = pipeline.create_training_dataset(us_locations, start_date, end_date)
    
    print(f"\nCreated training dataset: {training_df.shape[0]} rows, {training_df.shape[1]} features")
    print("\nFeature columns:")
    print(training_df.columns.tolist())
    print("\nFirst few rows:")
    print(training_df.head())
    
    # Export
    pipeline.export_to_csv(training_df, "sunset_training_data.csv")
    pipeline.export_to_json(training_df, "sunset_training_data.json")
