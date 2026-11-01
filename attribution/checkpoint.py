"""
Run checkpoint for unattended jobs.

A JSON file under STATE_DIR records, per stage, the last hour that completed
successfully. If a run dies (401/429/451, runner killed), the next run starts
from that hour instead of re-fetching or skipping data. In GitHub Actions the
file is carried between runs with actions/cache (see .github/workflows/kaun.yml).

Writes are atomic (temp file + rename) so a kill mid-write cannot corrupt it.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from .config import STATE_DIR


class Checkpoint:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(STATE_DIR, "checkpoint.json")
        self.data: dict = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                # A corrupt checkpoint must not block the run; start fresh.
                self.data = {}

    def get(self, stage: str) -> Optional[datetime]:
        raw = self.data.get(stage)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def set(self, stage: str, when: datetime) -> None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        self.data[stage] = when.isoformat()
        self._save()

    def note(self, key: str, value) -> None:
        self.data.setdefault("notes", {})[key] = value
        self._save()

    def _save(self) -> None:
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".ckpt", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)
