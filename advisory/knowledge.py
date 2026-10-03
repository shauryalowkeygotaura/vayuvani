"""
VayuVani knowledge base — CPCB guidelines + WHO AQ standards.

Source 1: CPCB National Air Quality Index technical document
Source 2: WHO Air Quality Guidelines 2021
Source 3: SAFAR health impact chart

No vector DB needed — full context fits in one LLM call.
We select the correct chunk at query time by AQI category.
"""

from dataclasses import dataclass


@dataclass
class KnowledgeChunk:
    category: str
    aqi_range: str
    cpcb_health_impact: str
    cpcb_cautionary_statement: str
    who_note: str
    vulnerable_groups: list[str]
    recommended_actions: list[str]
    recommended_actions_hi: list[str]   # Hindi equivalents for TTS


KNOWLEDGE: dict[str, KnowledgeChunk] = {
    "Good": KnowledgeChunk(
        category="Good",
        aqi_range="0–50",
        cpcb_health_impact="Minimal impact.",
        cpcb_cautionary_statement="None required.",
        who_note="Below WHO annual guideline for PM2.5 (5 µg/m³). Normal outdoor activity safe.",
        vulnerable_groups=[],
        recommended_actions=[
            "Air quality is good. Enjoy outdoor activities freely.",
            "No precautions needed.",
        ],
        recommended_actions_hi=[
            "वायु गुणवत्ता अच्छी है। बाहर जाने में कोई परेशानी नहीं।",
            "कोई सावधानी ज़रूरी नहीं।",
        ],
    ),
    "Satisfactory": KnowledgeChunk(
        category="Satisfactory",
        aqi_range="51–100",
        cpcb_health_impact="Minor breathing discomfort to sensitive people.",
        cpcb_cautionary_statement=(
            "People with lung disease, such as asthma, should limit prolonged outdoor exertion."
        ),
        who_note=(
            "PM2.5 may exceed WHO 24-hour guideline (15 µg/m³). Sensitive individuals should "
            "limit prolonged heavy outdoor exertion."
        ),
        vulnerable_groups=["Asthma patients", "People with COPD", "Elderly"],
        recommended_actions=[
            "Air quality is satisfactory. Most people can go outside normally.",
            "If you have asthma or breathing problems, limit long outdoor exercise.",
            "A mask is not required for healthy adults.",
        ],
        recommended_actions_hi=[
            "हवा की गुणवत्ता संतोषजनक है। ज़्यादातर लोग सामान्य रूप से बाहर जा सकते हैं।",
            "अस्थमा या सांस की बीमारी है तो लंबी बाहरी कसरत से बचें।",
            "स्वस्थ व्यक्तियों को मास्क की ज़रूरत नहीं।",
        ],
    ),
    "Moderate": KnowledgeChunk(
        category="Moderate",
        aqi_range="101–200",
        cpcb_health_impact=(
            "Breathing discomfort to the people with lungs, heart disease, children and older adults."
        ),
        cpcb_cautionary_statement=(
            "People with heart or lung disease, older adults, and children should reduce prolonged "
            "or heavy outdoor exertion."
        ),
        who_note=(
            "PM2.5 is 2–5× above WHO 24-hour guideline. Continuous exposure at this level "
            "increases risk of cardiovascular and respiratory disease."
        ),
        vulnerable_groups=["Children", "Elderly (60+)", "Heart disease patients", "Lung disease patients", "Pregnant women"],
        recommended_actions=[
            "Air quality is moderate. Healthy adults can go out but limit heavy exercise.",
            "Wear an N95 mask if you are outdoors for more than 30 minutes.",
            "Children and elderly should avoid outdoor exertion.",
            "Keep windows closed during peak traffic hours (8–10 AM, 6–8 PM).",
        ],
        recommended_actions_hi=[
            "हवा मध्यम स्तर की है। स्वस्थ लोग बाहर जा सकते हैं पर भारी व्यायाम से बचें।",
            "30 मिनट से ज़्यादा बाहर हों तो N95 मास्क पहनें।",
            "बच्चों और बुज़ुर्गों को बाहरी गतिविधि से बचना चाहिए।",
            "पीक ट्रैफिक के समय खिड़कियाँ बंद रखें।",
        ],
    ),
    "Poor": KnowledgeChunk(
        category="Poor",
        aqi_range="201–300",
        cpcb_health_impact="Breathing discomfort to most people on prolonged exposure.",
        cpcb_cautionary_statement=(
            "People with heart or lung disease, older adults, and children should avoid prolonged "
            "or heavy outdoor exertion; everyone else should limit prolonged outdoor exertion."
        ),
        who_note=(
            "PM2.5 is 5–10× above WHO 24-hour guideline. This level is associated with "
            "measurable lung function reduction in healthy adults after a few hours of exposure."
        ),
        vulnerable_groups=[
            "Everyone", "Children", "Elderly", "Heart patients", "Lung patients",
            "Outdoor workers", "Pregnant women",
        ],
        recommended_actions=[
            "Air quality is poor. Everyone should reduce outdoor time.",
            "Wear an N95 mask if you must go outside.",
            "Avoid outdoor exercise entirely — exercise indoors today.",
            "Sensitive groups (children, elderly, patients) should stay indoors.",
            "Use an air purifier indoors if available.",
        ],
        recommended_actions_hi=[
            "हवा खराब है। सभी लोग बाहर का समय कम करें।",
            "बाहर जाना ज़रूरी हो तो N95 मास्क ज़रूर पहनें।",
            "बाहरी व्यायाम बिल्कुल न करें — आज घर के अंदर करें।",
            "बच्चे, बुज़ुर्ग और मरीज़ घर के अंदर रहें।",
            "घर में एयर प्यूरीफायर चलाएं।",
        ],
    ),
    "Very Poor": KnowledgeChunk(
        category="Very Poor",
        aqi_range="301–400",
        cpcb_health_impact="Respiratory illness on prolonged exposure. Effect may be more pronounced in people with lung and heart diseases.",
        cpcb_cautionary_statement=(
            "People with heart or lung disease, older adults, and children should avoid all outdoor "
            "activity; everyone else should avoid prolonged outdoor exertion."
        ),
        who_note=(
            "PM2.5 is 10–20× above WHO guideline. This is a public health emergency level. "
            "Even brief outdoor exposure can trigger respiratory symptoms in healthy adults."
        ),
        vulnerable_groups=["Everyone — all outdoor activity strongly discouraged"],
        recommended_actions=[
            "Air quality is very poor — health alert.",
            "Stay indoors. Avoid all outdoor activity.",
            "If you must go outside, wear an N95 mask and limit time to under 15 minutes.",
            "Seal gaps in windows and doors.",
            "If you experience coughing, chest tightness, or difficulty breathing, seek medical attention.",
        ],
        recommended_actions_hi=[
            "हवा बहुत खराब है — स्वास्थ्य चेतावनी।",
            "घर के अंदर रहें। बाहरी गतिविधि बिल्कुल न करें।",
            "बाहर जाना ज़रूरी हो तो N95 मास्क पहनें और 15 मिनट से कम समय बाहर रहें।",
            "खिड़की-दरवाज़ों की दरारें बंद करें।",
            "खांसी, छाती में जकड़न या सांस लेने में तकलीफ हो तो डॉक्टर से मिलें।",
        ],
    ),
    "Severe": KnowledgeChunk(
        category="Severe",
        aqi_range="401–500",
        cpcb_health_impact=(
            "Respiratory effects even on healthy people. Serious health impacts on people with "
            "lung/heart disease. If exposed for prolonged periods, serious health impacts on "
            "healthy people."
        ),
        cpcb_cautionary_statement=(
            "Everyone should avoid all outdoor exertion; people with heart or lung disease, "
            "older adults, and children should remain indoors and keep activity levels low."
        ),
        who_note=(
            "PM2.5 is >20× above WHO guideline. Classified as a hazardous event. Prolonged "
            "exposure at this level can cause permanent lung damage and cardiovascular stress."
        ),
        vulnerable_groups=["Everyone — emergency level"],
        recommended_actions=[
            "EMERGENCY air quality — severe health hazard.",
            "Do not go outside under any circumstances without an N95 mask.",
            "All schools and outdoor events should be cancelled.",
            "Seal all gaps in windows and doors. Run air purifier on maximum.",
            "Monitor for symptoms: headache, nausea, chest pain, difficulty breathing.",
            "Seek emergency medical care immediately if symptoms develop.",
        ],
        recommended_actions_hi=[
            "आपातकालीन वायु गुणवत्ता — गंभीर स्वास्थ्य ख़तरा।",
            "N95 मास्क के बिना किसी भी हाल में बाहर न जाएं।",
            "स्कूल और बाहरी कार्यक्रम रद्द होने चाहिए।",
            "खिड़की-दरवाज़ों की सभी दरारें बंद करें। एयर प्यूरीफायर फुल चलाएं।",
            "सिरदर्द, मतली, सीने में दर्द, सांस लेने में दिक्कत पर ध्यान दें।",
            "लक्षण दिखने पर तुरंत डॉक्टर के पास जाएं।",
        ],
    ),
}


def get_chunk(category: str) -> KnowledgeChunk:
    """Return knowledge chunk for given AQI category. Defaults to Severe if unknown."""
    return KNOWLEDGE.get(category, KNOWLEDGE["Severe"])


WHO_ANNUAL_GUIDELINES = """
WHO Air Quality Guidelines 2021 — Annual Means:
- PM2.5: 5 µg/m³ (India's NAAQS: 40 µg/m³)
- PM10: 15 µg/m³ (India's NAAQS: 60 µg/m³)
- NO2: 10 µg/m³ (India's NAAQS: 80 µg/m³)
- SO2: — (WHO 24-hr: 40 µg/m³)
- CO: 4 mg/m³ 24-hr average

Delhi's annual mean PM2.5 consistently exceeds WHO guidelines by 10–15×.
"""
