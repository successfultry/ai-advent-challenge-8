from __future__ import annotations

from datetime import UTC, datetime, timedelta

from week_04.market_watch.store import Snapshot, utc_now


def summarize_snapshots(
    latest: list[Snapshot],
    history: dict[str, list[Snapshot]] | None = None,
    window: str = "all",
    top_n: int = 10,
) -> dict:
    markets = sorted(latest, key=lambda item: item.volume or 0.0, reverse=True)[:top_n]
    result = {
        "window": window,
        "market_count": len({item.market_id for item in latest}),
        "generated_at": utc_now(),
        "markets": [_snapshot_dict(item) for item in markets],
    }

    if history:
        result["top_movers"] = _top_movers(history, top_n)

    return result


def since_for_window(window: str, now: datetime | None = None) -> str | None:
    delta = _window_delta(window)
    if delta is None:
        return None
    now = now or datetime.now(UTC)
    return (now - delta).isoformat()


def _top_movers(history: dict[str, list[Snapshot]], top_n: int) -> list[dict]:
    movers: list[dict] = []
    for market_id, rows in history.items():
        ordered = sorted(rows, key=lambda item: (item.captured_at, item.id or 0))
        if len(ordered) < 2:
            continue
        first = ordered[0]
        last = ordered[-1]
        movers.append(
            {
                "market_id": market_id,
                "question": last.question,
                "outcome": last.outcome,
                "from_price": first.price,
                "to_price": last.price,
                "delta": last.price - first.price,
            }
        )
    return sorted(movers, key=lambda item: abs(item["delta"]), reverse=True)[:top_n]


def _snapshot_dict(snapshot: Snapshot) -> dict:
    return {
        "market_id": snapshot.market_id,
        "question": snapshot.question,
        "outcome": snapshot.outcome,
        "price": snapshot.price,
        "volume": snapshot.volume,
    }


def _window_delta(window: str) -> timedelta | None:
    value = window.strip().lower()
    if value == "all" or len(value) < 2:
        return None

    amount_text = value[:-1]
    unit = value[-1]
    if not amount_text.isdigit():
        return None

    amount = int(amount_text)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    return None
