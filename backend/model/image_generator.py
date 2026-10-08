"""
AI / procedural sunset image generation for SunCast
===================================================
Providers:
  1. Replicate (REPLICATE_API_TOKEN) — real text-to-image
  2. Pollinations — attempted when available
  3. Procedural Pillow renderer — always works offline from ML params

The procedural fallback paints a sky from hue/saturation/brightness/clouds
so the UI never shows a broken image when hosted AI APIs require payment.
"""

from __future__ import annotations

import base64
import io
import os
import time
import urllib.parse
from typing import Dict, Optional, Tuple

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter


class SunsetImageGenerator:
    """Wrapper around hosted T2I APIs with a reliable procedural fallback."""

    REPLICATE_MODEL = os.getenv(
        "REPLICATE_MODEL",
        "black-forest-labs/flux-schnell",
    )

    def __init__(
        self,
        provider: Optional[str] = None,
        replicate_token: Optional[str] = None,
    ):
        self.replicate_token = replicate_token or os.getenv("REPLICATE_API_TOKEN")
        requested = (provider or os.getenv("IMAGE_PROVIDER") or "auto").lower()

        if requested == "auto":
            self.provider = "replicate" if self.replicate_token else "auto"
        else:
            self.provider = requested

    def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 768,
        seed: Optional[int] = None,
        hue_shift: float = 45,
        saturation: float = 0.7,
        brightness: float = 0.75,
        cloud_density: float = 0.4,
        location_name: Optional[str] = None,
    ) -> Dict:
        prompt = self._enrich_prompt(prompt or "", location_name=location_name)
        width = int(np.clip(int(width or 1024), 64, 1280))
        height = int(np.clip(int(height or 768), 64, 960))
        errors = []

        # Prefer real AI when configured
        if self.provider in ("replicate", "auto") and self.replicate_token:
            try:
                return self._generate_replicate(prompt, width, height, seed)
            except Exception as e:
                errors.append(f"replicate: {e}")

        if self.provider in ("pollinations", "auto"):
            try:
                result = self._generate_pollinations(prompt, width, height, seed)
                if result.get("success"):
                    return result
                errors.append(f"pollinations: {result.get('error')}")
            except Exception as e:
                errors.append(f"pollinations: {e}")

        # Always-available local rendition from ML visual params
        try:
            result = self._generate_procedural(
                width=width,
                height=height,
                seed=seed,
                hue_shift=hue_shift,
                saturation=saturation,
                brightness=brightness,
                cloud_density=cloud_density,
                prompt=prompt,
                location_name=location_name,
            )
            if errors:
                result["fallback_errors"] = errors
            return result
        except Exception as e:
            return {
                "success": False,
                "provider": "procedural",
                "error": str(e),
                "prior_errors": errors,
            }

    def _enrich_prompt(self, prompt: str, location_name: Optional[str] = None) -> str:
        """Append photography cues and reinforce location grounding."""
        base = " ".join(prompt.split())
        place = (location_name or "").strip()
        place_cue = (
            f" highly recognizable view of {place}, landmark silhouettes of {place},"
            if place
            else ""
        )
        suffix = (
            f"{place_cue} photorealistic sunset landscape photography, natural atmospheric "
            "perspective, soft golden hour lighting, high dynamic range, "
            "no text, no watermark, no people"
        )
        if "photorealistic" in base.lower() and (not place or place.lower() in base.lower()):
            return base if not place_cue else f"{base}.{place_cue}"
        return f"{base}. {suffix}".strip() if base else suffix.strip()

    def _generate_pollinations(
        self,
        prompt: str,
        width: int,
        height: int,
        seed: Optional[int],
    ) -> Dict:
        encoded = urllib.parse.quote(prompt[:500])
        params = {
            "width": min(width, 768),
            "height": min(height, 576),
            "nologo": "true",
        }
        if seed is not None:
            params["seed"] = int(seed)
        query = urllib.parse.urlencode(params)
        image_url = f"https://image.pollinations.ai/prompt/{encoded}?{query}"

        resp = requests.get(
            image_url,
            timeout=12,
            allow_redirects=True,
            headers={"User-Agent": "SunCast/1.0"},
        )
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.status_code != 200 or "image" not in ctype or len(resp.content) < 1000:
            raise RuntimeError(
                f"Pollinations unavailable (HTTP {resp.status_code}, "
                f"type={ctype}, bytes={len(resp.content)})"
            )

        b64 = base64.b64encode(resp.content).decode("ascii")
        return {
            "success": True,
            "provider": "pollinations",
            "image_url": f"data:{ctype};base64,{b64}",
            "prompt": prompt,
            "width": width,
            "height": height,
        }

    def _generate_replicate(
        self,
        prompt: str,
        width: int,
        height: int,
        seed: Optional[int],
    ) -> Dict:
        if not self.replicate_token:
            raise RuntimeError("REPLICATE_API_TOKEN is not set")

        headers = {
            "Authorization": f"Bearer {self.replicate_token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }
        payload = {
            "input": {
                "prompt": prompt,
                "aspect_ratio": "4:3" if width >= height else "3:4",
                "output_format": "jpg",
                "go_fast": True,
            }
        }
        if seed is not None:
            payload["input"]["seed"] = int(seed)

        create = requests.post(
            f"https://api.replicate.com/v1/models/{self.REPLICATE_MODEL}/predictions",
            headers=headers,
            json=payload,
            timeout=90,
        )
        create.raise_for_status()
        prediction = create.json()

        status = prediction.get("status")
        get_url = prediction.get("urls", {}).get("get")
        attempts = 0
        while status not in ("succeeded", "failed", "canceled") and get_url and attempts < 40:
            time.sleep(1.5)
            poll = requests.get(get_url, headers=headers, timeout=30)
            poll.raise_for_status()
            prediction = poll.json()
            status = prediction.get("status")
            attempts += 1

        if status != "succeeded":
            err = prediction.get("error") or status or "unknown error"
            raise RuntimeError(f"Replicate prediction failed: {err}")

        output = prediction.get("output")
        image_url = output[0] if isinstance(output, list) and output else output
        if not image_url:
            raise RuntimeError("Replicate returned no image URL")

        # Prefer embedding so the browser never depends on third-party hotlink rules
        try:
            img = requests.get(image_url, timeout=60)
            if img.status_code == 200 and len(img.content) > 1000:
                b64 = base64.b64encode(img.content).decode("ascii")
                ctype = img.headers.get("content-type", "image/jpeg")
                image_url = f"data:{ctype};base64,{b64}"
        except Exception:
            pass

        return {
            "success": True,
            "provider": "replicate",
            "image_url": image_url,
            "prompt": prompt,
            "width": width,
            "height": height,
            "prediction_id": prediction.get("id"),
        }

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> Tuple[int, int, int]:
        h = (h % 360) / 60.0
        c = v * s
        x = c * (1 - abs(h % 2 - 1))
        m = v - c
        if 0 <= h < 1:
            r, g, b = c, x, 0
        elif 1 <= h < 2:
            r, g, b = x, c, 0
        elif 2 <= h < 3:
            r, g, b = 0, c, x
        elif 3 <= h < 4:
            r, g, b = 0, x, c
        elif 4 <= h < 5:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x
        return (
            int(np.clip((r + m) * 255, 0, 255)),
            int(np.clip((g + m) * 255, 0, 255)),
            int(np.clip((b + m) * 255, 0, 255)),
        )

    def _generate_procedural(
        self,
        width: int,
        height: int,
        seed: Optional[int],
        hue_shift: float,
        saturation: float,
        brightness: float,
        cloud_density: float,
        prompt: str,
        location_name: Optional[str] = None,
    ) -> Dict:
        rng = np.random.default_rng(int(seed) if seed is not None else 42)
        width = int(np.clip(width, 320, 1280))
        height = int(np.clip(height, 240, 960))

        hue = float(hue_shift) % 360
        sat = float(np.clip(saturation, 0.15, 1.0))
        bright = float(np.clip(brightness, 0.25, 1.0))
        clouds = float(np.clip(cloud_density, 0.0, 1.0))

        # Vertical sky gradient: deep dusk → mid hue → bright near horizon
        yy = np.linspace(0, 1, height)[:, None]
        xx = np.linspace(0, 1, width)[None, :]

        top = self._hsv_to_rgb(hue + 40, sat * 0.35, bright * 0.18)
        mid = self._hsv_to_rgb(hue + 10, sat * 0.85, bright * 0.55)
        bot = self._hsv_to_rgb(max(hue - 8, 5), min(sat * 1.05, 1.0), min(bright * 1.05, 1.0))
        glow = self._hsv_to_rgb(hue, sat * 0.55, min(bright * 1.15, 1.0))

        # Blend bands
        t1 = np.clip((yy - 0.0) / 0.45, 0, 1)
        t2 = np.clip((yy - 0.45) / 0.35, 0, 1)
        sky = np.zeros((height, width, 3), dtype=np.float32)
        for i, (a, b) in enumerate(zip(top, mid)):
            sky[:, :, i] = a * (1 - t1) + b * t1
        for i, (a, b) in enumerate(zip(mid, bot)):
            band = sky[:, :, i]
            sky[:, :, i] = band * (1 - t2) + b * t2

        # Sun glow near horizon center
        sun_y, sun_x = 0.72, 0.5
        dist = np.sqrt((xx - sun_x) ** 2 + ((yy - sun_y) * 1.35) ** 2)
        glow_w = np.exp(-(dist ** 2) / (0.045 + 0.02 * (1 - clouds)))
        for i, c in enumerate(glow):
            sky[:, :, i] = sky[:, :, i] * (1 - 0.55 * glow_w) + c * (0.55 * glow_w)

        # Soft cloud layers
        n_clouds = int(4 + clouds * 14)
        cloud_layer = np.zeros((height, width), dtype=np.float32)
        for _ in range(n_clouds):
            cy = rng.uniform(0.15, 0.78)
            cx = rng.uniform(0.05, 0.95)
            sx = rng.uniform(0.08, 0.28)
            sy = rng.uniform(0.02, 0.07)
            blob = np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2))
            cloud_layer += blob * rng.uniform(0.35, 0.9)

        if cloud_layer.max() > 0:
            cloud_layer = cloud_layer / cloud_layer.max()
        cloud_layer *= clouds

        # Cloud color: lit underside + cooler tops
        lit = np.array(self._hsv_to_rgb(hue, sat * 0.7, min(bright * 0.95, 1.0)), dtype=np.float32)
        shade = np.array(self._hsv_to_rgb(hue + 25, sat * 0.25, bright * 0.35), dtype=np.float32)
        underside = np.clip((yy - 0.4) / 0.4, 0, 1)
        for i in range(3):
            cloud_col = shade[i] * (1 - underside) + lit[i] * underside
            sky[:, :, i] = (
                sky[:, :, i] * (1 - 0.75 * cloud_layer)
                + cloud_col * (0.75 * cloud_layer)
            )

        # Subtle film grain
        grain = rng.normal(0, 3.5, size=sky.shape)
        sky = np.clip(sky + grain, 0, 255).astype(np.uint8)

        img = Image.fromarray(sky, mode="RGB")
        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))

        # Soft ground silhouette
        draw = ImageDraw.Draw(img)
        ground_y = int(height * 0.88)
        draw.rectangle([(0, ground_y), (width, height)], fill=(18, 12, 22))
        # Gentle hills
        pts = [(0, height)]
        for x in range(0, width + 1, max(8, width // 40)):
            y = ground_y - int(12 + 18 * np.sin(x / 70.0) + 10 * np.sin(x / 33.0))
            pts.append((x, y))
        pts.append((width, height))
        draw.polygon(pts, fill=(22, 14, 28))

        # Location caption so procedural fallback still reflects the place
        place = (location_name or "").strip()
        if place:
            from PIL import ImageFont
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 22)
            except Exception:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
                except Exception:
                    font = ImageFont.load_default()
            label = f"SunCast · {place}"
            # Soft dark plate for readability
            tw = min(width - 24, 12 * len(label))
            draw.rectangle([(16, height - 48), (16 + tw, height - 16)], fill=(12, 8, 16, 180) if False else (12, 8, 16))
            draw.text((24, height - 42), label, fill=(255, 236, 220), font=font)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        return {
            "success": True,
            "provider": "procedural",
            "image_url": f"data:image/jpeg;base64,{b64}",
            "prompt": prompt,
            "width": width,
            "height": height,
            "location_name": place or None,
            "note": "Local ML-conditioned sky render (set REPLICATE_API_TOKEN for hosted AI images)",
        }
