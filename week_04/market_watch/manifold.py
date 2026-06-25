from dataclasses import dataclass
from typing import Any

import httpx

from week_04.market_watch.store import Snapshot, utc_now


@dataclass(frozen=True)
class MarketQuote:
    market_id: str
    question: str
    outcome: str
    price: float
    volume: float | None


class ManifoldClient:
    def __init__(
        self,
        base_url: str = "https://api.manifold.markets",
        timeout_s: float = 15.0,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(timeout_s))

    async def list_active_markets(self, limit: int = 10) -> list[MarketQuote]:
        params = {"limit": str(max(limit * 5, 100))}
        markets = await self._get_markets(params)
        quotes: list[MarketQuote] = []
        binary_markets = 0
        for market in sorted(markets, key=_sort_volume, reverse=True):
            market_quotes = _quotes_from_market(market)
            if not market_quotes:
                continue
            quotes.extend(market_quotes)
            binary_markets += 1
            if binary_markets >= limit:
                break
        return quotes

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_markets(self, params: dict[str, str]) -> list[dict[str, Any]]:
        try:
            response = await self._client.get("/v0/markets", params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            url = str(exc.request.url)
            status = exc.response.status_code
            raise RuntimeError(f"Manifold request failed: GET {url} -> {status}") from exc
        except httpx.HTTPError as exc:
            url = str(exc.request.url) if exc.request else "unknown URL"
            raise RuntimeError(f"Manifold request failed: GET {url}: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("Manifold returned invalid JSON") from exc

        if not isinstance(data, list):
            raise RuntimeError("Manifold /v0/markets returned an unexpected payload")
        return [item for item in data if isinstance(item, dict)]


def quotes_to_snapshots(quotes: list[MarketQuote]) -> list[Snapshot]:
    captured_at = utc_now()
    return [
        Snapshot(
            id=None,
            market_id=quote.market_id,
            question=quote.question,
            outcome=quote.outcome,
            price=quote.price,
            volume=quote.volume,
            captured_at=captured_at,
        )
        for quote in quotes
    ]


def _quotes_from_market(market: dict[str, Any]) -> list[MarketQuote]:
    if market.get("outcomeType") != "BINARY" or market.get("isResolved"):
        return []

    question = _string_field(market, "question")
    market_id = _string_field(market, "id")
    probability = _optional_float(market.get("probability"))
    volume = _market_volume(market)

    if not question or not market_id or probability is None:
        return []

    return [
        MarketQuote(
            market_id=market_id,
            question=question,
            outcome="Yes",
            price=probability,
            volume=volume,
        ),
        MarketQuote(
            market_id=market_id,
            question=question,
            outcome="No",
            price=1 - probability,
            volume=volume,
        ),
    ]


def _market_volume(market: dict[str, Any]) -> float | None:
    volume_24h = _optional_float(market.get("volume24Hours"))
    if volume_24h is not None:
        return volume_24h
    return _optional_float(market.get("volume"))


def _sort_volume(market: dict[str, Any]) -> float:
    return _market_volume(market) or 0.0


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_field(market: dict[str, Any], key: str) -> str:
    value = market.get(key)
    return value.strip() if isinstance(value, str) else str(value) if value is not None else ""
