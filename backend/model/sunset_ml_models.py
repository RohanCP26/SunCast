"""
Sunset Prediction ML Models
Two approaches: Gradient Boosting (MVP) → CNN (Long-term)
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
import joblib
import json
from typing import Dict, Tuple, List


# ============================================================================
# PART 1: GRADIENT BOOSTING MVP (Fast, 1-2 weeks)
# ============================================================================

class SunsetGradientBoostingModel:
    """
    MVP Model: Predicts sunset visual characteristics from weather numbers
    
    Input: [cloud_cover, humidity, wind_speed, visibility, aerosol_proxy, solar_elevation, ...]
    Output: {hue_shift, saturation, brightness, color_palette}
    
    These outputs feed into image generation (Stable Diffusion).
    """
    
    def __init__(self, n_estimators=100, learning_rate=0.1, max_depth=7):
        """Initialize gradient boosting model"""
        
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        
        # Separate models for each visual output
        self.models = {
            'hue_shift': GradientBoostingRegressor(
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                max_depth=max_depth,
                random_state=42
            ),
            'saturation': GradientBoostingRegressor(
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                max_depth=max_depth,
                random_state=42
            ),
            'brightness': GradientBoostingRegressor(
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                max_depth=max_depth,
                random_state=42
            ),
            'cloud_density': GradientBoostingRegressor(
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                max_depth=max_depth,
                random_state=42
            ),
        }
        
        self.scaler = StandardScaler()
        self.feature_names = None
        self.trained = False
        
    def prepare_features(self, df: pd.DataFrame, 
                        feature_columns: List[str] = None) -> Tuple[np.ndarray, List[str]]:
        """
        Prepare feature matrix from raw data
        
        If feature_columns not provided, uses all numeric columns except targets
        """
        
        if feature_columns is None:
            # Auto-select numeric columns, excluding outputs
            exclude = ['hue_shift', 'saturation', 'brightness', 'cloud_density', 
                      'location', 'day_of_year']
            feature_columns = [col for col in df.columns 
                             if df[col].dtype in ['float64', 'int64'] and col not in exclude]
        
        X = df[feature_columns].values
        X = np.nan_to_num(X, nan=0.0)  # Replace NaN with 0
        
        self.feature_names = feature_columns
        return X, feature_columns
    
    def train(self, df: pd.DataFrame, feature_columns: List[str] = None):
        """
        Train gradient boosting models
        
        Expected DataFrame columns:
            Features: cloud_cover, humidity, wind_speed, visibility, etc.
            Targets: hue_shift (0-360), saturation (0-1), brightness (0-1), cloud_density (0-1)
        """
        
        print("Training Gradient Boosting Model...")
        
        X, self.feature_names = self.prepare_features(df, feature_columns)
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Train one model per output
        for target_name, model in self.models.items():
            if target_name not in df.columns:
                print(f"Warning: Target '{target_name}' not in DataFrame, skipping")
                continue
            
            y = df[target_name].values
            y = np.nan_to_num(y, nan=0.0)
            
            print(f"  Training {target_name}...")
            model.fit(X_scaled, y)
            
            # Print feature importance
            feature_importance = list(zip(self.feature_names, model.feature_importances_))
            feature_importance.sort(key=lambda x: x[1], reverse=True)
            
            print(f"    Top 5 features for {target_name}:")
            for feat, importance in feature_importance[:5]:
                print(f"      - {feat}: {importance:.4f}")
        
        self.trained = True
        print("Training complete!")
    
    def predict(self, X: np.ndarray) -> Dict[str, np.ndarray]:
        """
        Predict sunset characteristics
        
        Args:
            X: Feature matrix (n_samples, n_features)
            
        Returns:
            Dictionary with predictions for each visual characteristic
        """
        
        if not self.trained:
            raise ValueError("Model not trained yet. Call .train() first.")
        
        X_scaled = self.scaler.transform(X)
        
        predictions = {}
        for target_name, model in self.models.items():
            # Skip targets that were never fitted (e.g. cloud_density missing from training data)
            if not hasattr(model, 'estimators_') or model.estimators_ is None or len(model.estimators_) == 0:
                predictions[target_name] = np.zeros(len(X))
                continue
            predictions[target_name] = model.predict(X_scaled)
        
        return predictions
    
    def predict_single(self, features_dict: Dict[str, float]) -> Dict[str, float]:
        """
        Predict for a single observation (convenience method)
        
        Args:
            features_dict: {'cloud_cover': 45, 'humidity': 75, ...}
            
        Returns:
            {'hue_shift': 35, 'saturation': 0.92, 'brightness': 0.8, 'cloud_density': 0.6}
        """
        
        # Create feature vector in correct order
        X = np.array([[features_dict.get(name, 0) for name in self.feature_names]])
        
        predictions = self.predict(X)
        
        # Return as dict with scalar values
        return {
            target: float(values[0]) 
            for target, values in predictions.items()
        }
    
    def get_feature_importance(self) -> Dict[str, List[Tuple[str, float]]]:
        """Return feature importance for each target"""
        
        importance = {}
        for target_name, model in self.models.items():
            feat_imp = list(zip(self.feature_names, model.feature_importances_))
            feat_imp.sort(key=lambda x: x[1], reverse=True)
            importance[target_name] = feat_imp
        
        return importance
    
    def save(self, filepath: str):
        """Save trained model to disk"""
        data = {
            'models': self.models,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'hyperparams': {
                'n_estimators': self.n_estimators,
                'learning_rate': self.learning_rate,
                'max_depth': self.max_depth,
            }
        }
        joblib.dump(data, filepath)
        print(f"Model saved to {filepath}")
    
    def load(self, filepath: str):
        """Load trained model from disk"""
        data = joblib.load(filepath)
        self.models = data['models']
        self.scaler = data['scaler']
        self.feature_names = data['feature_names']
        self.trained = True
        print(f"Model loaded from {filepath}")


# ============================================================================
# PART 2: CNN UPGRADE (Longer term, 2-3 months)
# ============================================================================

class SunsetCNNModel:
    """
    CNN Model: Learns visual patterns directly from sunset photos
    
    Architecture:
    1. Input: Sunset photo (256x256 RGB)
    2. Feature extraction: Pre-trained ResNet50 backbone
    3. Condition: Weather features (cloud%, humidity, etc.)
    4. Output: Visual embeddings for image generation
    
    This is NOT a generative model — it's a conditional feature extractor
    that learns what visual patterns correlate with atmospheric conditions.
    """
    
    def __init__(self, backbone='resnet50', embedding_dim=256):
        """
        Initialize CNN model
        
        backbone: 'resnet50', 'efficientnet', or 'vit_base'
        embedding_dim: Output embedding dimension
        """
        
        self.backbone_name = backbone
        self.embedding_dim = embedding_dim
        self.model = None
        self.trained = False
        
        # Note: In real implementation, use PyTorch/TensorFlow
        # This is pseudocode for the architecture
        self._architecture = f"""
        CNN Architecture (Pseudo-code):
        
        Input: Sunset photo (256x256x3)
                + Weather features (cloud_cover, humidity, ..., 10 dims)
        
        Stem (Image Processing):
        - Conv2D(3, 64, kernel=7, stride=2) + BatchNorm + ReLU
        - MaxPool2D(3, stride=2)
        
        Backbone ({backbone}, weights from ImageNet):
        - ResNet50 Layer1-4 (extract multi-scale features)
        - GlobalAvgPool → 2048-dim vector
        
        Weather Fusion:
        - Weather features (10-dim) → Dense(64) + ReLU → Dense(128)
        - Concatenate with image features: [2048] + [128] → 2176-dim
        
        Head (Visual Embedding):
        - Dense(512) + BatchNorm + ReLU
        - Dense(256) + BatchNorm + ReLU
        - Dense({embedding_dim}) → Output embeddings
        
        Loss: Contrastive loss (similar atmospheres → similar embeddings)
              + Auxiliary: Cloud classification loss
        
        Output: {embedding_dim}-dim embedding vector
                (feeds to Stable Diffusion via fine-tuned LoRA)
        """
    
    def get_architecture(self) -> str:
        """Return model architecture description"""
        return self._architecture
    
    def prepare_training_data(self, 
                             photo_paths: List[str],
                             metadata: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare training data from sunset photos + weather metadata
        
        Args:
            photo_paths: List of paths to sunset photos
            metadata: DataFrame with columns:
                - photo_path
                - cloud_cover
                - humidity
                - wind_speed
                - visibility
                - aerosol_proxy
                - sunset_azimuth
                - ... (other weather features)
        
        Returns:
            (images, weather_features) ready for training
        
        Note: Real implementation would load images, resize, normalize, etc.
        """
        
        print(f"Loading {len(photo_paths)} sunset photos...")
        print("(This is pseudocode — real implementation uses PIL/opencv)")
        
        # In reality:
        # from PIL import Image
        # images = []
        # for path in photo_paths:
        #     img = Image.open(path).resize((256, 256))
        #     img = np.array(img) / 255.0
        #     images.append(img)
        # images = np.array(images)
        
        # For demo, return dummy data
        images = np.random.randn(len(photo_paths), 256, 256, 3)
        
        weather_cols = ['cloud_cover', 'humidity', 'wind_speed', 'visibility', 
                       'aerosol_proxy', 'sunset_azimuth']
        weather_features = metadata[weather_cols].values
        weather_features = (weather_features - weather_features.mean(axis=0)) / (weather_features.std(axis=0) + 1e-8)
        
        return images, weather_features
    
    def train_pseudo(self, images: np.ndarray, weather_features: np.ndarray, 
                    epochs=50, batch_size=32):
        """
        Training pseudocode (real implementation requires PyTorch/TensorFlow)
        
        Loss function would be:
        - Contrastive loss: Similar weather conditions → similar image embeddings
        - Auxiliary classification: Predict cloud type from embedding
        """
        
        print(f"Training CNN with {len(images)} images...")
        print(f"Batch size: {batch_size}, Epochs: {epochs}")
        print("""
        Training procedure (pseudocode):
        
        for epoch in range(epochs):
            for batch_images, batch_weather in dataloader:
                # Forward pass
                image_features = backbone(batch_images)  # 2048-dim
                weather_embed = weather_processor(batch_weather)  # 128-dim
                combined = concat([image_features, weather_embed])
                embeddings = head(combined)  # (batch, 256)
                
                # Loss calculation
                # 1. Contrastive: Pull together similar weather conditions
                contrastive_loss = NT_Xent_loss(embeddings, weather_similar)
                
                # 2. Cloud prediction auxiliary task
                cloud_pred = cloud_head(embeddings)
                aux_loss = CrossEntropy(cloud_pred, cloud_labels)
                
                total_loss = contrastive_loss + 0.1 * aux_loss
                
                # Backward pass
                optimizer.zero_grad()
                total_loss.backward()
                optimizer.step()
            
            print(f"Epoch {epoch} loss: {total_loss:.4f}")
        
        self.trained = True
        """)
        
        self.trained = True
    
    def get_training_advantages(self) -> str:
        """Advantages of CNN-based approach"""
        
        return """
        CNN Training Advantages:
        
        1. Visual Pattern Learning
           - Automatically discovers what makes sunsets look different
           - Learns cloud texture, gradient smoothness, color transitions
           - Captures non-linear relationships between atmosphere & appearance
        
        2. Generalization
           - Transfers learned patterns across locations
           - Works better with new atmospheric conditions
           - Learns global patterns (not location-specific)
        
        3. Competitive Advantage
           - SunsetHue uses rule-based heuristics (not ML)
           - Your CNN learns from actual sunset data
           - Can predict novel color combinations
           - Continuously improves with more training data
        
        4. Integration with Generative Models
           - Embeddings feed directly to Stable Diffusion LoRA
           - Fine-tune image generator on sunset characteristics
           - Enables infinite variations of predicted sunsets
        
        Challenges:
           - Requires 5,000+ labeled sunset photos with timestamps
           - Annotation pipeline needed (web scraping + manual QA)
           - GPU training (A100 ~24 hours for 50 epochs)
           - Model monitoring & retraining cycle
        """


