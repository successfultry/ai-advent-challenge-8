from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from week_04.mcp_server_places import build_report, save_to_file, search_places

_MOCK_FSQ_RESPONSE = {
    "results": [
        {
            "name": "Ristorante Roma",
            "location": {
                "address": "Via Roma 1",
                "locality": "Milan",
                "country": "IT",
            },
            "categories": [{"name": "Italian Restaurant"}],
            "distance": 350,
            "tel": "+39 02 1234567",
            "website": "https://roma.example.com",
        },
        {
            "name": "Pizzeria Bella",
            "location": {
                "address": "Corso Buenos Aires 10",
                "locality": "Milan",
                "country": "IT",
            },
            "categories": [{"name": "Pizza Place"}],
            "distance": 120,
            "tel": "",
            "website": "",
        },
        {
            "name": "Far Away Cafe",
            "location": {
                "address": "Remote Street 99",
                "locality": "Milan",
                "country": "IT",
            },
            "categories": [{"name": "Cafe"}],
            "distance": 5000,
            "tel": "",
            "website": "",
        },
    ]
}

_MOCK_SEARCH_JSON = json.dumps(
    {
        "near": "Milan",
        "query": "italian restaurant",
        "count": 3,
        "places": [
            {
                "name": "Ristorante Roma",
                "address": "Via Roma 1",
                "locality": "Milan",
                "country": "IT",
                "categories": ["Italian Restaurant"],
                "distance_m": 350,
                "tel": "+39 02 1234567",
                "website": "https://roma.example.com",
            },
            {
                "name": "Pizzeria Bella",
                "address": "Corso Buenos Aires 10",
                "locality": "Milan",
                "country": "IT",
                "categories": ["Pizza Place"],
                "distance_m": 120,
                "tel": "",
                "website": "",
            },
            {
                "name": "Far Away Cafe",
                "address": "Remote Street 99",
                "locality": "Milan",
                "country": "IT",
                "categories": ["Cafe"],
                "distance_m": 5000,
                "tel": "",
                "website": "",
            },
        ],
    }
)


def _mock_async_client(resp: MagicMock) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)
    return mock_client


@pytest.mark.asyncio
async def test_search_places_returns_expected_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _MOCK_FSQ_RESPONSE
    mock_client = _mock_async_client(mock_resp)

    with patch("week_04.mcp_server_places.httpx.AsyncClient", return_value=mock_client):
        result = await search_places(near="Milan", query="italian restaurant", limit=5)

    data = json.loads(result)
    assert "error" not in data
    assert data["near"] == "Milan"
    assert data["query"] == "italian restaurant"
    assert data["count"] == 3
    assert [p["name"] for p in data["places"]] == [
        "Ristorante Roma",
        "Pizzeria Bella",
        "Far Away Cafe",
    ]


@pytest.mark.asyncio
async def test_search_places_uses_pro_fields_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_client = _mock_async_client(mock_resp)

    with patch("week_04.mcp_server_places.httpx.AsyncClient", return_value=mock_client):
        await search_places(near="Tokyo", query="sushi", sort="DISTANCE")

    params = mock_client.get.call_args.kwargs["params"]
    assert params["fields"] == "name,location,categories,distance,tel,website"
    assert params["sort"] == "DISTANCE"


@pytest.mark.asyncio
async def test_search_places_rejects_empty_near(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test-key")
    result = await search_places(near="  ", query="restaurant")
    assert "error" in json.loads(result)


@pytest.mark.asyncio
async def test_search_places_rejects_bad_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test-key")
    result = await search_places(near="Tokyo", query="sushi", limit=0)
    assert "error" in json.loads(result)


@pytest.mark.asyncio
async def test_search_places_rejects_unshown_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test-key")
    result = await search_places(near="Tokyo", query="sushi", sort="RATING")
    data = json.loads(result)
    assert data["error"] == "sort must be RELEVANCE or DISTANCE"


@pytest.mark.asyncio
async def test_search_places_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOURSQUARE_API_KEY", raising=False)
    result = await search_places(near="Tokyo", query="sushi")
    data = json.loads(result)
    assert "FOURSQUARE_API_KEY" in data["error"]


@pytest.mark.asyncio
async def test_search_places_handles_non_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.side_effect = ValueError("not json")
    mock_client = _mock_async_client(mock_resp)

    with patch("week_04.mcp_server_places.httpx.AsyncClient", return_value=mock_client):
        result = await search_places(near="Tokyo", query="sushi")

    assert json.loads(result)["error"] == "Foursquare returned non-JSON body"


def test_build_report_sorts_by_distance() -> None:
    result = build_report(data_json=_MOCK_SEARCH_JSON, top_n=3)
    data = json.loads(result)
    report = data["report_markdown"]
    assert report.index("Pizzeria Bella") < report.index("Ristorante Roma")


def test_build_report_filters_by_max_distance() -> None:
    result = build_report(data_json=_MOCK_SEARCH_JSON, top_n=5, max_distance_m=500)
    data = json.loads(result)
    assert data["shown"] == 2
    assert "Far Away Cafe" not in data["report_markdown"]


def test_build_report_respects_top_n() -> None:
    result = build_report(data_json=_MOCK_SEARCH_JSON, top_n=1)
    data = json.loads(result)
    assert data["shown"] == 1
    assert "Pizzeria Bella" in data["report_markdown"]
    assert "Ristorante Roma" not in data["report_markdown"]


def test_build_report_handles_non_positive_top_n() -> None:
    result = build_report(data_json=_MOCK_SEARCH_JSON, top_n=-1)
    data = json.loads(result)
    assert data["shown"] == 0


def test_build_report_handles_error_in_input() -> None:
    error_json = json.dumps({"error": "Foursquare API error: 403 Forbidden"})
    result = build_report(data_json=error_json)
    data = json.loads(result)
    assert "403" in data["error"]


def test_build_report_handles_invalid_json() -> None:
    result = build_report(data_json="not json at all")
    assert "error" in json.loads(result)


def test_build_report_markdown_structure() -> None:
    result = build_report(data_json=_MOCK_SEARCH_JSON, top_n=5)
    md = json.loads(result)["report_markdown"]
    assert "## Places:" in md
    assert "---" in md
    assert "Showing" in md


def test_save_to_file_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("week_04.mcp_server_places._OUTPUTS_DIR", tmp_path)

    result = save_to_file(content="# Hello\nWorld", filename="test_report.md")
    data = json.loads(result)

    assert data["ok"] is True
    saved = tmp_path / "test_report.md"
    assert saved.exists()
    assert saved.read_text(encoding="utf-8") == "# Hello\nWorld"
    assert data["path"].endswith("test_report.md")
    assert "\\" not in data["path"]
    assert data["bytes"] == len(b"# Hello\nWorld")


def test_save_to_file_rejects_path_traversal() -> None:
    result = save_to_file(content="bad", filename="../escape.md")
    assert "error" in json.loads(result)


def test_save_to_file_rejects_slash_in_name() -> None:
    result = save_to_file(content="bad", filename="sub/dir/file.md")
    assert "error" in json.loads(result)


def test_save_to_file_rejects_dot_filename() -> None:
    result = save_to_file(content="bad", filename=".")
    assert "error" in json.loads(result)


def test_save_to_file_rejects_empty_filename() -> None:
    result = save_to_file(content="content", filename="  ")
    assert "error" in json.loads(result)
