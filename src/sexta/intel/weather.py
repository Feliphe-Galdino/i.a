"""Clima pelo Open-Meteo (gratuito, sem chave) + avisos derivados da previsão."""

from __future__ import annotations

from typing import Any

from .http import FetchError, HttpClient

SOURCE = "Open-Meteo (open-meteo.com)"

WEATHER_CODES = {
    0: "céu limpo",
    1: "predominantemente limpo",
    2: "parcialmente nublado",
    3: "nublado",
    45: "neblina",
    48: "neblina com geada",
    51: "garoa fraca",
    53: "garoa",
    55: "garoa forte",
    56: "garoa congelante",
    57: "garoa congelante forte",
    61: "chuva fraca",
    63: "chuva",
    65: "chuva forte",
    66: "chuva congelante",
    67: "chuva congelante forte",
    71: "neve fraca",
    73: "neve",
    75: "neve forte",
    77: "grãos de neve",
    80: "pancadas de chuva fracas",
    81: "pancadas de chuva",
    82: "pancadas de chuva fortes",
    85: "pancadas de neve",
    86: "pancadas de neve fortes",
    95: "tempestade",
    96: "tempestade com granizo",
    99: "tempestade com granizo forte",
}


def describe(code: int | None) -> str:
    return WEATHER_CODES.get(int(code), "condição desconhecida") if code is not None else "—"


async def geocode(http: HttpClient, name: str) -> dict[str, Any]:
    data = await http.json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": name, "count": 1, "language": "pt", "format": "json"},
    )
    results = data.get("results") or []
    if not results:
        raise FetchError(f"cidade não encontrada: {name}")
    r = results[0]
    return {
        "name": r.get("name"),
        "admin1": r.get("admin1"),
        "country": r.get("country"),
        "lat": r["latitude"],
        "lon": r["longitude"],
        "timezone": r.get("timezone") or "auto",
    }


async def forecast(http: HttpClient, lat: float, lon: float, days: int = 7) -> dict[str, Any]:
    data = await http.json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max,wind_speed_10m_max,uv_index_max",
            "timezone": "auto",
            "forecast_days": max(1, min(16, days)),
        },
    )
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    days_out = []
    for i, date in enumerate(daily.get("time") or []):

        def pick(key: str, index: int = i):
            values = daily.get(key) or []
            return values[index] if index < len(values) else None

        days_out.append(
            {
                "date": date,
                "tmax": pick("temperature_2m_max"),
                "tmin": pick("temperature_2m_min"),
                "rain_mm": pick("precipitation_sum"),
                "rain_prob": pick("precipitation_probability_max"),
                "wind_max": pick("wind_speed_10m_max"),
                "uv_max": pick("uv_index_max"),
                "code": pick("weather_code"),
                "desc": describe(pick("weather_code")),
            }
        )
    return {
        "current": {
            "time": current.get("time"),
            "temp": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind": current.get("wind_speed_10m"),
            "code": current.get("weather_code"),
            "desc": describe(current.get("weather_code")),
        },
        "daily": days_out,
        "timezone": data.get("timezone"),
        "source": SOURCE,
    }


DEFAULT_THRESHOLDS = {"rain_mm": 30.0, "temp_max": 35.0, "temp_min": 5.0, "wind_kmh": 60.0}


def weather_risks(daily: list[dict[str, Any]], thresholds: dict[str, float] | None = None, days: int = 2) -> list[str]:
    """Avisos simples para hoje/amanhã (estimativas a partir da previsão — não são alertas oficiais)."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    risks: list[str] = []
    labels = ["hoje", "amanhã"]
    for i, day in enumerate(daily[:days]):
        when = labels[i] if i < len(labels) else day["date"]
        if day.get("rain_mm") is not None and day["rain_mm"] >= t["rain_mm"]:
            risks.append(f"Chuva forte prevista {when}: {day['rain_mm']:.0f} mm")
        if day.get("tmax") is not None and day["tmax"] >= t["temp_max"]:
            risks.append(f"Calor intenso {when}: máxima de {day['tmax']:.0f} °C")
        if day.get("tmin") is not None and day["tmin"] <= t["temp_min"]:
            risks.append(f"Frio intenso {when}: mínima de {day['tmin']:.0f} °C")
        if day.get("wind_max") is not None and day["wind_max"] >= t["wind_kmh"]:
            risks.append(f"Ventos fortes {when}: até {day['wind_max']:.0f} km/h")
        if day.get("code") in (95, 96, 99):
            risks.append(f"Possibilidade de tempestade {when}")
    return risks