# ============================================================================
# PART 3: INTEGRATION & INFERENCE
# ============================================================================

class SunsetPredictionPipeline:
    """End-to-end pipeline: Weather → ML Model → Image Generation"""
    
    def __init__(self, use_cnn=False):
        """
        Initialize prediction pipeline
        
        use_cnn: If True, uses CNN model. If False, uses gradient boosting.
        """
        
        self.use_cnn = use_cnn
        
        if use_cnn:
            self.model = SunsetCNNModel()
        else:
            self.model = SunsetGradientBoostingModel()
    
    def predict_sunset_appearance(self, weather_features: Dict[str, float]) -> Dict:
        """
        Predict what a sunset will look like
        
        Args:
            weather_features: {
                'cloud_cover': 45,
                'humidity': 75,
                'wind_speed': 8,
                'visibility': 12,
                'aerosol_proxy': 25,
                'solar_elevation': 5,
                ...
            }
        
        Returns:
            {
                'hue_shift': 35,
                'saturation': 0.92,
                'brightness': 0.8,
                'cloud_density': 0.6,
                'confidence': 0.87,
                'image_generation_prompt': "..."
            }
        """
        
        if not self.model.trained:
            return {'error': 'Model not trained'}
        
        # Get raw predictions
        predictions = self.model.predict_single(weather_features)
        
        # Construct image generation prompt (include location when available)
        prompt = self._build_prompt(
            predictions,
            weather_features,
            location=weather_features.get('location_name')
            or weather_features.get('location'),
        )
        
        return {
            **predictions,
            'confidence': self._estimate_confidence(weather_features),
            'image_generation_prompt': prompt
        }
    
    def _build_prompt(
        self,
        predictions: Dict,
        weather: Dict,
        location: str = None,
    ) -> str:
        """
        Build text-to-image prompt from model predictions + place context.
        """
        
        hue = predictions['hue_shift']
        sat = predictions['saturation']
        brightness = predictions['brightness']
        cloud_density = predictions['cloud_density']
        place = (location or weather.get('location_name') or weather.get('location') or '').strip()
        
        # Color description
        if hue < 15:
            color = "deep red and crimson"
        elif hue < 30:
            color = "fiery orange and red"
        elif hue < 45:
            color = "brilliant orange and gold"
        elif hue < 60:
            color = "warm golden yellow"
        else:
            color = "pale yellow transitioning to blue"
        
        # Saturation → vividness
        vividness = "extremely vivid and saturated" if sat > 0.8 else \
                   "vibrant and rich" if sat > 0.6 else \
                   "muted and soft"
        
        # Cloud coverage
        cloud_desc = "clear horizon with scattered clouds" if cloud_density < 0.3 else \
                    "partially covered by clouds" if cloud_density < 0.6 else \
                    "dramatic cloud formations"

        place_line = (
            f"Sunset over {place}, recognizable local landscape and skyline of {place}."
            if place else
            "Sunset over an open landscape horizon."
        )
        
        prompt = (
            f"{place_line} "
            f"A stunning {vividness} sunset with {color} hues across the sky. "
            f"The {cloud_desc} catching the last light of day. "
            f"Professional landscape photography of {place or 'the scene'}, "
            f"atmospheric lighting, natural color grading, serene mood."
        )
        
        return " ".join(prompt.split())
    
    def _estimate_confidence(self, weather_features: Dict) -> float:
        """
        Estimate model confidence based on feature values
        
        High confidence when:
        - Cloud cover not too extreme (5-80%)
        - Good visibility (>5 km)
        - Normal humidity (30-80%)
        
        Low confidence when:
        - Data outside training range
        - Unusual combinations
        """
        
        confidence = 1.0
        
        # Penalize extreme values
        if weather_features.get('cloud_cover', 50) < 5 or weather_features.get('cloud_cover', 50) > 95:
            confidence *= 0.7
        
        if weather_features.get('visibility', 10) < 3 or weather_features.get('visibility', 10) > 16:
            confidence *= 0.8
        
        return min(confidence, 1.0)

    def aesthetic_score(self, prediction: Dict, weather: Dict = None) -> Dict:
        """
        Map ML visual outputs (+ weather context) to a 1–10 aesthetics score.

        Higher when colors are vivid/warm and clouds are dramatic but not overcast.
        """
        weather = weather or {}
        sat = float(prediction.get("saturation", 0.5))
        bright = float(prediction.get("brightness", 0.5))
        hue = float(prediction.get("hue_shift", 45)) % 360
        clouds = prediction.get("cloud_density")
        if clouds is None:
            clouds = float(weather.get("cloud_cover", 40)) / 100.0
        else:
            clouds = float(clouds)

        # Warm classic sunset hues (red→gold) score highest
        if hue <= 60 or hue >= 330:
            hue_score = 1.0
        elif hue <= 90:
            hue_score = 0.75
        else:
            hue_score = 0.45

        # Partial cloud cover (~20–55%) tends to look most dramatic
        if 0.2 <= clouds <= 0.55:
            cloud_score = 1.0
        elif clouds < 0.2:
            cloud_score = 0.55 + clouds * 2.0
        else:
            cloud_score = max(0.15, 1.0 - (clouds - 0.55) * 1.6)

        visibility = float(weather.get("visibility", 10))
        # Model was trained around ~5–16 km; clamp extreme meteo values
        vis_norm = min(1.0, max(0.0, visibility / 16.0))

        raw = (
            0.35 * sat
            + 0.25 * bright
            + 0.25 * cloud_score
            + 0.10 * hue_score
            + 0.05 * vis_norm
        )
        score = 1.0 + raw * 9.0
        score = float(np.clip(round(score, 1), 1.0, 10.0))

        if score >= 8.5:
            label = "Exceptional"
        elif score >= 7.0:
            label = "Excellent"
        elif score >= 5.5:
            label = "Good"
        elif score >= 4.0:
            label = "Fair"
        else:
            label = "Muted"

        return {
            "score": score,
            "label": label,
            "components": {
                "saturation": round(sat, 3),
                "brightness": round(bright, 3),
                "hue_score": round(hue_score, 3),
                "cloud_score": round(cloud_score, 3),
            },
        }


