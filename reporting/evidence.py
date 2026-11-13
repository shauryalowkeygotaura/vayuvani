"""
Evidence pack for one high-confidence local spike: chart + numbers + wind
sector + timestamps. Pure-Python SVG (no matplotlib) so the cron image stays
small. Written to public/evidence/<id>/ so the approval reviewer can open it.
"""

import html
import json
import os
from datetime import timedelta, timezone
from typing import Optional

from attribution.config import STATE_DIR
from attribution.labels import LABELS_EN
from .agencies import agencies_for, routing_source

IST = timezone(timedelta(hours=5, minutes=30))


def _ev(rec: dict) -> dict:
    ev = rec.get("evidence") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except ValueError:
            ev = {}
    return ev


def chart_svg(hourly: list[dict], width: int = 640, height: int = 260) -> str:
    """PM2.5 vs baseline across the spike window."""
    pts = [(h["hour"], h.get("pm25"), h.get("base_pm25")) for h in hourly if h.get("pm25") is not None]
    if not pts:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
    pad = 40
    ymax = max(max(p[1] for p in pts), max((p[2] or 0) for p in pts)) * 1.15 or 1
    n = len(pts)

    def xy(i, v):
        x = pad + (width - 2 * pad) * (i / max(n - 1, 1))
        y = height - pad - (height - 2 * pad) * (v / ymax)
        return f"{x:.1f},{y:.1f}"

    obs_line = " ".join(xy(i, p[1]) for i, p in enumerate(pts))
    base_line = " ".join(xy(i, p[2]) for i, p in enumerate(pts) if p[2] is not None)
    labels = "".join(
        f'<text x="{xy(i, 0).split(",")[0]}" y="{height - 12}" font-size="10" text-anchor="middle">'
        f'{html.escape(str(p[0])[11:16])}Z</text>' for i, p in enumerate(pts))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif">'
        f'<rect width="100%" height="100%" fill="#fff"/>'
        f'<text x="{pad}" y="20" font-size="13">PM2.5 (ug/m3): observed vs 7-day same-hour baseline</text>'
        f'<polyline fill="none" stroke="#999" stroke-dasharray="4 3" stroke-width="2" points="{base_line}"/>'
        f'<polyline fill="none" stroke="#c0392b" stroke-width="2.5" points="{obs_line}"/>'
        f'<text x="{width - pad}" y="{pad}" font-size="11" text-anchor="end">max {ymax / 1.15:.0f}</text>'
        f'{labels}</svg>'
    )


def build(rec: dict, root: Optional[str] = None) -> dict:
    ev = _ev(rec)
    shares = rec.get("shares") or {}
    if isinstance(shares, str):
        shares = json.loads(shares)
    cause = rec.get("cause") or {}
    if isinstance(cause, str):
        try:
            cause = json.loads(cause)
        except ValueError:
            cause = {}
    top = routing_source(rec)
    cands = ((cause.get("local") or {}).get("candidates") or []) if isinstance(cause, dict) else []
    d = os.path.join(root or STATE_DIR, "evidence", rec["id"])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "chart.svg"), "w", encoding="utf-8") as f:
        f.write(chart_svg(ev.get("hourly") or []))

    start = rec["window_start"]
    lines = [
        f"# Evidence pack: {rec['station_name']}",
        "",
        f"- Window (UTC): {start} to {rec['window_end']}",
        f"- Peak PM2.5: {rec.get('peak_pm25')} ug/m3; baseline {rec.get('baseline_pm25')}; "
        f"excess {rec.get('excess_pm25')}",
        f"- Estimated sources: " + ", ".join(f"{LABELS_EN.get(k, k)} {v:.0%}" for k, v in shares.items()),
        f"- Confidence: **{rec['confidence']}**",
        f"- Cause: {cause.get('text_en') or 'n/a'}" if isinstance(cause, dict) else "- Cause: n/a",
        ("- Possible sites (OpenStreetMap, in the wind sector): " +
         "; ".join(f"{c['name']} ({c['type']}, {c['km']} km {c['sector']}, "
                   f"https://maps.google.com/?q={c.get('lat')},{c.get('lon')})" for c in cands)) if cands else
        "- Possible sites: none named in OpenStreetMap for this sector",
        f"- Wind: {json.dumps(ev.get('wind'))}",
        f"- Ratios: {json.dumps(ev.get('ratios'))}",
        f"- Factor analysis (PM2.5 shares): {json.dumps(ev.get('nmf_pm25_shares'))}",
        f"- Upwind fires: {json.dumps(ev.get('upwind_fires'))}",
        f"- Suggested agency: {', '.join(agencies_for(top)) or 'none'}",
        "",
        "![chart](chart.svg)",
        "",
        "Method: observation-driven ratio fingerprints, wind sector and NMF factor analysis on public "
        "CPCB/DPCC station data (via OpenAQ), Open-Meteo wind, NASA FIRMS fires. Estimates, not "
        "measurements of individual emitters. Station data cannot identify a specific site; the "
        "request is for inspection of the indicated sector.",
    ]
    with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return {"dir": d, "markdown": "\n".join(lines)}
