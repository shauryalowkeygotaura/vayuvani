"""
Advisory generator — Python version for testing.
Production version lives in vayuvani-app/lib/advisory.ts (Groq, model switching).

Uses the vault's shared Groq pool (advisory/groq_pool.py, vendored by
Scripts/sync_groq_pool.py): key rotation across accounts, model fallback on a
retired or throttled model. Was the Anthropic SDK until 2026-10-03.
Set GROQ_API_KEY (Doppler or .env) before running test_samples.py.
"""

import os
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

from . import groq_pool
from .prompts import AdvisoryInput, build_prompt, time_of_day

load_dotenv()
logger = logging.getLogger(__name__)

# Fast tier first: qwen answers in ~0.5s with no hidden reasoning tokens, and
# the pool walks to gpt-oss if it is retired or throttled.
MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b")


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
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> str:
    """
    Generate a plain-language health advisory for voice output.
    Returns the advisory string, or a safe fallback if generation fails.
    With caller coordinates, appends the "Kaun?" line (who caused the latest
    nearby spike) from the attribution feed: a template, no extra LLM call.
    """
    advisory = _generate(neighborhood, station_name, aqi, category, pm25, pm10, no2,
                         dominant_pollutant, language, hour_utc)
    return with_kaun(advisory, latitude, longitude, language)


def with_kaun(advisory: str, latitude: Optional[float], longitude: Optional[float],
              language: str) -> str:
    if latitude is None or longitude is None:
        return advisory
    try:
        from attribution.publish.voice import answer
        line = answer(latitude, longitude, language)
    except Exception as e:  # the advisory must never fail because of Kaun
        logger.warning(f"Kaun line skipped: {e}")
        return advisory
    return f"{advisory} {line}" if line else advisory


def _generate(neighborhood, station_name, aqi, category, pm25, pm10, no2,
              dominant_pollutant, language, hour_utc) -> str:
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

    try:
        text = ""
        # One model at a time so a reply that fails the language check can be
        # handed to the next model; the pool still rotates keys and waits out
        # throttles inside each call.
        for model in MODELS:
            resp = groq_pool.chat(
                (model,),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                require_content=True,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text and _reads_clean(text, language):
                break
            logger.warning(f"{model} gave an unusable {language} advisory; trying next model")
            text = ""
        if not text:
            raise ValueError("no clean advisory from any model")
        logger.info(f"Advisory generated for {neighborhood} ({category}): {len(text)} chars")
        return text
    except Exception as e:
        logger.error(f"Advisory generation failed: {e}")
        return _fallback_advisory(category, language)


# Latin words allowed inside a Hindi advisory. Anything else Latin is a model
# glitch: qwen once dropped a Turkish word ("özellikle") mid-sentence, which a
# Hindi-speaking caller would hear read aloud.
_ALLOWED_LATIN = {"n95", "aqi", "pm", "pm2", "pm10", "no2", "who", "cpcb"}


def _reads_clean(text: str, language: str) -> bool:
    if language != "hi":
        return True
    words = re.findall(r"[A-Za-zÀ-ɏ]+", text)
    return all(w.lower() in _ALLOWED_LATIN or len(w) <= 2 for w in words)


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
