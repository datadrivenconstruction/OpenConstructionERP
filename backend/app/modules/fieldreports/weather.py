"""Weather data fetcher using OpenWeatherMap API.

Optional -- gracefully degrades if no API key configured.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_weather(lat: float, lon: float, api_key: str | None = None) -> dict | None:
    """Fetch current weather from OpenWeatherMap.

    Returns:
        {
            "temperature_c": 22.5,
            "feels_like_c": 21.0,
            "humidity_pct": 65,
            "wind_speed_ms": 3.5,
            "wind_direction": "NW",
            "description": "partly cloudy",
            "icon": "02d",
            "precipitation_mm": 0.0,
        }
    Returns None if API key is not configured or request fails.
    """
    if not api_key:
        return None

    url = (
        f"https://api.openweathermap.org/data/2.5/weather"
        f"?lat={lat}&lon={lon}&appid={api_key}&units=metric"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("OpenWeatherMap returned %d", resp.status_code)
                return None
            data = resp.json()

            return {
                "temperature_c": data.get("main", {}).get("temp"),
                "feels_like_c": data.get("main", {}).get("feels_like"),
                "humidity_pct": data.get("main", {}).get("humidity"),
                "wind_speed_ms": data.get("wind", {}).get("speed"),
                "wind_direction": _degrees_to_compass(data.get("wind", {}).get("deg", 0)),
                "description": data.get("weather", [{}])[0].get("description", ""),
                "icon": data.get("weather", [{}])[0].get("icon", ""),
                "precipitation_mm": data.get("rain", {}).get("1h", 0.0),
            }
    except Exception:
        logger.exception("Weather fetch failed")
        return None


def _degrees_to_compass(degrees: float) -> str:
    """Convert wind direction in degrees to a 16-point compass label."""
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    idx = round(degrees / 22.5) % 16
    return dirs[idx]
