"""
Traffic proxy: a fixed time-of-day prior for Delhi.

No free hourly congestion feed for Delhi is wired in (TomTom/HERE free tiers
were not evaluated this session; check their caching terms before adding one).
So this is a deterministic prior,
0..1, with morning (8-11 IST) and evening (17-21 IST) peaks and a deep night
trough, plus a small post-midnight shoulder because Delhi restricts heavy
goods vehicle entry to night hours (exact window not verified this session,
so the shoulder is kept deliberately small).

It is a weak prior used only to nudge the traffic score; the NO2/CO
fingerprint dominates. Replace with a real feed if one becomes available.
"""

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# Index = IST hour.
_PROFILE = [
    0.30, 0.30, 0.25, 0.20, 0.20, 0.25, 0.40, 0.60,
    0.85, 1.00, 0.90, 0.75, 0.65, 0.65, 0.65, 0.70,
    0.80, 0.95, 1.00, 1.00, 0.90, 0.70, 0.50, 0.40,
]


def prior(hour_utc: datetime) -> float:
    if hour_utc.tzinfo is None:
        hour_utc = hour_utc.replace(tzinfo=timezone.utc)
    return _PROFILE[hour_utc.astimezone(IST).hour]
