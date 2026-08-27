"""SQLite cache for gateway responses (M3).

Free-tier quota is the project's budget; the cache makes every repeated
evaluation run cost zero of it. Keys are a SHA-256 over the full request
(task tag, system prompt, user prompt, sampling params) — so changing a prompt
naturally invalidates only the calls it affects, and identical requests are
answered from disk forever.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    text TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    total_tokens INTEGER,
    created_at TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class CachedResponse:
    text: str
    provider: str
    model: str
    total_tokens: int | None


class ResponseCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    @staticmethod
    def make_key(task: str, system: str, prompt: str, params: dict[str, Any]) -> str:
        payload = json.dumps(
            {"task": task, "system": system, "prompt": prompt, "params": params},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> CachedResponse | None:
        row = self._conn.execute(
            "SELECT text, provider, model, total_tokens FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return CachedResponse(text=row[0], provider=row[1], model=row[2], total_tokens=row[3])

    def put(self, key: str, task: str, response: CachedResponse) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                task,
                response.text,
                response.provider,
                response.model,
                response.total_tokens,
                dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ResponseCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