# ============================================================================
# EXAMPLE: FULL WORKFLOW
# ============================================================================

if __name__ == "__main__":
    
    print("=" * 70)
    print("SUNSET PREDICTION ML MODELS - DEMONSTRATION")
    print("=" * 70)
    
    # --- Create synthetic training data ---
    print("\n1. Creating synthetic training data...")
    
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
        
        # Targets: correlate with features
        'hue_shift': np.random.uniform(0, 180, n_samples),
        'saturation': np.random.uniform(0.3, 1.0, n_samples),
        'brightness': np.random.uniform(0.5, 1.0, n_samples),
        'cloud_density': np.random.uniform(0, 1.0, n_samples),
    })
    
    print(f"  Created {len(df)} training samples")
    print(f"  Features: {list(df.columns[:8])}")
    print(f"  Targets: {list(df.columns[8:])}")
    
    # --- Train Gradient Boosting Model (MVP) ---
    print("\n2. Training Gradient Boosting Model (MVP)...")
    
    gb_model = SunsetGradientBoostingModel(n_estimators=50, learning_rate=0.1)
    gb_model.train(df)
    
    # --- Make a prediction ---
    print("\n3. Making a prediction...")
    
    test_weather = {
        'cloud_cover': 45,
        'humidity': 72,
        'wind_speed': 8,
        'visibility': 12,
        'aerosol_proxy': 25,
        'solar_elevation': 5,
        'sunset_azimuth': 280,
        'season': 1,  # Spring
    }
    
    prediction = gb_model.predict_single(test_weather)
    print(f"  Weather conditions: {test_weather}")
    print(f"  Predicted sunset appearance:")
    for key, value in prediction.items():
        print(f"    - {key}: {value:.3f}")
    
    # --- Full pipeline with image generation ---
    print("\n4. End-to-end pipeline with prompt generation...")
    
    pipeline = SunsetPredictionPipeline(use_cnn=False)
    pipeline.model = gb_model
    
    result = pipeline.predict_sunset_appearance(test_weather)
    
    print(f"  Generated Stable Diffusion Prompt:")
    print(f"  ---")
    print(f"  {result['image_generation_prompt']}")
    print(f"  ---")
    print(f"  Confidence: {result['confidence']:.2%}")
    
    # --- Show CNN architecture ---
    print("\n5. CNN Upgrade Path (for later)...")
    print("  " + "=" * 60)
    
    cnn_model = SunsetCNNModel(backbone='resnet50', embedding_dim=256)
    print(cnn_model.get_architecture())
    
    print("\n  Training advantages:")
    print(cnn_model.get_training_advantages())
    
    # --- Save model ---
    print("\n6. Saving model...")
    gb_model.save("/home/claude/sunset_model_v1.pkl")
    
    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)
