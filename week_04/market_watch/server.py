import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from week_04.market_watch.aggregate import since_for_window, summarize_snapshots
from week_04.market_watch.manifold import ManifoldClient, quotes_to_snapshots
from week_04.market_watch.store import MarketStore, Run, Snapshot, Summary, utc_now


@dataclass(frozen=True)
class Config:
    base_url: str
    interval_s: int
    limit: int
    db_path: str


@dataclass
class State:
    store: MarketStore
    client: ManifoldClient
    collector: asyncio.Task[None]
    config: Config


CONFIG = Config(
    base_url=os.environ.get("MANIFOLD_API_URL", "https://api.manifold.markets"),
    interval_s=max(1, int(os.environ.get("MARKET_WATCH_INTERVAL_S", "10"))),
    limit=max(1, int(os.environ.get("MARKET_WATCH_LIMIT", "10"))),
    db_path=os.environ.get("MARKET_WATCH_DB", "week_04/market_watch.db"),
)


@asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncIterator[State]:
    store = MarketStore(CONFIG.db_path)
    await store.init()
    client = ManifoldClient(CONFIG.base_url)
    collector = asyncio.create_task(_collector_loop(store, client, CONFIG))
    state = State(store=store, client=client, collector=collector, config=CONFIG)
    try:
        yield state
    finally:
        collector.cancel()
        try:
            await collector
        except asyncio.CancelledError:
            pass
        await client.close()
        await store.close()


mcp = FastMCP("market-watch", log_level="ERROR", lifespan=_lifespan)


@mcp.tool(description="Collect Manifold quotes immediately and store them as snapshots.")
async def collect_now(ctx: Context) -> dict:
    state = _state(ctx)
    try:
        saved = await _collect_once(state.store, state.client, state.config.limit)
    except Exception as exc:
        await state.store.log_run(Run(None, "collect", False, str(exc), utc_now()))
        return {"error": str(exc)}
    return {"saved": saved}


@mcp.tool(description="Return the latest stored market snapshots.")
async def latest_markets(ctx: Context) -> list[dict]:
    state = _state(ctx)
    snapshots = await state.store.latest_per_market()
    return [_snapshot_dict(snapshot) for snapshot in snapshots]


@mcp.tool(description="Build and persist a deterministic market summary.")
async def build_summary(ctx: Context, window: str = "all", top_n: int = 10) -> dict:
    state = _state(ctx)
    latest = await state.store.latest_per_market()
    since_iso = since_for_window(window)
    history = await _history_for_latest(state.store, latest, since_iso)
    summary = summarize_snapshots(latest, history=history, window=window, top_n=top_n)
    text = _summary_text(summary)
    summary_id = await state.store.save_summary(
        Summary(
            id=None,
            window=window,
            created_at=summary["generated_at"],
            text=text,
            payload=json.dumps(summary, ensure_ascii=False),
        )
    )
    await state.store.log_run(Run(None, "summary", True, f"saved {summary_id}", utc_now()))
    return {"summary_id": summary_id, "text": text, **summary}


@mcp.tool(description="Return the latest persisted market summary.")
async def latest_summary(ctx: Context) -> dict | None:
    state = _state(ctx)
    summary = await state.store.latest_summary()
    if summary is None:
        return None
    return {
        "id": summary.id,
        "window": summary.window,
        "created_at": summary.created_at,
        "text": summary.text,
        "payload": summary.payload,
    }


async def _collector_loop(
    store: MarketStore,
    client: ManifoldClient,
    config: Config,
) -> None:
    while True:
        start = time.monotonic()
        try:
            saved = await _collect_once(store, client, config.limit)
            await store.log_run(Run(None, "collect", True, f"saved {saved}", utc_now()))
        except Exception as exc:
            await store.log_run(Run(None, "collect", False, str(exc), utc_now()))
        elapsed = time.monotonic() - start
        await asyncio.sleep(max(0.0, config.interval_s - elapsed))


async def _collect_once(store: MarketStore, client: ManifoldClient, limit: int) -> int:
    quotes = await client.list_active_markets(limit)
    rows = quotes_to_snapshots(quotes)
    return await store.save_snapshots(rows)


async def _history_for_latest(
    store: MarketStore,
    latest: list[Snapshot],
    since_iso: str | None,
) -> dict[str, list[Snapshot]] | None:
    if since_iso is None:
        return None

    grouped = await store.snapshots_since_batch(list({s.market_id for s in latest}), since_iso)
    history: dict[str, list[Snapshot]] = {}
    for snapshot in latest:
        rows = [
            row
            for row in grouped.get(snapshot.market_id, [])
            if row.outcome == snapshot.outcome
        ]
        if rows:
            history[f"{snapshot.market_id}|{snapshot.outcome}"] = rows
    return history


def _state(ctx: Context) -> State:
    return ctx.request_context.lifespan_context


def _snapshot_dict(snapshot: Snapshot) -> dict:
    return {
        "id": snapshot.id,
        "market_id": snapshot.market_id,
        "question": snapshot.question,
        "outcome": snapshot.outcome,
        "price": snapshot.price,
        "volume": snapshot.volume,
        "captured_at": snapshot.captured_at,
    }


def _summary_text(summary: dict[str, Any]) -> str:
    market_count = summary["market_count"]
    window = summary["window"]
    movers = summary.get("top_movers") or []
    if movers:
        top = movers[0]
        return (
            f"{market_count} markets in {window}; top mover: "
            f"{top['outcome']} {top['delta']:+.3f} on {top['question']}"
        )
    return f"{market_count} markets in {window}; no movers available."


if __name__ == "__main__":
    mcp.run(transport="stdio")
