"""
Sunset viewpoint finder
=======================
Finds high / scenic spots near a location using OpenStreetMap Overpass
(tourism=viewpoint, natural=peak) and Open-Meteo elevation.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import requests


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _cardinal(bearing: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((bearing + 22.5) // 45) % 8]


class ViewpointFinder:
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

    def find_viewpoints(
        self,
        lat: float,
        lon: float,
        radius_m: int = 25000,
        limit: int = 8,
        location_name: str = "",
    ) -> List[Dict]:
        places = self._query_overpass(lat, lon, radius_m)
        if not places:
            # Soft fallback: suggest heading west to higher ground
            return [
                {
                    "name": f"West-facing high ground near {location_name or 'you'}",
                    "type": "suggestion",
                    "latitude": lat,
                    "longitude": lon - 0.05,
                    "distance_km": 4.0,
                    "elevation_m": None,
                    "direction": "W",
                    "why": (
                        "No mapped viewpoints found nearby. At sunset, head toward "
                        "open west-facing elevation for an unobstructed horizon."
                    ),
                    "maps_url": self._maps_url(lat, lon - 0.05),
                }
            ]

        elev = self._elevations([(p["latitude"], p["longitude"]) for p in places])
        for i, p in enumerate(places):
            p["elevation_m"] = elev[i] if i < len(elev) else None
            p["distance_km"] = round(
                _haversine_km(lat, lon, p["latitude"], p["longitude"]), 2
            )
            bearing = _bearing_deg(lat, lon, p["latitude"], p["longitude"])
            p["direction"] = _cardinal(bearing)
            p["maps_url"] = self._maps_url(p["latitude"], p["longitude"])
            elev_txt = (
                f"{int(p['elevation_m'])} m elevation"
                if p.get("elevation_m") is not None
                else "scenic overlook"
            )
            p["why"] = (
                f"{p.get('type', 'viewpoint').replace('_', ' ').title()} · {elev_txt} · "
                f"{p['distance_km']} km {p['direction']} of your location. "
                f"Arrive before sunset for the best light."
            )

        # Prefer higher elevation, then closer
        places.sort(
            key=lambda p: (
                -(p["elevation_m"] if p.get("elevation_m") is not None else -9999),
                p["distance_km"],
            )
        )
        return places[:limit]

    def _query_overpass(self, lat: float, lon: float, radius_m: int) -> List[Dict]:
        query = f"""
        [out:json][timeout:25];
        (
          node["tourism"="viewpoint"](around:{radius_m},{lat},{lon});
          node["natural"="peak"](around:{radius_m},{lat},{lon});
          node["natural"="cliff"](around:{radius_m},{lat},{lon});
          way["tourism"="viewpoint"](around:{radius_m},{lat},{lon});
        );
        out center 40;
        """
        try:
            resp = requests.post(
                self.OVERPASS_URL,
                data={"data": query},
                timeout=30,
                headers={"User-Agent": "SunCast/1.0"},
            )
            resp.raise_for_status()
            elements = resp.json().get("elements") or []
        except Exception as e:
            print(f"Overpass error: {e}")
            return []

        places = []
        seen = set()
        for el in elements:
            tags = el.get("tags") or {}
            if "center" in el:
                plat, plon = el["center"]["lat"], el["center"]["lon"]
            else:
                plat, plon = el.get("lat"), el.get("lon")
            if plat is None or plon is None:
                continue
            key = (round(plat, 4), round(plon, 4))
            if key in seen:
                continue
            seen.add(key)
            kind = (
                "viewpoint"
                if tags.get("tourism") == "viewpoint"
                else tags.get("natural") or "scenic"
            )
            name = tags.get("name") or f"Unnamed {kind}"
            places.append(
                {
                    "name": name,
                    "type": kind,
                    "latitude": plat,
                    "longitude": plon,
                    "osm_id": el.get("id"),
                }
            )
        return places

    def _elevations(self, coords: List[tuple]) -> List[Optional[float]]:
        if not coords:
            return []
        try:
            lats = ",".join(str(c[0]) for c in coords)
            lons = ",".join(str(c[1]) for c in coords)
            resp = requests.get(
                self.ELEVATION_URL,
                params={"latitude": lats, "longitude": lons},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("elevation") or [None] * len(coords)
        except Exception as e:
            print(f"Elevation error: {e}")
            return [None] * len(coords)

    def _maps_url(self, lat: float, lon: float) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
