"""
Static spoken advisories per NAQI category, Hindi and English.

Standard library only: used by the LLM advisory as its fallback and by the
phone webhook directly (no LLM in the 2 s hot path).
"""


def fallback_advisory(category: str, language: str) -> str:
    """Safe static advisory for a NAQI category."""
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
