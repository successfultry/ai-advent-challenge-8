from datetime import UTC, datetime

from week_04.market_watch.aggregate import since_for_window, summarize_snapshots
from week_04.market_watch.manifold import _quotes_from_market
from week_04.market_watch.store import MarketStore, Run, Snapshot, Summary


def _snapshot(
    market_id: str,
    outcome: str,
    price: float,
    volume: float | None,
    captured_at: str,
    question: str = "Will the test market resolve?",
) -> Snapshot:
    return Snapshot(
        id=None,
        market_id=market_id,
        question=question,
        outcome=outcome,
        price=price,
        volume=volume,
        captured_at=captured_at,
    )


def test_summarize_snapshots_sorts_caps_and_counts():
    latest = [
        _snapshot("low", "Yes", 0.1, 10.0, "2026-01-01T00:00:00+00:00"),
        _snapshot("high", "Yes", 0.2, 50.0, "2026-01-01T00:00:00+00:00"),
        _snapshot("none", "Yes", 0.3, None, "2026-01-01T00:00:00+00:00"),
    ]

    summary = summarize_snapshots(latest, top_n=2)

    assert summary["market_count"] == 3
    assert [item["market_id"] for item in summary["markets"]] == ["high", "low"]
    assert "top_movers" not in summary


def test_summarize_snapshots_top_movers_delta_order():
    history = {
        "m1|Yes": [
            _snapshot("m1", "Yes", 0.4, 100.0, "2026-01-01T00:00:00+00:00"),
            _snapshot("m1", "Yes", 0.7, 100.0, "2026-01-01T01:00:00+00:00"),
        ],
        "m2|No": [
            _snapshot("m2", "No", 0.8, 200.0, "2026-01-01T00:00:00+00:00"),
            _snapshot("m2", "No", 0.6, 200.0, "2026-01-01T01:00:00+00:00"),
        ],
    }

    summary = summarize_snapshots([rows[-1] for rows in history.values()], history=history)

    assert [item["market_id"] for item in summary["top_movers"]] == ["m1|Yes", "m2|No"]
    assert summary["top_movers"][0]["delta"] == 0.29999999999999993
    assert summary["top_movers"][1]["delta"] == -0.20000000000000007


def test_since_for_window():
    now = datetime(2026, 1, 8, 12, 0, tzinfo=UTC)

    assert since_for_window("all", now) is None
    assert since_for_window("oops", now) is None
    assert since_for_window("1h", now) == "2026-01-08T11:00:00+00:00"
    assert since_for_window("24h", now) == "2026-01-07T12:00:00+00:00"
    assert since_for_window("7d", now) == "2026-01-01T12:00:00+00:00"


def test_quotes_from_binary_manifold_market():
    quotes = _quotes_from_market(
        {
            "id": "market-1",
            "question": "Will this pass?",
            "outcomeType": "BINARY",
            "isResolved": False,
            "probability": 0.42,
            "volume24Hours": 123.45,
        }
    )

    assert [(q.market_id, q.outcome, q.price, q.volume) for q in quotes] == [
        ("market-1", "Yes", 0.42, 123.45),
        ("market-1", "No", 0.5800000000000001, 123.45),
    ]


def test_quotes_from_market_skips_resolved_non_binary_and_missing_probability():
    base = {
        "id": "market-1",
        "question": "Will this pass?",
        "outcomeType": "BINARY",
        "isResolved": False,
        "probability": 0.42,
    }

    assert _quotes_from_market({**base, "isResolved": True}) == []
    assert _quotes_from_market({**base, "outcomeType": "MULTIPLE_CHOICE"}) == []
    assert _quotes_from_market({**base, "probability": None}) == []


async def test_market_store_round_trip(tmp_path):
    store = MarketStore(str(tmp_path / "market_watch.db"))
    await store.init()
    try:
        saved = await store.save_snapshots(
            [
                _snapshot("m1", "Yes", 0.4, 100.0, "2026-01-01T00:00:00+00:00"),
                _snapshot("m1", "No", 0.6, 100.0, "2026-01-01T00:00:00+00:00"),
                _snapshot("m1", "Yes", 0.5, 110.0, "2026-01-01T01:00:00+00:00"),
                _snapshot("m2", "Yes", 0.2, None, "2026-01-01T01:00:00+00:00"),
            ]
        )
        latest = await store.latest_per_market()
        since = await store.snapshots_since("m1", "2026-01-01T00:30:00+00:00")
        summary_id = await store.save_summary(
            Summary(
                id=None,
                window="1h",
                created_at="2026-01-01T01:00:00+00:00",
                text="test summary",
                payload='{"ok": true}',
            )
        )
        summary = await store.latest_summary()
        await store.log_run(
            Run(None, "collect", True, "saved 4", "2026-01-01T01:00:00+00:00")
        )
    finally:
        await store.close()

    assert saved == 4
    assert {(row.market_id, row.outcome, row.price) for row in latest} == {
        ("m1", "Yes", 0.5),
        ("m1", "No", 0.6),
        ("m2", "Yes", 0.2),
    }
    assert [(row.market_id, row.outcome, row.price) for row in since] == [("m1", "Yes", 0.5)]
    assert summary_id == 1
    assert summary is not None
    assert summary.text == "test summary"
