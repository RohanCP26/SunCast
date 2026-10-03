"""
Enhanced Real Sunset Data Scraper (SunCast)
===========================================
Scrapes more photos across more queries, extracts richer visual statistics,
and attaches historical weather when coordinates are available.

Data sources:
  • Unsplash API — sunset photos (set UNSPLASH_ACCESS_KEY)
  • Pexels API   — optional secondary source (set PEXELS_API_KEY)
  • Open-Meteo Archive — historical weather near photo date/location
  • PIL / NumPy — visual feature extraction (real pixels only)

Output: CSV with expanded visual + weather features for higher-accuracy training
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from PIL import Image


SEARCH_QUERIES = [
    "sunset golden hour",
    "dramatic sunset clouds",
    "orange sunset sky",
    "red sunset horizon",
    "beach sunset",
    "mountain sunset",
    "city sunset skyline",
    "twilight afterglow",
]


class ImprovedRealSunsetDataScraper:
    """Scrapes REAL sunset data only — no synthetic visual fallback."""

    def __init__(self, unsplash_api_key=None, pexels_api_key=None):
        self.unsplash_api_key = unsplash_api_key or os.getenv("UNSPLASH_ACCESS_KEY", "")
        self.pexels_api_key = pexels_api_key or os.getenv("PEXELS_API_KEY", "")
        self.unsplash_base = "https://api.unsplash.com"
        self.pexels_base = "https://api.pexels.com/v1"
        self.successful_photos = []
        self.failed_photos = []
        self.stats = {
            "attempted": 0,
            "downloaded": 0,
            "processed": 0,
            "failed": 0,
            "weather_matched": 0,
            "weather_fallback": 0,
            "queries_used": 0,
            "sources": {"unsplash": 0, "pexels": 0},
        }

    # ===== PHOTO SCRAPING =====

    def scrape_sunset_photos(self, num_photos: int = 300) -> List[Dict]:
        """Scrape sunset photos from Unsplash (+ optional Pexels) across many queries."""
        print(f"🌅 Scraping up to {num_photos} sunset photos...\n")
        photos: List[Dict] = []
        seen_ids = set()

        if self.unsplash_api_key:
            photos.extend(self._scrape_unsplash(num_photos, seen_ids))
        else:
            print("⚠️  UNSPLASH_ACCESS_KEY not set — skipping Unsplash")

        if len(photos) < num_photos and self.pexels_api_key:
            photos.extend(self._scrape_pexels(num_photos - len(photos), seen_ids))

        print(f"✓ Found {len(photos)} unique sunset photos\n")
        return photos[:num_photos]

    def _scrape_unsplash(self, num_photos: int, seen_ids: set) -> List[Dict]:
        photos = []
        per_query = max(40, (num_photos // max(len(SEARCH_QUERIES), 1)) + 20)

        for query in SEARCH_QUERIES:
            if len(photos) >= num_photos:
                break
            self.stats["queries_used"] += 1
            pages_needed = (per_query // 20) + 1
            print(f"  Unsplash query: '{query}'")

            for page in range(1, pages_needed + 1):
                if len(photos) >= num_photos:
                    break
                try:
                    response = requests.get(
                        f"{self.unsplash_base}/search/photos",
                        params={
                            "query": query,
                            "per_page": 30,
                            "order_by": "relevant",
                            "content_filter": "high",
                            "page": page,
                        },
                        headers={"Authorization": f"Client-ID {self.unsplash_api_key}"},
                        timeout=12,
                    )
                    if response.status_code != 200:
                        print(f"    Page {page}: HTTP {response.status_code}")
                        break

                    batch = response.json().get("results", [])
                    if not batch:
                        break

                    for photo in batch:
                        pid = photo.get("id")
                        if not pid or pid in seen_ids:
                            continue
                        url = photo.get("urls", {}).get("regular")
                        if not url:
                            continue

                        loc = photo.get("location") or {}
                        position = loc.get("position") or {}
                        photos.append({
                            "id": pid,
                            "source": "unsplash",
                            "url": url,
                            "description": photo.get("description") or "",
                            "alt_description": photo.get("alt_description") or "",
                            "likes": photo.get("likes", 0) or 0,
                            "downloads": photo.get("downloads", 0) or 0,
                            "views": photo.get("views", 0) or 0,
                            "width": photo.get("width"),
                            "height": photo.get("height"),
                            "color": photo.get("color"),
                            "location_name": loc.get("name") or loc.get("city") or loc.get("title") or "Unknown",
                            "latitude": position.get("latitude"),
                            "longitude": position.get("longitude"),
                            "user": (photo.get("user") or {}).get("username", "unknown"),
                            "created_at": photo.get("created_at", ""),
                            "query": query,
                        })
                        seen_ids.add(pid)
                        self.stats["sources"]["unsplash"] += 1

                    print(f"    Page {page}: +{len(batch)} (total unique {len(photos)})")
                except Exception as e:
                    print(f"    Page {page}: {str(e)[:60]}")
                time.sleep(0.4)

        return photos

    def _scrape_pexels(self, num_photos: int, seen_ids: set) -> List[Dict]:
        photos = []
        print("  Pexels secondary scrape...")
        for query in SEARCH_QUERIES[:4]:
            if len(photos) >= num_photos:
                break
            self.stats["queries_used"] += 1
            try:
                response = requests.get(
                    f"{self.pexels_base}/search",
                    params={"query": query, "per_page": 40, "orientation": "landscape"},
                    headers={"Authorization": self.pexels_api_key},
                    timeout=12,
                )
                if response.status_code != 200:
                    print(f"    Pexels '{query}': HTTP {response.status_code}")
                    continue
                for photo in response.json().get("photos", []):
                    pid = f"pexels_{photo.get('id')}"
                    if pid in seen_ids:
                        continue
                    url = (photo.get("src") or {}).get("large") or (photo.get("src") or {}).get("medium")
                    if not url:
                        continue
                    photos.append({
                        "id": pid,
                        "source": "pexels",
                        "url": url,
                        "description": photo.get("alt") or query,
                        "alt_description": photo.get("alt") or "",
                        "likes": 0,
                        "downloads": 0,
                        "views": 0,
                        "width": photo.get("width"),
                        "height": photo.get("height"),
                        "color": photo.get("avg_color"),
                        "location_name": "Unknown",
                        "latitude": None,
                        "longitude": None,
                        "user": (photo.get("photographer") or "unknown"),
                        "created_at": "",
                        "query": query,
                    })
                    seen_ids.add(pid)
                    self.stats["sources"]["pexels"] += 1
            except Exception as e:
                print(f"    Pexels error: {str(e)[:60]}")
            time.sleep(0.35)
        print(f"    Pexels added {len(photos)} photos")
        return photos

    # ===== VISUAL FEATURE EXTRACTION =====

    def extract_visual_features(self, image_url: str) -> Optional[Dict]:
        """Extract rich visual stats. Returns None if extraction fails."""
        try:
            response = requests.get(image_url, timeout=8)
            if response.status_code != 200:
                return None
            try:
                img = Image.open(BytesIO(response.content))
            except Exception:
                return None

            if img.mode != "RGB":
                try:
                    img = img.convert("RGB")
                except Exception:
                    return None

            if img.width < 100 or img.height < 100:
                return None

            img.thumbnail((640, 640))
            pixels = np.array(img, dtype=np.float32) / 255.0
            features = self._analyze_image_colors_robust(pixels)
            if features is None:
                return None
            for key, val in features.items():
                if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
                    return None
            return features
        except Exception:
            return None

    def _analyze_image_colors_robust(self, pixels: np.ndarray) -> Optional[Dict]:
        """HSV + spatial / distribution stats for richer model features."""
        try:
            if pixels.size == 0 or len(pixels.shape) != 3:
                return None
            h, w, c = pixels.shape
            if h < 10 or w < 10 or c != 3:
                return None

            # Focus on upper 55% (sky-dominant region for sunsets)
            sky = pixels[: max(1, int(h * 0.55)), :, :]
            horizon = pixels[int(h * 0.35): int(h * 0.7), :, :]

            def hsv_stats(region: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
                flat = region.reshape(-1, 3)
                r, g, b = flat[:, 0], flat[:, 1], flat[:, 2]
                c_max = np.maximum(np.maximum(r, g), b)
                c_min = np.minimum(np.minimum(r, g), b)
                delta = c_max - c_min
                hue = np.zeros_like(delta)
                mask_r = (c_max == r) & (delta > 0)
                mask_g = (c_max == g) & (delta > 0)
                mask_b = (c_max == b) & (delta > 0)
                hue[mask_r] = 60 * (((g[mask_r] - b[mask_r]) / delta[mask_r]) % 6)
                hue[mask_g] = 60 * (((b[mask_g] - r[mask_g]) / delta[mask_g]) + 2)
                hue[mask_b] = 60 * (((r[mask_b] - g[mask_b]) / delta[mask_b]) + 4)
                hue = np.where(hue < 0, hue + 360, hue)
                sat = np.where(c_max > 0, delta / c_max, 0)
                val = c_max
                return hue, sat, val

            hue, sat, val = hsv_stats(sky)
            h_h, h_s, h_v = hsv_stats(horizon)

            avg_hue = float(np.median(hue))
            avg_saturation = float(np.median(sat))
            avg_brightness = float(np.median(val))

            flat = sky.reshape(-1, 3)
            r, g, b = flat[:, 0], flat[:, 1], flat[:, 2]
            warmth = float(np.clip((np.median(r) - np.median(b)) * 0.5 + 0.5, 0, 1))

            # Extra statistics for accuracy
            contrast = float(np.std(val))
            sat_std = float(np.std(sat))
            brightness_p90 = float(np.percentile(val, 90))
            brightness_p10 = float(np.percentile(val, 10))
            dynamic_range = float(brightness_p90 - brightness_p10)

            # Warm hue fraction (reds/oranges/golds ~ 0–60°)
            warm_mask = (hue <= 60) | (hue >= 330)
            warm_ratio = float(np.mean(warm_mask))

            # Cloud proxy: mid-brightness, low-saturation patches
            cloud_mask = (val > 0.35) & (val < 0.9) & (sat < 0.25)
            cloud_density = float(np.clip(np.mean(cloud_mask) * 1.8, 0, 1))

            # Vertical gradient (bright horizon vs darker upper sky often = vivid sunset)
            top_slice = sky[: max(1, sky.shape[0] // 4)].reshape(-1, 3)
            top_bright = float(np.median(top_slice.max(axis=1)))
            bot_bright = float(np.median(horizon.reshape(-1, 3).max(axis=1)))
            vertical_glow = float(np.clip(bot_bright - top_bright + 0.5, 0, 1))

            # Colorfulness (Hasler–Süsstrunk approx)
            rg = r - g
            yb = 0.5 * (r + g) - b
            colorfulness = float(np.sqrt(np.std(rg) ** 2 + np.std(yb) ** 2) + 0.3 * np.sqrt(np.mean(rg) ** 2 + np.mean(yb) ** 2))

            if not all(np.isfinite([avg_hue, avg_saturation, avg_brightness, warmth, contrast, cloud_density])):
                return None

            return {
                "hue_shift": avg_hue,
                "saturation": avg_saturation,
                "brightness": avg_brightness,
                "warmth": warmth,
                "contrast": contrast,
                "saturation_std": sat_std,
                "dynamic_range": dynamic_range,
                "warm_ratio": warm_ratio,
                "cloud_density": cloud_density,
                "vertical_glow": vertical_glow,
                "colorfulness": colorfulness,
                "horizon_hue": float(np.median(h_h)),
                "horizon_saturation": float(np.median(h_s)),
                "horizon_brightness": float(np.median(h_v)),
            }
        except Exception:
            return None

    # ===== WEATHER =====

    def fetch_historical_weather(self, lat: float, lon: float, date: datetime) -> Optional[Dict]:
        """Open-Meteo archive weather near sunset for a lat/lon/date."""
        try:
            day = date.strftime("%Y-%m-%d")
            response = requests.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": day,
                    "end_date": day,
                    "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,visibility,wind_speed_10m,surface_pressure",
                    "daily": "sunset",
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "timezone": "auto",
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            hourly = data.get("hourly") or {}
            times = hourly.get("time") or []
            if not times:
                return None

            sunset_list = (data.get("daily") or {}).get("sunset") or []
            target_hour = 18
            if sunset_list:
                try:
                    target_hour = int(sunset_list[0].split("T")[1][:2])
                except Exception:
                    pass

            best_i = min(
                range(len(times)),
                key=lambda i: abs(int(times[i].split("T")[1][:2]) - target_hour),
            )
            nearby = [
                i for i, t in enumerate(times)
                if abs(int(t.split("T")[1][:2]) - target_hour) <= 1
            ] or [best_i]

            def avg(key, scale=1.0, default=0.0):
                vals = []
                series = hourly.get(key) or []
                for i in nearby:
                    if i < len(series) and series[i] is not None:
                        vals.append(float(series[i]) * scale)
                return float(np.mean(vals)) if vals else default

            vis_km = avg("visibility", scale=0.001, default=10.0)
            return {
                "cloud_cover": avg("cloud_cover", default=40.0),
                "humidity": avg("relative_humidity_2m", default=60.0),
                "wind_speed": avg("wind_speed_10m", default=5.0),
                "visibility": float(np.clip(vis_km, 1, 50)),
                "temperature": avg("temperature_2m", default=70.0),
                "pressure": avg("surface_pressure", default=1013.0),
                "weather_source": "open-meteo-archive",
            }
        except Exception as e:
            print(f"    weather archive miss: {str(e)[:50]}")
            return None

    def get_weather_for_date_location(
        self,
        location: str,
        date: datetime,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict:
        """Prefer historical weather; fall back to seasonal priors only if needed."""
        if latitude is not None and longitude is not None:
            hist = self.fetch_historical_weather(float(latitude), float(longitude), date)
            if hist:
                self.stats["weather_matched"] += 1
                return hist

        self.stats["weather_fallback"] += 1
        season = (date.month % 12) // 3
        seasonal_cloud_cover = {
            0: np.random.uniform(20, 50),
            1: np.random.uniform(30, 60),
            2: np.random.uniform(40, 70),
            3: np.random.uniform(25, 55),
        }
        return {
            "cloud_cover": seasonal_cloud_cover[season],
            "humidity": np.random.uniform(40, 80),
            "wind_speed": np.random.uniform(0, 15),
            "visibility": np.random.uniform(8, 16),
            "temperature": np.random.uniform(50, 90),
            "pressure": np.random.uniform(1000, 1030),
            "weather_source": "seasonal_prior",
        }

    # ===== TRAINING DATA =====

    def create_real_training_dataset(self, num_target_samples: int = 200) -> pd.DataFrame:
        print("=" * 70)
        print(f"CREATING REAL SUNSET TRAINING DATASET — TARGET: {num_target_samples}")
        print("=" * 70)

        num_to_scrape = max(num_target_samples * 3, 300)
        photos = self.scrape_sunset_photos(num_photos=num_to_scrape)
        if not photos:
            print("❌ No photos scraped!")
            return pd.DataFrame()

        training_rows = []
        print(f"\n📸 Processing {len(photos)} photos (target {num_target_samples})...\n")

        for i, photo in enumerate(photos):
            self.stats["attempted"] += 1
            desc = photo.get("description") or photo.get("alt_description") or "Sunset"
            print(f"  [{i+1}/{len(photos)}] '{str(desc)[:40]}'...", end="")

            try:
                visual = self.extract_visual_features(photo["url"])
                if visual is None:
                    self.stats["failed"] += 1
                    print(" ❌ features")
                    self.failed_photos.append(photo["id"])
                    continue

                self.stats["downloaded"] += 1
                try:
                    photo_date = datetime.fromisoformat(photo["created_at"].replace("Z", "+00:00"))
                except Exception:
                    photo_date = datetime.now() - timedelta(days=int(np.random.randint(30, 800)))

                weather = self.get_weather_for_date_location(
                    photo.get("location_name", "Unknown"),
                    photo_date,
                    photo.get("latitude"),
                    photo.get("longitude"),
                )

                row = {
                    "photo_id": photo["id"],
                    "source": f"{photo.get('source', 'unknown')}_real",
                    "query": photo.get("query", ""),
                    "date": photo_date.strftime("%Y-%m-%d"),
                    "location": photo.get("location_name", "Unknown"),
                    "latitude": photo.get("latitude"),
                    "longitude": photo.get("longitude"),
                    "photo_url": photo["url"],
                    "description": photo.get("description", ""),
                    "width": photo.get("width"),
                    "height": photo.get("height"),
                    # Visual targets / features
                    **visual,
                    # Weather
                    **{k: weather[k] for k in (
                        "cloud_cover", "humidity", "wind_speed",
                        "visibility", "temperature", "pressure",
                    )},
                    "weather_source": weather.get("weather_source"),
                    # Engagement metadata
                    "likes": photo.get("likes", 0),
                    "downloads": photo.get("downloads", 0),
                    "views": photo.get("views", 0),
                    "season": (photo_date.month % 12) // 3,
                    "month": photo_date.month,
                    "day_of_year": photo_date.timetuple().tm_yday,
                }
                training_rows.append(row)
                self.stats["processed"] += 1
                print(f" ✓ hue={visual['hue_shift']:.0f} cloud={visual['cloud_density']:.2f}")

                if len(training_rows) >= num_target_samples:
                    break
            except Exception as e:
                self.stats["failed"] += 1
                print(f" ❌ {str(e)[:40]}")
                self.failed_photos.append(photo.get("id", "unknown"))

        df = pd.DataFrame(training_rows)
        self._print_stats(df)
        return df

    def _print_stats(self, df: pd.DataFrame):
        print("\n" + "=" * 70)
        print("SCRAPING STATISTICS")
        print("=" * 70)
        print(f"Photos attempted:     {self.stats['attempted']}")
        print(f"Photos with features: {self.stats['downloaded']}")
        print(f"Rows kept:            {self.stats['processed']}")
        print(f"Failed:               {self.stats['failed']}")
        print(f"Success rate:         {self.stats['processed'] / max(self.stats['attempted'], 1) * 100:.1f}%")
        print(f"Queries used:         {self.stats['queries_used']}")
        print(f"Sources:              {self.stats['sources']}")
        print(f"Weather matched:      {self.stats['weather_matched']}")
        print(f"Weather prior fallbk: {self.stats['weather_fallback']}")
        if len(df):
            print(f"\nFinal dataset: {len(df)} rows × {len(df.columns)} columns")
            visual_cols = [c for c in (
                "hue_shift", "saturation", "brightness", "warmth",
                "contrast", "cloud_density", "colorfulness", "warm_ratio",
            ) if c in df.columns]
            print("\nVisual feature summary:")
            print(df[visual_cols].describe().round(3))

    def save_dataset(self, df: pd.DataFrame, filename: str = "sunset_real_training_data.csv"):
        if len(df) == 0:
            print("❌ No data to save!")
            return
        df.to_csv(filename, index=False)
        print(f"\n💾 Saved to {filename}")
        print(f"   Rows: {len(df)} | Columns: {list(df.columns)}")

    def dataset_quality_report(self, df: pd.DataFrame) -> Dict:
        """Return summary stats useful for judging training readiness."""
        if df is None or len(df) == 0:
            return {"ok": False, "rows": 0}
        report = {
            "ok": True,
            "rows": int(len(df)),
            "columns": list(df.columns),
            "geo_coverage": float(df["latitude"].notna().mean()) if "latitude" in df else 0.0,
            "real_weather_share": float((df.get("weather_source") == "open-meteo-archive").mean())
            if "weather_source" in df
            else 0.0,
            "hue_std": float(df["hue_shift"].std()) if "hue_shift" in df else None,
            "sources": df["source"].value_counts().to_dict() if "source" in df else {},
        }
        return report


if __name__ == "__main__":
    scraper = ImprovedRealSunsetDataScraper()
    print("\n🌅 ENHANCED REAL SUNSET DATA COLLECTION\n")
    training_df = scraper.create_real_training_dataset(num_target_samples=200)

    if len(training_df) > 0:
        print("\n📊 DATASET OVERVIEW\n")
        print(training_df.head(8))
        print("\nQuality report:", scraper.dataset_quality_report(training_df))
        out = os.path.join(
            os.path.dirname(__file__),
            "backend",
            "model",
            "sunset_real_training_data.csv",
        )
        os.makedirs(os.path.dirname(out), exist_ok=True)
        scraper.save_dataset(training_df, filename=out)
        print(
            "\nRetrain with:\n"
            "  cd backend && ../venv/bin/python -c \"from model.sunset_ml_models import SunsetGradientBoostingModel; "
            "import pandas as pd; df=pd.read_csv('model/sunset_real_training_data.csv'); "
            "m=SunsetGradientBoostingModel(); m.train(df); m.save('model/sunset_model_real_v1.pkl')\""
        )
    else:
        print("\n❌ Failed to create dataset. Set UNSPLASH_ACCESS_KEY and check network.")
