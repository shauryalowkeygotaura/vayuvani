"""
Storage layer for Kaun.

Two backends with the same interface:
- SupabaseStore: PostgREST over plain requests (status checked, JSON validated,
  idempotent upserts keyed on the table's natural key).
- LocalStore: CSV files under STATE_DIR. Used for development, tests, and as a
  dry-run backend when Supabase is not configured.

Tables (see supabase/migrations/002_kaun.sql):
    hourly_obs       (station_id, hour)            pollutants per station-hour
    wind_obs         (station_id, hour)            wind speed/direction
    fire_points      (source, latitude, longitude, acq_time)
    kaun_stations    (id)                          station metadata
    attributions     (station_id, window_start)
    complaint_queue  (attribution_id)
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Iterable, Optional

import pandas as pd
import requests

from .config import STATE_DIR
from .http import AuthError, BadResponse, RateLimited

logger = logging.getLogger(__name__)

# Natural keys used for idempotent upserts. Also the whitelist of tables this
# module may touch: anything else is rejected before a URL is built.
TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "kaun_stations": ("id",),
    "hourly_obs": ("station_id", "hour"),
    "wind_obs": ("station_id", "hour"),
    "fire_points": ("source", "latitude", "longitude", "acq_time"),
    "attributions": ("station_id", "window_start"),
    "complaint_queue": ("attribution_id",),
    "citizen_reports": ("id",),
    "report_digests": ("agency", "day"),
    "station_landuse": ("station_id",),
}

PAGE = 1000


def _check_table(table: str) -> None:
    if table not in TABLE_KEYS:
        raise ValueError(f"table {table!r} not in whitelist {sorted(TABLE_KEYS)}")


def _clean(v):
    """JSON-safe value: NaN/NaT -> None, numpy scalars -> python, timestamps -> ISO."""
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.isoformat()
    if isinstance(v, datetime):
        return v.isoformat()
    if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
        if isinstance(v, float) and v != v:
            return None
    return v


def _deep(v):
    if isinstance(v, dict):
        return {str(k): _deep(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_deep(x) for x in v]
    return _clean(v)


def clean_rows(rows: Iterable[dict]) -> list[dict]:
    """JSON-safe rows, recursing into nested evidence so NaN never reaches Postgres."""
    return [{k: _deep(v) for k, v in r.items()} for r in rows]


class SupabaseStore:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        key = key or os.environ["SUPABASE_KEY"]
        self.session = requests.Session()
        self.session.headers.update({
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })

    def _send(self, method: str, what: str, **kwargs) -> requests.Response:
        """One request with a short retry on dropped connections (seen as WinError 10054 mid-batch)."""
        last: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = self.session.request(method, timeout=30, **kwargs)
            except requests.RequestException as e:
                last = e
                logger.warning(f"Supabase {what}: network error (attempt {attempt + 1}): {e}")
                time.sleep(2 ** attempt)
                continue
            if 500 <= resp.status_code < 600 and attempt < 2:
                logger.warning(f"Supabase {what}: {resp.status_code} (attempt {attempt + 1})")
                time.sleep(2 ** attempt)
                continue
            return resp
        raise BadResponse(f"Supabase {what}: unreachable after 3 attempts: {last}")

    def _raise_for(self, resp: requests.Response, what: str) -> None:
        code = resp.status_code
        if code in (401, 403):
            raise AuthError(f"Supabase {what}: {code} {resp.text[:200]}")
        if code in (429, 451):
            raise RateLimited(f"Supabase {what}: {code}")
        if code >= 300:
            raise BadResponse(f"Supabase {what}: {code} {resp.text[:300]}")

    def upsert(self, table: str, rows: list[dict], chunk: int = 500) -> int:
        _check_table(table)
        rows = clean_rows(rows)
        if not rows:
            return 0
        on_conflict = ",".join(TABLE_KEYS[table])
        # PostgREST bulk inserts need one key set per request (PGRST102), and
        # stations report different pollutants. Group by key set rather than
        # padding with nulls, so a missing column still means "leave it alone".
        groups: dict[frozenset, list[dict]] = {}
        for r in rows:
            groups.setdefault(frozenset(r), []).append(r)
        n = 0
        for part in (g[i:i + chunk] for g in groups.values() for i in range(0, len(g), chunk)):
            resp = self._send(
                "POST", f"upsert {table}",
                url=f"{self.url}/rest/v1/{table}",
                params={"on_conflict": on_conflict},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                data=json.dumps(part, allow_nan=False, default=str),
            )
            self._raise_for(resp, f"upsert {table}")
            n += len(part)
        return n

    def select(self, table: str, filters: Optional[dict] = None,
               order: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
        """filters: PostgREST operators, e.g. {"hour": "gte.2026-10-01T00:00:00+00:00"}."""
        _check_table(table)
        out: list[dict] = []
        offset = 0
        # Offset pagination is only stable under a total order. Without one,
        # Postgres hands back pages in heap order and rows drift between pages:
        # on the live project that silently dropped ~15% of wind_obs rows, so a
        # third of spike windows lost their wind (and every map/wind term).
        order = order or ",".join(TABLE_KEYS[table])
        while True:
            params = dict(filters or {})
            params["select"] = "*"
            params["order"] = order
            page = PAGE if limit is None else min(PAGE, limit - len(out))
            params["limit"] = page
            params["offset"] = offset
            resp = self._send("GET", f"select {table}", url=f"{self.url}/rest/v1/{table}", params=params)
            self._raise_for(resp, f"select {table}")
            try:
                batch = resp.json()
            except ValueError as e:
                raise BadResponse(f"Supabase select {table}: non-JSON body") from e
            if not isinstance(batch, list):
                raise BadResponse(f"Supabase select {table}: expected list, got {type(batch).__name__}")
            out.extend(batch)
            if len(batch) < page or (limit is not None and len(out) >= limit):
                return out
            offset += page

    def update(self, table: str, match: dict, values: dict) -> None:
        _check_table(table)
        params = {k: f"eq.{v}" for k, v in match.items()}
        resp = self._send(
            "PATCH", f"update {table}",
            url=f"{self.url}/rest/v1/{table}", params=params,
            headers={"Prefer": "return=minimal"},
            data=json.dumps(clean_rows([values])[0]),
        )
        self._raise_for(resp, f"update {table}")


class LocalStore:
    """CSV-backed store with the same upsert/select semantics (dev + tests)."""

    def __init__(self, root: Optional[str] = None):
        self.root = root or os.path.join(STATE_DIR, "db")
        os.makedirs(self.root, exist_ok=True)

    def _path(self, table: str) -> str:
        _check_table(table)
        return os.path.join(self.root, f"{table}.csv")

    def _load(self, table: str) -> pd.DataFrame:
        p = self._path(table)
        if not os.path.exists(p):
            return pd.DataFrame()
        return pd.read_csv(p)

    def upsert(self, table: str, rows: list[dict], chunk: int = 0) -> int:
        _check_table(table)
        rows = clean_rows(rows)
        if not rows:
            return 0
        keys = list(TABLE_KEYS[table])
        new = pd.DataFrame(rows)
        for c in new.columns:
            if new[c].map(lambda x: isinstance(x, (dict, list))).any():
                new[c] = new[c].map(lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x)
        old = self._load(table)
        both = pd.concat([old, new], ignore_index=True) if not old.empty else new
        key_str = both[keys].astype(str).agg("|".join, axis=1)
        both = both.loc[~key_str.duplicated(keep="last")]
        both.to_csv(self._path(table), index=False)
        return len(rows)

    def select(self, table: str, filters: Optional[dict] = None,
               order: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
        df = self._load(table)
        if df.empty:
            return []
        for col, expr in (filters or {}).items():
            op, _, val = expr.partition(".")
            if col not in df.columns:
                return []
            series = df[col]
            if op in ("gte", "lte", "gt", "lt") and col in ("hour", "window_start", "window_end", "acq_time", "created_at", "timestamp"):
                series = pd.to_datetime(series, utc=True, format="ISO8601")
                val = pd.Timestamp(val)
                val = val.tz_localize("UTC") if val.tzinfo is None else val
            elif op in ("gte", "lte", "gt", "lt"):
                val = float(val)
            else:
                series = series.astype(str)
            mask = {
                "eq": series == val, "gte": series >= val, "lte": series <= val,
                "gt": series > val, "lt": series < val,
            }.get(op)
            if mask is None:
                raise ValueError(f"unsupported filter op {op}")
            df = df.loc[mask]
        if order:
            col, _, direction = order.partition(".")
            df = df.sort_values(col, ascending=direction != "desc")
        if limit is not None:
            df = df.head(limit)
        df = df.astype(object).where(pd.notna(df), None)
        return df.to_dict("records")

    def update(self, table: str, match: dict, values: dict) -> None:
        df = self._load(table)
        if df.empty:
            return
        mask = pd.Series(True, index=df.index)
        for k, v in match.items():
            mask &= df[k].astype(str) == str(v)
        for k, v in clean_rows([values])[0].items():
            if k not in df.columns:
                df[k] = None
            df[k] = df[k].astype(object)
            df.loc[mask, k] = json.dumps(v) if isinstance(v, (dict, list)) else v
        df.to_csv(self._path(table), index=False)


def get_store():
    """Supabase when configured, else LocalStore (logged loudly)."""
    if os.getenv("KAUN_STORE", "").lower() == "local":
        return LocalStore()
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"):
        return SupabaseStore()
    logger.warning("SUPABASE_URL/SUPABASE_KEY not set: using LocalStore under %s", STATE_DIR)
    return LocalStore()
