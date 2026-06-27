from __future__ import annotations

import json
from pathlib import Path

import pytest

from week_04.tech_radar.mcp_server_reports import list_reports, load_report, save_report


def test_save_report_rejects_unsafe_slug() -> None:
    data = json.loads(save_report("x", "../escape"))
    assert "error" in data


def test_save_and_list_and_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("week_04.tech_radar.mcp_server_reports._OUTPUTS_DIR", tmp_path)

    saved = json.loads(save_report("# Radar", "py_validation_radar_2026"))
    assert saved["ok"] is True
    assert saved["path"] == "tech_radar_outputs/py_validation_radar_2026.md"
    assert (tmp_path / "py_validation_radar_2026.md").exists()

    listed = json.loads(list_reports())
    assert listed["count"] == 1
    assert listed["reports"] == ["py_validation_radar_2026.md"]

    loaded = load_report("py_validation_radar_2026")
    assert loaded == "# Radar"


