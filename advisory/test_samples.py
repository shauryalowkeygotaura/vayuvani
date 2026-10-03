"""
Week 2 validation: test advisory generation with 20 representative samples.

Usage:
    python -m advisory.test_samples
    python -m advisory.test_samples --language hi
    python -m advisory.test_samples --check-hallucinations

Each test prints: input → advisory → manual pass/fail checklist.
"""

import argparse
import json
from datetime import datetime, timezone
from .generator import generate_advisory

# 20 test cases covering:
# - All 6 AQI categories (Good → Severe)
# - Both languages
# - Different times of day
# - Known high-pollution stations (Anand Vihar, Jahangirpuri)
# - Known lower-pollution stations (Lodhi Road)
# - Edge cases: missing NO2, dominant=PM10 vs PM2.5

SAMPLES = [
    # --- GOOD ---
    {
        "id": "GOOD-01",
        "neighborhood": "Lodhi Road",
        "station_name": "Lodhi Road CPCB",
        "aqi": 38,
        "category": "Good",
        "pm25": 18.0, "pm10": 35.0, "no2": 15.0,
        "dominant_pollutant": "pm25",
        "language": "en", "hour_utc": 3,  # 8:30 AM IST
    },
    {
        "id": "GOOD-02",
        "neighborhood": "साकेत",
        "station_name": "Siri Fort CPCB",
        "aqi": 42,
        "category": "Good",
        "pm25": 20.0, "pm10": 38.0, "no2": None,
        "dominant_pollutant": "pm25",
        "language": "hi", "hour_utc": 14,  # 7:30 PM IST
    },

    # --- SATISFACTORY ---
    {
        "id": "SAT-01",
        "neighborhood": "Dwarka",
        "station_name": "Dwarka CPCB",
        "aqi": 72,
        "category": "Satisfactory",
        "pm25": 40.0, "pm10": 75.0, "no2": 30.0,
        "dominant_pollutant": "pm10",
        "language": "en", "hour_utc": 7,  # 12:30 PM IST
    },
    {
        "id": "SAT-02",
        "neighborhood": "मयूर विहार",
        "station_name": "Mayur Vihar CPCB",
        "aqi": 85,
        "category": "Satisfactory",
        "pm25": 50.0, "pm10": 90.0, "no2": 45.0,
        "dominant_pollutant": "pm25",
        "language": "hi", "hour_utc": 2,  # 7:30 AM IST
    },

    # --- MODERATE ---
    {
        "id": "MOD-01",
        "neighborhood": "Rohini",
        "station_name": "Rohini CPCB",
        "aqi": 145,
        "category": "Moderate",
        "pm25": 78.0, "pm10": 140.0, "no2": 60.0,
        "dominant_pollutant": "pm25",
        "language": "en", "hour_utc": 1,  # 6:30 AM IST (morning commute)
    },
    {
        "id": "MOD-02",
        "neighborhood": "पंजाबी बाग",
        "station_name": "Punjabi Bagh CPCB",
        "aqi": 165,
        "category": "Moderate",
        "pm25": 88.0, "pm10": 155.0, "no2": 75.0,
        "dominant_pollutant": "pm25",
        "language": "hi", "hour_utc": 12,  # 5:30 PM IST (evening)
    },
    {
        "id": "MOD-03",
        "neighborhood": "Connaught Place",
        "station_name": "Mandir Marg CPCB",
        "aqi": 130,
        "category": "Moderate",
        "pm25": 68.0, "pm10": None, "no2": 95.0,
        "dominant_pollutant": "no2",  # vehicular dominant
        "language": "en", "hour_utc": 9,  # 2:30 PM IST
    },

    # --- POOR ---
    {
        "id": "POOR-01",
        "neighborhood": "Anand Vihar",
        "station_name": "Anand Vihar CPCB",
        "aqi": 255,
        "category": "Poor",
        "pm25": 140.0, "pm10": 245.0, "no2": 85.0,
        "dominant_pollutant": "pm25",
        "language": "en", "hour_utc": 0,  # 5:30 AM IST
    },
    {
        "id": "POOR-02",
        "neighborhood": "वज़ीरपुर",
        "station_name": "Wazirpur CPCB",
        "aqi": 285,
        "category": "Poor",
        "pm25": 160.0, "pm10": 280.0, "no2": 90.0,
        "dominant_pollutant": "pm10",
        "language": "hi", "hour_utc": 5,  # 10:30 AM IST
    },
    {
        "id": "POOR-03",
        "neighborhood": "ITO",
        "station_name": "ITO CPCB",
        "aqi": 220,
        "category": "Poor",
        "pm25": 120.0, "pm10": 210.0, "no2": 110.0,
        "dominant_pollutant": "no2",
        "language": "en", "hour_utc": 15,  # 8:30 PM IST
    },

    # --- VERY POOR ---
    {
        "id": "VPOOR-01",
        "neighborhood": "Jahangirpuri",
        "station_name": "Jahangirpuri CPCB",
        "aqi": 340,
        "category": "Very Poor",
        "pm25": 200.0, "pm10": 350.0, "no2": 95.0,
        "dominant_pollutant": "pm25",
        "language": "en", "hour_utc": 2,  # 7:30 AM IST
    },
    {
        "id": "VPOOR-02",
        "neighborhood": "आनंद विहार",
        "station_name": "Anand Vihar CPCB",
        "aqi": 375,
        "category": "Very Poor",
        "pm25": 225.0, "pm10": 380.0, "no2": 100.0,
        "dominant_pollutant": "pm25",
        "language": "hi", "hour_utc": 4,  # 9:30 AM IST
    },
    {
        "id": "VPOOR-03",
        "neighborhood": "Shadipur",
        "station_name": "Shadipur CPCB",
        "aqi": 320,
        "category": "Very Poor",
        "pm25": 185.0, "pm10": None, "no2": 88.0,
        "dominant_pollutant": "pm25",
        "language": "en", "hour_utc": 18,  # 11:30 PM IST
    },

    # --- SEVERE ---
    {
        "id": "SEV-01",
        "neighborhood": "Anand Vihar",
        "station_name": "Anand Vihar CPCB",
        "aqi": 450,
        "category": "Severe",
        "pm25": 290.0, "pm10": 480.0, "no2": 110.0,
        "dominant_pollutant": "pm25",
        "language": "en", "hour_utc": 1,  # 6:30 AM IST
    },
    {
        "id": "SEV-02",
        "neighborhood": "जहांगीरपुरी",
        "station_name": "Jahangirpuri CPCB",
        "aqi": 490,
        "category": "Severe",
        "pm25": 320.0, "pm10": 510.0, "no2": 115.0,
        "dominant_pollutant": "pm25",
        "language": "hi", "hour_utc": 3,  # 8:30 AM IST
    },
    {
        "id": "SEV-03",
        "neighborhood": "Chandni Chowk",
        "station_name": "Chandni Chowk CPCB",
        "aqi": 420,
        "category": "Severe",
        "pm25": 265.0, "pm10": 430.0, "no2": 130.0,
        "dominant_pollutant": "pm25",
        "language": "en", "hour_utc": 7,  # 12:30 PM IST
    },

    # --- EDGE CASES ---
    {
        "id": "EDGE-01-no-no2",
        "neighborhood": "NSIT Dwarka",
        "station_name": "NSIT Dwarka CPCB",
        "aqi": 178,
        "category": "Moderate",
        "pm25": 95.0, "pm10": 170.0, "no2": None,  # No NO2 data
        "dominant_pollutant": "pm10",
        "language": "en", "hour_utc": 6,
    },
    {
        "id": "EDGE-02-high-no2",
        "neighborhood": "ITO",
        "station_name": "ITO CPCB",
        "aqi": 195,
        "category": "Moderate",
        "pm25": 60.0, "pm10": 100.0, "no2": 175.0,  # NO2 is dominant
        "dominant_pollutant": "no2",
        "language": "en", "hour_utc": 8,
    },
    {
        "id": "EDGE-03-hindi-severe",
        "neighborhood": "रोहिणी",
        "station_name": "Rohini CPCB",
        "aqi": 435,
        "category": "Severe",
        "pm25": 270.0, "pm10": 445.0, "no2": None,
        "dominant_pollutant": "pm25",
        "language": "hi", "hour_utc": 0,
    },
]

