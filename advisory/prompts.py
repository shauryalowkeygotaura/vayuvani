"""
Prompt builder for VayuVani advisory generation.
Produces advisory text for both Hindi and English voice output.
"""

from .knowledge import get_chunk, KnowledgeChunk
from dataclasses import dataclass
from typing import Optional


@dataclass
class AdvisoryInput:
    neighborhood: str
    station_name: str
    aqi: int
    category: str
    pm25: Optional[float]
    pm10: Optional[float]
    no2: Optional[float]
    dominant_pollutant: str
    language: str  # 'en' or 'hi'
    time_of_day: str  # 'morning' | 'afternoon' | 'evening' | 'night'


def build_prompt(inp: AdvisoryInput) -> str:
    chunk = get_chunk(inp.category)
    lang_instruction = (
        "Respond in Hindi (Devanagari script). Use simple, everyday Hindi — not formal or literary."
        if inp.language == "hi"
        else "Respond in simple, clear English."
    )

    pollutant_line = _format_pollutants(inp)
    actions = (
        "\n".join(f"- {a}" for a in chunk.recommended_actions_hi)
        if inp.language == "hi"
        else "\n".join(f"- {a}" for a in chunk.recommended_actions)
    )

    return f"""You are VayuVani, an AI air quality advisor for Delhi residents. {lang_instruction}

CURRENT CONDITIONS — {inp.neighborhood}:
- Station: {inp.station_name}
- AQI: {inp.aqi} ({inp.category})
- {pollutant_line}
- Main pollutant: {inp.dominant_pollutant.upper()}
- Time: {inp.time_of_day}

HEALTH GUIDANCE (from CPCB):
{chunk.cpcb_health_impact}
{chunk.cpcb_cautionary_statement}

RECOMMENDED ACTIONS:
{actions}

VULNERABLE GROUPS TO WARN:
{', '.join(chunk.vulnerable_groups) if chunk.vulnerable_groups else 'No specific groups — general caution for all'}

YOUR TASK:
Generate a voice advisory — exactly 3 sentences, max 70 words total.
Structure:
1. Current air quality status (plain language, mention the neighborhood and category)
2. The single most important action to take right now
3. Who should be most careful (if applicable) OR reassurance (if Good/Satisfactory)

Rules:
- No numbers or AQI values in the output — only plain language descriptions
- Conversational, warm tone — like a knowledgeable friend, not a government bulletin
- No lists, no bullet points — flowing speech only
- Do NOT start with "I" or "VayuVani"
- Do NOT mention WHO or CPCB by name"""


def _format_pollutants(inp: AdvisoryInput) -> str:
    parts = []
    if inp.pm25 is not None:
        parts.append(f"PM2.5: {inp.pm25:.1f} µg/m³")
    if inp.pm10 is not None:
        parts.append(f"PM10: {inp.pm10:.1f} µg/m³")
    if inp.no2 is not None:
        parts.append(f"NO2: {inp.no2:.1f} µg/m³")
    return " | ".join(parts) if parts else "Pollutant data limited"


def time_of_day(hour_utc: int) -> str:
    """Convert UTC hour to IST and return time-of-day label."""
    ist_hour = (hour_utc + 5) % 24 + (1 if hour_utc >= 19 else 0)  # IST = UTC+5:30
    if 5 <= ist_hour < 12:
        return "morning"
    elif 12 <= ist_hour < 17:
        return "afternoon"
    elif 17 <= ist_hour < 21:
        return "evening"
    else:
        return "night"
