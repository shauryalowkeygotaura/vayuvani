"""
Pre-flight credential gate (CLAUDE.md): before any API-dependent work, check
each key exists AND has the scope the run needs. Fail loudly with the exact fix.

    python -m attribution.preflight          # full check, exits 1 on failure
"""

import logging
import os
import sys

from . import http
from .store import TABLE_KEYS, SupabaseStore

logger = logging.getLogger(__name__)


class PreflightError(SystemExit):
    pass


def _fail(msg: str, fix: str) -> str:
    return f"  FAIL  {msg}\n        fix: {fix}"


def check(require_supabase: bool = True, require_firms: bool = True) -> list[str]:
    problems: list[str] = []

    # FIRMS: key present and accepted by the status endpoint.
    key = os.getenv("FIRMS_MAP_KEY", "").strip()
    if require_firms:
        if not key:
            problems.append(_fail("FIRMS_MAP_KEY not set",
                                  "get a free MAP_KEY at https://firms.modaps.eosdis.nasa.gov/api/map_key/ "
                                  "and add it as the FIRMS_MAP_KEY secret"))
        else:
            try:
                from .ingest.firms import check_key
                st = check_key(key)
                used, limit = st.get("current_transactions"), st.get("transaction_limit")
                logger.info(f"FIRMS key ok: {used}/{limit} transactions in current window")
                if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and used >= limit:
                    problems.append(_fail("FIRMS MAP_KEY transaction limit reached",
                                          "wait for the 10-minute window to reset"))
            except http.ExternalError as e:
                problems.append(_fail(f"FIRMS MAP_KEY check failed: {e}",
                                      "regenerate the key; check the host is reachable"))

    # OpenAQ: key optional but recommended (higher limits). Probe one call.
    try:
        from pipeline.fetcher import OPENAQ_BASE
        hdr = {"X-API-Key": os.environ["OPENAQ_API_KEY"]} if os.getenv("OPENAQ_API_KEY") else {}
        http.get_json(f"{OPENAQ_BASE}/parameters", params={"limit": 1}, headers=hdr, retries=2)
    except http.AuthError as e:
        problems.append(_fail(f"OpenAQ rejected the key: {e}",
                              "OpenAQ v3 requires a key: create one at https://explore.openaq.org/register "
                              "and set OPENAQ_API_KEY"))
    except http.ExternalError as e:
        problems.append(_fail(f"OpenAQ unreachable: {e}", "check network / OpenAQ status"))

    # Supabase: creds present, every Kaun table exists, and the key can write.
    if require_supabase:
        if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")):
            problems.append(_fail("SUPABASE_URL / SUPABASE_KEY not set",
                                  "add both as GitHub Actions secrets (Doppler locally)"))
        else:
            try:
                store = SupabaseStore()
                for t in TABLE_KEYS:
                    store.select(t, limit=1)
                # Write scope: the anon key usually cannot insert under RLS.
                store.upsert("kaun_stations", [{"id": "_preflight", "name": "_preflight",
                                                "latitude": 0.0, "longitude": 0.0, "active": False}])
            except http.AuthError as e:
                problems.append(_fail(f"Supabase key lacks scope: {e}",
                                      "use the service_role key for the cron (SUPABASE_KEY secret), "
                                      "never the anon key"))
            except http.ExternalError as e:
                problems.append(_fail(f"Supabase check failed: {e}",
                                      "run supabase/kaun_schema.sql in the Supabase SQL editor"))

    # CPCB via data.gov.in is optional.
    from .ingest.cpcb import api_key
    if not api_key():
        logger.info("CPCB (data.gov.in) key not set: OpenAQ alone will carry the run")
    return problems


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    problems = check()
    if problems:
        print("Kaun pre-flight FAILED:\n" + "\n".join(problems), file=sys.stderr)
        sys.exit(1)
    print("Kaun pre-flight OK")


if __name__ == "__main__":
    main()