HALLUCINATION_CHECKS = [
    # (thing_that_must_not_appear, reason)
    ("AQI", "Should not say 'AQI' — use plain language"),
    ("µg", "Should not mention pollutant concentrations"),
    ("WHO", "Should not reference WHO by name"),
    ("CPCB", "Should not reference CPCB by name"),
    ("μg/m", "Should not mention pollutant units"),
]


def run_tests(language_filter: str = None, check_hallucinations: bool = False):
    samples = SAMPLES
    if language_filter:
        samples = [s for s in SAMPLES if s["language"] == language_filter]

    results = []
    passed = 0
    failed = 0

    for s in samples:
        print(f"\n{'='*60}")
        print(f"[{s['id']}] {s['neighborhood']} | AQI {s['aqi']} ({s['category']}) | {s['language'].upper()}")
        print(f"Pollutants: PM2.5={s['pm25']}, PM10={s['pm10']}, NO2={s['no2']}")
        print(f"{'─'*60}")

        advisory = generate_advisory(
            neighborhood=s["neighborhood"],
            station_name=s["station_name"],
            aqi=s["aqi"],
            category=s["category"],
            pm25=s["pm25"],
            pm10=s["pm10"],
            no2=s["no2"],
            dominant_pollutant=s["dominant_pollutant"],
            language=s["language"],
            hour_utc=s["hour_utc"],
        )

        print(f"ADVISORY: {advisory}")
        print(f"Word count: {len(advisory.split())}")

        issues = []
        if len(advisory.split()) > 75:
            issues.append(f"TOO LONG: {len(advisory.split())} words (max 70)")
        if advisory.strip().startswith("I ") or advisory.strip().startswith("VayuVani"):
            issues.append("STARTS WITH FORBIDDEN WORD")

        if check_hallucinations:
            for token, reason in HALLUCINATION_CHECKS:
                if token in advisory:
                    issues.append(f"HALLUCINATION: '{token}' found — {reason}")

        if issues:
            print(f"ISSUES: {'; '.join(issues)}")
            failed += 1
        else:
            print("PASS")
            passed += 1

        results.append({
            "id": s["id"],
            "input": s,
            "advisory": advisory,
            "issues": issues,
        })

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{len(samples)} passed, {failed} failed")

    # Save results to vault
    output_path = "advisory/test_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Full results saved to {output_path}")

    return passed, failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=["en", "hi"], help="Filter by language")
    parser.add_argument("--check-hallucinations", action="store_true")
    args = parser.parse_args()
    run_tests(language_filter=args.language, check_hallucinations=args.check_hallucinations)
