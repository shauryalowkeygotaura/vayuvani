"""
One HTTP helper for every external call in Kaun.

Rules it enforces (CLAUDE.md, "validate every external response"):
- HTTP status is always checked. 401/403 and 429/451 raise distinct errors so
  the runner can checkpoint and stop instead of hammering a dead key.
- JSON parsing is wrapped; a non-JSON body raises BadResponse with a snippet.
- 5xx and network errors retry with backoff; everything else fails fast.
"""

import json
import logging
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class ExternalError(Exception):
    """Base class for upstream failures."""


class AuthError(ExternalError):
    """401/403: key missing, revoked, or lacking scope. Do not retry."""


class RateLimited(ExternalError):
    """429 or 451: stop this run, resume from checkpoint next hour."""


class BadResponse(ExternalError):
    """Unexpected status, empty body, or unparseable payload."""


def _snippet(text: str, n: int = 200) -> str:
    return (text or "")[:n].replace("\n", " ")


def get(
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 20.0,
    retries: int = 3,
    session: Optional[requests.Session] = None,
) -> requests.Response:
    s = session or requests
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = s.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            logger.warning(f"GET {url} network error (attempt {attempt + 1}): {e}")
            time.sleep(2 ** attempt)
            continue

        code = resp.status_code
        if code in (401, 403):
            raise AuthError(f"{code} from {url}: {_snippet(resp.text)}")
        if code in (429, 451):
            raise RateLimited(f"{code} from {url}: {_snippet(resp.text)}")
        if 500 <= code < 600:
            last_exc = BadResponse(f"{code} from {url}")
            logger.warning(f"GET {url} -> {code} (attempt {attempt + 1})")
            time.sleep(2 ** attempt)
            continue
        if code != 200:
            raise BadResponse(f"{code} from {url}: {_snippet(resp.text)}")
        return resp
    raise BadResponse(f"GET {url} failed after {retries} attempts: {last_exc}")


def get_json(url: str, **kwargs) -> Any:
    resp = get(url, **kwargs)
    if not resp.text.strip():
        raise BadResponse(f"empty body from {url}")
    try:
        return resp.json()
    except (ValueError, json.JSONDecodeError) as e:
        raise BadResponse(f"non-JSON from {url}: {_snippet(resp.text)}") from e


def get_text(url: str, **kwargs) -> str:
    return get(url, **kwargs).text
