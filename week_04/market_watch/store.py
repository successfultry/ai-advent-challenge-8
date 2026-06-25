from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import aiosqlite


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Snapshot:
    id: int | None
    market_id: str
    question: str
    outcome: str
    price: float
    volume: float | None
    captured_at: str


@dataclass(frozen=True)
class Summary:
    id: int | None
    window: str
    created_at: str
    text: str
    payload: str


@dataclass(frozen=True)
class Run:
    id: int | None
    kind: Literal["collect", "summary"]
    ok: bool
    detail: str
    ran_at: str


class MarketStore:
    def __init__(self, db_path: str = "week_04/market_watch.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        path = Path(self.db_path)
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                question TEXT NOT NULL,
                outcome TEXT NOT NULL,
                price REAL NOT NULL,
                volume REAL,
                captured_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_market_captured
                ON snapshots(market_id, captured_at);

            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                window TEXT NOT NULL,
                created_at TEXT NOT NULL,
                text TEXT NOT NULL,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK (kind IN ('collect', 'summary')),
                ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
                detail TEXT NOT NULL,
                ran_at TEXT NOT NULL
            );
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is None:
            return
        await self._db.close()
        self._db = None

    async def save_snapshots(self, rows: list[Snapshot]) -> int:
        if not rows:
            return 0
        db = self._require_db()
        await db.executemany(
            """
            INSERT INTO snapshots (market_id, question, outcome, price, volume, captured_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.market_id,
                    row.question,
                    row.outcome,
                    row.price,
                    row.volume,
                    row.captured_at,
                )
                for row in rows
            ],
        )
        await db.commit()
        return len(rows)

    async def latest_per_market(self) -> list[Snapshot]:
        db = self._require_db()
        async with db.execute(
            """
            SELECT id, market_id, question, outcome, price, volume, captured_at
            FROM (
                SELECT
                    id,
                    market_id,
                    question,
                    outcome,
                    price,
                    volume,
                    captured_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY market_id, outcome
                        ORDER BY captured_at DESC, id DESC
                    ) AS rn
                FROM snapshots
            )
            WHERE rn = 1
            ORDER BY market_id
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    async def snapshots_since(self, market_id: str, since_iso: str) -> list[Snapshot]:
        db = self._require_db()
        async with db.execute(
            """
            SELECT id, market_id, question, outcome, price, volume, captured_at
            FROM snapshots
            WHERE market_id = ? AND captured_at >= ?
            ORDER BY captured_at ASC, id ASC
            """,
            (market_id, since_iso),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    async def save_summary(self, s: Summary) -> int:
        db = self._require_db()
        cursor = await db.execute(
            """
            INSERT INTO summaries (window, created_at, text, payload)
            VALUES (?, ?, ?, ?)
            """,
            (s.window, s.created_at, s.text, s.payload),
        )
        await db.commit()
        return int(cursor.lastrowid)

    async def latest_summary(self) -> Summary | None:
        db = self._require_db()
        async with db.execute(
            """
            SELECT id, window, created_at, text, payload
            FROM summaries
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else self._summary_from_row(row)

    async def log_run(self, r: Run) -> None:
        db = self._require_db()
        await db.execute(
            """
            INSERT INTO runs (kind, ok, detail, ran_at)
            VALUES (?, ?, ?, ?)
            """,
            (r.kind, int(r.ok), r.detail, r.ran_at),
        )
        await db.commit()

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("MarketStore.init() must be called before use")
        return self._db

    @staticmethod
    def _snapshot_from_row(row: aiosqlite.Row) -> Snapshot:
        return Snapshot(
            id=row["id"],
            market_id=row["market_id"],
            question=row["question"],
            outcome=row["outcome"],
            price=row["price"],
            volume=row["volume"],
            captured_at=row["captured_at"],
        )

    @staticmethod
    def _summary_from_row(row: aiosqlite.Row) -> Summary:
        return Summary(
            id=row["id"],
            window=row["window"],
            created_at=row["created_at"],
            text=row["text"],
            payload=row["payload"],
        )

