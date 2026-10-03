"""
Week 11 — A/B test analysis for IRIS research paper.

Research question:
  Does a voice-first AI advisory system (VayuVani, Group B) improve
  behavioral response rate compared to standard AQI app notifications (Group A)?

Primary outcome: changed_plans (boolean) from advisory_logs + manual survey
Secondary outcome: advisory comprehension score (separate survey form)

Statistical test: Chi-squared test on changed_plans proportions.
Target: p < 0.05 to claim statistically significant improvement.

Usage:
    python -m research.ab_analysis
    python -m research.ab_analysis --min-n 50
"""

import argparse
import sys
from dotenv import load_dotenv

load_dotenv()

# pylint: disable=wrong-import-position
from pipeline.db import get_client


def fetch_ab_data() -> tuple[list[dict], list[dict]]:
    """Return (group_a_rows, group_b_rows) from advisory_logs."""
    client = get_client()
    result = (
        client.table("advisory_logs")
        .select("group_label, changed_plans, language, category, neighborhood")
        .not_.is_("changed_plans", "null")  # only rows with survey response
        .execute()
    )
    rows = result.data or []
    group_a = [r for r in rows if r["group_label"] == "A"]
    group_b = [r for r in rows if r["group_label"] == "B"]
    return group_a, group_b


def chi_squared(a_yes: int, a_no: int, b_yes: int, b_no: int) -> tuple[float, float]:
    """
    2×2 chi-squared test.
    Returns (chi2_statistic, p_value).
    Uses Yates correction for small samples.
    """
    import math

    n = a_yes + a_no + b_yes + b_no
    if n == 0:
        return 0.0, 1.0

    # Expected counts
    r1 = a_yes + a_no
    r2 = b_yes + b_no
    c1 = a_yes + b_yes
    c2 = a_no + b_no

    e_a_yes = r1 * c1 / n
    e_a_no = r1 * c2 / n
    e_b_yes = r2 * c1 / n
    e_b_no = r2 * c2 / n

    if any(e < 5 for e in [e_a_yes, e_a_no, e_b_yes, e_b_no]):
        print("WARNING: Expected cell counts < 5. Consider Fisher's exact test.")

    # Yates-corrected chi-squared
    chi2 = (
        (abs(a_yes - e_a_yes) - 0.5) ** 2 / e_a_yes
        + (abs(a_no - e_a_no) - 0.5) ** 2 / e_a_no
        + (abs(b_yes - e_b_yes) - 0.5) ** 2 / e_b_yes
        + (abs(b_no - e_b_no) - 0.5) ** 2 / e_b_no
    )

    # p-value from chi-squared distribution (1 df) — approximation
    # For final paper, use scipy.stats.chi2_contingency for exact p-value
    x = chi2 / 2
    p = math.exp(-x) * (1 + x + x**2 / 2 + x**3 / 6)  # crude upper bound
    p = min(1.0, max(0.0, p))

    return chi2, p


def run_analysis(min_n: int = 50):
    group_a, group_b = fetch_ab_data()

    na = len(group_a)
    nb = len(group_b)

    print(f"\n{'='*55}")
    print(f"VAYUVANI A/B TEST ANALYSIS")
    print(f"{'='*55}")
    print(f"Group A (control — AQI app):  n={na}")
    print(f"Group B (VayuVani calls):      n={nb}")

    if na < min_n or nb < min_n:
        print(f"\nWARNING: Need at least {min_n} per group. Current: A={na}, B={nb}")
        print("Continue recruiting. Come back when n >= 50 per group.")
        return

    a_yes = sum(1 for r in group_a if r["changed_plans"])
    a_no = na - a_yes
    b_yes = sum(1 for r in group_b if r["changed_plans"])
    b_no = nb - b_yes

    a_rate = a_yes / na * 100
    b_rate = b_yes / nb * 100
    lift = b_rate - a_rate

    print(f"\nBehavioral response rate (changed_plans=True):")
    print(f"  Group A: {a_yes}/{na} = {a_rate:.1f}%")
    print(f"  Group B: {b_yes}/{nb} = {b_rate:.1f}%")
    print(f"  Lift:    {lift:+.1f} percentage points")

    chi2, p = chi_squared(a_yes, a_no, b_yes, b_no)
    print(f"\nChi-squared (Yates): {chi2:.3f}")
    print(f"p-value (approx):    {p:.4f}")
    print(f"Significant (p<0.05): {'YES' if p < 0.05 else 'NO'}")

    print(f"\n{'─'*55}")
    print("NOTE: For the IRIS paper, replace the approximation above with:")
    print("  from scipy.stats import chi2_contingency")
    print("  chi2, p, dof, expected = chi2_contingency([[a_yes,a_no],[b_yes,b_no]])")
    print("This gives the exact p-value for the contingency table.")

    # Breakdown by category
    print(f"\nBreakdown by AQI category (Group B — VayuVani):")
    cats = ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
    for cat in cats:
        cat_rows = [r for r in group_b if r["category"] == cat]
        if not cat_rows:
            continue
        cat_yes = sum(1 for r in cat_rows if r["changed_plans"])
        print(f"  {cat:15}: {cat_yes}/{len(cat_rows)} changed plans ({cat_yes/len(cat_rows)*100:.0f}%)")

    print(f"\nBreakdown by language (Group B):")
    for lang in ["en", "hi"]:
        lang_rows = [r for r in group_b if r["language"] == lang]
        if not lang_rows:
            continue
        lang_yes = sum(1 for r in lang_rows if r["changed_plans"])
        print(f"  {lang}: {lang_yes}/{len(lang_rows)} ({lang_yes/len(lang_rows)*100:.0f}%)")

    return {"a_rate": a_rate, "b_rate": b_rate, "lift": lift, "p": p, "significant": p < 0.05}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-n", type=int, default=50)
    args = parser.parse_args()
    result = run_analysis(min_n=args.min_n)
    if result and not result["significant"]:
        sys.exit(1)
