"""Local rate-limit tracking backed by SQLite (WAL mode).

The tracker is *advisory*: it pre-skips providers whose limits we know are
breached, saving doomed HTTP calls. It is never the source of truth — a live
429 from the server always wins and is recorded here as a cooldown.

Concurrency notes: WAL mode lets the CLI `status` command read while a gateway
process writes. The check-then-call race between two processes is tolerated by
design — the loser receives a 429, which becomes a cooldown.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ProviderConfig
from .models import ProviderStatus

_PACIFIC = ZoneInfo("America/Los_Angeles")
_DAY_S = 86400.0
_PRUNE_AFTER_S = 48 * 3600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    ts REAL NOT NULL,
    total_tokens INTEGER
);
CREATE INDEX IF NOT EXISTS idx_requests_provider_ts ON requests(provider, ts);
CREATE TABLE IF NOT EXISTS cooldowns (
    provider TEXT PRIMARY KEY,
    until REAL NOT NULL,
    reason TEXT NOT NULL
);
"""


def _next_midnight_pacific(now_ts: float) -> float:
    """Epoch seconds of the next midnight in America/Los_Angeles (DST-correct)."""
    now_pt = datetime.fromtimestamp(now_ts, tz=_PACIFIC)
    next_day = (now_pt + timedelta(days=1)).date()
    boundary = datetime(next_day.year, next_day.month, next_day.day, tzinfo=_PACIFIC)
    return boundary.timestamp()


def _last_midnight_pacific(now_ts: float) -> float:
    """Epoch seconds of the most recent midnight in America/Los_Angeles."""
    now_pt = datetime.fromtimestamp(now_ts, tz=_PACIFIC)
    boundary = datetime(now_pt.year, now_pt.month, now_pt.day, tzinfo=_PACIFIC)
    return boundary.timestamp()


def _to_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)


class RateLimitTracker:
    """Sliding-window request/token counters plus server-imposed cooldowns."""

    def __init__(self, db_path: Path, clock: Callable[[], float] = time.time):
        self._db_path = db_path
        self._clock = clock
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------------ writes

    def record_success(self, provider: str, model: str, total_tokens: int | None) -> None:
        now = self._clock()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO requests (provider, model, ts, total_tokens) VALUES (?, ?, ?, ?)",
                (provider, model, now, total_tokens),
            )

    def set_cooldown(self, provider: str, until_ts: float, reason: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cooldowns (provider, until, reason) VALUES (?, ?, ?) "
                "ON CONFLICT(provider) DO UPDATE SET until=excluded.until, reason=excluded.reason",
                (provider, until_ts, reason),
            )

    def clear(self, provider: str | None = None) -> None:
        """Wipe counters/cooldowns (all providers or one); also prunes old rows."""
        cutoff = self._clock() - _PRUNE_AFTER_S
        with self._connect() as conn:
            if provider is None:
                conn.execute("DELETE FROM requests")
                conn.execute("DELETE FROM cooldowns")
            else:
                conn.execute("DELETE FROM requests WHERE provider=?", (provider,))
                conn.execute("DELETE FROM cooldowns WHERE provider=?", (provider,))
            conn.execute("DELETE FROM requests WHERE ts < ?", (cutoff,))

    # ------------------------------------------------------------------- reads

    def _window_stats(self, conn: sqlite3.Connection, provider: str, since: float):
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_tokens), 0), MIN(ts) "
            "FROM requests WHERE provider=? AND ts >= ?",
            (provider, since),
        ).fetchone()
        return int(row[0]), int(row[1]), row[2]  # count, tokens, oldest_ts|None

    def _day_window_start(self, p: ProviderConfig, now: float) -> float:
        if p.daily_reset == "midnight_pt":
            return _last_midnight_pacific(now)
        return now - _DAY_S

    def _day_reset_ts(self, p: ProviderConfig, now: float, oldest_ts: float | None) -> float:
        if p.daily_reset == "midnight_pt":
            return _next_midnight_pacific(now)
        # Rolling window: frees up when the oldest request ages out.
        return (oldest_ts if oldest_ts is not None else now) + _DAY_S

    def availability(self, p: ProviderConfig) -> datetime | None:
        """None if the provider is callable now, else when it next becomes available."""
        now = self._clock()
        candidates: list[float] = []
        with self._connect() as conn:
            row = conn.execute(
                "SELECT until FROM cooldowns WHERE provider=? AND until > ?", (p.name, now)
            ).fetchone()
            if row:
                candidates.append(row[0])

            lim = p.limits
            if lim.rpm is not None or lim.tpm is not None:
                count, tokens, oldest = self._window_stats(conn, p.name, now - 60.0)
                if oldest is not None:
                    if lim.rpm is not None and count >= lim.rpm:
                        candidates.append(oldest + 60.0)
                    if lim.tpm is not None and tokens >= lim.tpm:
                        candidates.append(oldest + 60.0)

            if lim.rpd is not None or lim.tpd is not None:
                day_start = self._day_window_start(p, now)
                count, tokens, oldest = self._window_stats(conn, p.name, day_start)
                breached = (lim.rpd is not None and count >= lim.rpd) or (
                    lim.tpd is not None and tokens >= lim.tpd
                )
                if breached:
                    candidates.append(self._day_reset_ts(p, now, oldest))

        if not candidates:
            return None
        return _to_dt(max(candidates))

    def snapshot(self, providers: list[ProviderConfig]) -> list[ProviderStatus]:
        now = self._clock()
        out: list[ProviderStatus] = []
        with self._connect() as conn:
            for p in providers:
                minute_count, minute_tokens, _ = self._window_stats(conn, p.name, now - 60.0)
                day_count, day_tokens, _ = self._window_stats(
                    conn, p.name, self._day_window_start(p, now)
                )
                cd = conn.execute(
                    "SELECT until, reason FROM cooldowns WHERE provider=? AND until > ?",
                    (p.name, now),
                ).fetchone()
                out.append(
                    ProviderStatus(
                        name=p.name,
                        enabled=p.enabled,
                        has_key=p.resolve_api_key() is not None,
                        priority=p.priority,
                        model=p.model,
                        rpm_used=minute_count,
                        rpm_limit=p.limits.rpm,
                        rpd_used=day_count,
                        rpd_limit=p.limits.rpd,
                        tokens_minute_used=minute_tokens,
                        tpm_limit=p.limits.tpm,
                        tokens_day_used=day_tokens,
                        tpd_limit=p.limits.tpd,
                        cooldown_until=_to_dt(cd[0]) if cd else None,
                        cooldown_reason=cd[1] if cd else None,
                        next_available=self.availability(p),
                    )
                )
        return out
