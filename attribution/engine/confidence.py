"""
Confidence grading. Every attribution gets low / medium / high; none ships
without one (CLAUDE.md domain rule).

Points:
    +1   >= 4 of {pm25, pm10, no2, co, so2} present in the window
    +1   top source leads the runner-up by >= 0.20
    +1   NMF factor analysis agrees on the top source
    +0.5 steady, non-calm wind (sector claim is meaningful)
    +0.5 spike lasts >= 2 hours
    -1   baseline is the trailing-24h fallback (too little history)
    -1   boundary layer collapsed (> 50% drop): the spike may be meteorology
Grades: >= 3.5 high, >= 2 medium, else low.
Caps:
    fewer than 3 species  -> low
    single-hour spike     -> at most medium; low if < 30% above baseline
    industry/dust top without its second signal (fingerprints.second_signal)
                          -> at most medium (low if already marginal)
    3+ sources at >= 15%  -> at most medium (3-way separation from station
                             data alone is fuzzy; say so, do not oversell)
"""

from typing import Optional


def grade(*, species_present: int, shares: dict, nmf_top: Optional[str], top: Optional[str],
          wind: dict, n_hours: int, baseline_kind: str, pbl_drop: Optional[float],
          excess_ratio: Optional[float] = None, second_signal: Optional[bool] = None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    pts = 0.0
    if species_present >= 4:
        pts += 1
    else:
        reasons.append(f"only {species_present} pollutant species reported")
    ranked = sorted(shares.values(), reverse=True)
    margin = ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0) if ranked else 0.0
    if margin >= 0.20:
        pts += 1
    else:
        reasons.append("top two sources are close")
    if nmf_top and top and nmf_top == top:
        pts += 1
    elif nmf_top:
        reasons.append(f"factor analysis points to {nmf_top} instead")
    else:
        reasons.append("factor analysis unavailable (short history)")
    if wind.get("sector") and (wind.get("steadiness") or 0) >= 0.6:
        pts += 0.5
    elif wind.get("calm"):
        reasons.append("calm wind: source is nearby but direction unknown")
    if n_hours >= 2:
        pts += 0.5
    if baseline_kind != "same-hour-7d":
        pts -= 1
        reasons.append("baseline from <4 days of history")
    if pbl_drop is not None and pbl_drop > 0.5:
        pts -= 1
        reasons.append(f"boundary layer fell {pbl_drop:.0%}: part of the spike is trapped air, not new emissions")

    level = "high" if pts >= 3.5 else "medium" if pts >= 2 else "low"
    if species_present < 3:
        level = "low"
    if sum(1 for v in shares.values() if v >= 0.15) >= 3 and level == "high":
        level = "medium"
        reasons.append("3+ sources mixed: station data cannot separate them cleanly")
    if n_hours < 2 and level == "high":
        level = "medium"
        reasons.append("single-hour spike")
    if n_hours < 2 and excess_ratio is not None and excess_ratio < 0.3:
        level = "low"
        reasons.append(f"weak transient: one hour, only {excess_ratio:.0%} above baseline")
    if second_signal is False and level != "low":
        level = "low" if level == "medium" and pts < 3 else "medium"
        reasons.append(f"{top} rests on one signal only; second signal absent")
    if not shares:
        level = "low"
    return level, reasons
