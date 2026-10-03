"""
Advisory generator — Python version for testing.
Production version lives in vayuvani-app/lib/advisory.ts (AI SDK + Vercel AI Gateway).

Uses Anthropic Python SDK directly for standalone testing.
Set ANTHROPIC_API_KEY in .env before running test_samples.py.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional
import anthropic
from dotenv import load_dotenv

from .prompts import AdvisoryInput, build_prompt, time_of_day

load_dotenv()
logger = logging.getLogger(__name__)

# Fast + cheap — good enough for advisory generation
MODEL = "claude-haiku-4-5-20251001"


def generate_advisory(
    neighborhood: str,
    station_name: str,
    aqi: int,
    category: str,
    pm25: Optional[float],
    pm10: Optional[float],
    no2: Optional[float],
    dominant_pollutant: str,
    language: str = "en",
    hour_utc: Optional[int] = None,
) -> str:
    """
    Generate a plain-language health advisory for voice output.
    Returns the advisory string, or a safe fallback if generation fails.
    """
    if hour_utc is None:
        hour_utc = datetime.now(timezone.utc).hour

    inp = AdvisoryInput(
        neighborhood=neighborhood,
        station_name=station_name,
        aqi=aqi,
        category=category,
        pm25=pm25,
        pm10=pm10,
        no2=no2,
        dominant_pollutant=dominant_pollutant,
        language=language,
        time_of_day=time_of_day(hour_utc),
    )

    prompt = build_prompt(inp)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        logger.info(f"Advisory generated for {neighborhood} ({category}): {len(text)} chars")
        return text
    except Exception as e:
        logger.error(f"Advisory generation failed: {e}")
        return _fallback_advisory(category, language)


def _fallback_advisory(category: str, language: str) -> str:
    """Safe static fallback if LLM call fails."""
    fallbacks_en = {
        "Good": "Air quality in your area is good today. You can go outside freely.",
        "Satisfactory": "Air quality is satisfactory. People with breathing conditions should limit outdoor time.",
        "Moderate": "Air quality is moderate. Limit outdoor exercise and wear a mask if you have breathing problems.",
        "Poor": "Air quality is poor. Everyone should reduce outdoor time and wear an N95 mask if going outside.",
        "Very Poor": "Air quality is very poor. Stay indoors and avoid all outdoor activity.",
        "Severe": "Air quality is at emergency levels. Do not go outside. Seal windows and doors.",
    }
    fallbacks_hi = {
        "Good": "आपके क्षेत्र में हवा आज अच्छी है। आप बाहर जा सकते हैं।",
        "Satisfactory": "हवा संतोषजनक है। सांस की बीमारी वालों को बाहर कम समय बिताना चाहिए।",
        "Moderate": "हवा मध्यम स्तर की है। बाहरी व्यायाम सीमित करें।",
        "Poor": "हवा खराब है। बाहर कम निकलें और N95 मास्क पहनें।",
        "Very Poor": "हवा बहुत खराब है। घर के अंदर रहें।",
        "Severe": "हवा की स्थिति आपातकालीन है। बाहर बिल्कुल न जाएं।",
    }
    table = fallbacks_hi if language == "hi" else fallbacks_en
    return table.get(category, table["Severe"])
