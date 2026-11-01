"""
Display labels shared by the engine, the public feed, the phone line and the
agency reports. Standard library only, so the voice webhook can import it
without pulling in numpy/pandas.
"""

LABELS_EN = {
    "traffic": "traffic exhaust",
    "biomass_burning": "biomass/garbage burning",
    "industry": "industry/power (SO2)",
    "dust": "construction/road dust",
    "regional_background": "regional background",
    "transported_smoke": "smoke transported from upwind fires",
}
LABELS_HI = {
    "traffic": "गाड़ियों का धुआं",
    "biomass_burning": "कचरा/लकड़ी जलाना",
    "industry": "उद्योग/बिजलीघर",
    "dust": "निर्माण/सड़क की धूल",
    "regional_background": "पूरे इलाके का प्रदूषण",
    "transported_smoke": "दूर की आग का धुआं",
}
CONF_HI = {"low": "कम", "medium": "मध्यम", "high": "अधिक"}

SECTORS_HI = {
    "N": "उत्तर", "NE": "उत्तर-पूर्व", "E": "पूर्व", "SE": "दक्षिण-पूर्व",
    "S": "दक्षिण", "SW": "दक्षिण-पश्चिम", "W": "पश्चिम", "NW": "उत्तर-पश्चिम",
}
SECTORS_EN = {
    "N": "north", "NE": "north-east", "E": "east", "SE": "south-east",
    "S": "south", "SW": "south-west", "W": "west", "NW": "north-west",
}

# Citizen report type (spoken by callers) -> engine source class.
CITIZEN_TYPE_TO_SOURCE = {
    "burning": "biomass_burning",
    "vehicular": "traffic",
    "industrial": "industry",
    "dust": "dust",
}
