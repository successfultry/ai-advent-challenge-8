from __future__ import annotations

import json

from week_04.tech_radar.mcp_server_radar import (
    _normalize_enriched_candidate,
    build_comparison,
    extract_requirements,
    normalize_candidates,
)


def test_extract_requirements_is_deterministic() -> None:
    raw = extract_requirements(
        "Find typed and maintained data validation libraries for production backend service."
    )
    data = json.loads(raw)
    assert data["use_case"] == "data validation"
    assert "typed" in data["needs"]
    assert data["weights"]["fit_to_requirements"] == 0.45


def test_normalize_candidates_schema() -> None:
    search_json = json.dumps(
        {
            "items": [
                {
                    "full_name": "pydantic/pydantic",
                    "name": "pydantic",
                    "stargazers_count": 25000,
                    "language": "Python",
                }
            ]
        }
    )
    data = json.loads(normalize_candidates(search_json, max_candidates=1))
    candidate = data["candidates"][0]
    assert set(candidate) == {"label", "repo", "package", "reason", "package_guess"}
    assert candidate["repo"] == "pydantic/pydantic"


def test_normalize_enriched_candidate_fills_nulls() -> None:
    normalized = _normalize_enriched_candidate({"label": "x", "repo": "a/b", "package": "x"})
    assert normalized["package_guess"] is False
    assert normalized["github"]["stars"] is None
    assert normalized["github"]["open_issues"] is None
    assert normalized["github"]["topics"] == []
    assert normalized["readme"]["excerpt"] is None
    assert normalized["pypi"]["version"] is None
    assert normalized["pypi"]["latest_release_version"] is None
    assert normalized["pypi"]["latest_release_uploaded_at"] is None
    assert normalized["releases"]["items"] == []
    assert normalized["releases"]["latest_version"] is None
    assert normalized["releases"]["latest_uploaded_at"] is None


def test_build_comparison_applies_guess_penalty_only_on_failed_pypi() -> None:
    requirements_json = extract_requirements("Need async data validation library")
    enriched = [
        {
            "label": "guess_fail",
            "repo": "foo/guess_fail",
            "package": "guess-fail",
            "package_guess": True,
            "github": {"stars": 1000, "updated_at": "2026-06-20T00:00:00+00:00", "error": None},
            "readme": {"excerpt": "async typing", "error": None},
            "pypi": {"name": None, "version": None, "requires_python": None, "error": "not found"},
            "releases": {"items": [], "error": "not found"},
        },
        {
            "label": "guess_success",
            "repo": "foo/guess_success",
            "package": "guess-success",
            "package_guess": True,
            "github": {"stars": 1000, "updated_at": "2026-06-20T00:00:00+00:00", "error": None},
            "readme": {"excerpt": "async typing", "error": None},
            "pypi": {
                "name": "guess-success",
                "version": "1.2.3",
                "requires_python": ">=3.10",
                "error": None,
            },
            "releases": {
                "items": [{"version": "1.2.3", "uploaded_at": "2026-06-01T00:00:00+00:00"}],
                "error": None,
            },
        },
    ]

    response = json.loads(build_comparison(requirements_json, json.dumps(enriched)))
    by_label = {row["label"]: row for row in response["ranking"]}
    assert by_label["guess_fail"]["confidence_penalty"] == 0.1
    assert by_label["guess_success"]["confidence_penalty"] == 0.0


def test_build_comparison_handles_partial_evidence() -> None:
    requirements_json = extract_requirements("backend libraries")
    enriched = [
        {
            "label": "partial",
            "repo": "foo/partial",
            "package": "partial",
            "package_guess": False,
            "github": {"stars": None, "updated_at": None, "error": "rate limited"},
            "readme": {"excerpt": None, "error": "missing"},
            "pypi": {"name": None, "version": None, "requires_python": None, "error": "timeout"},
            "releases": {"items": [], "error": "timeout"},
        }
    ]
    response = json.loads(build_comparison(requirements_json, json.dumps({"candidates": enriched})))
    assert response["count"] == 1
    assert response["ranking"][0]["label"] == "partial"


def test_build_comparison_exposes_llm_report_evidence_fields() -> None:
    requirements_json = extract_requirements("Need typed, maintained data validation libs")
    enriched = [
        {
            "label": "pydantic",
            "repo": "pydantic/pydantic",
            "package": "pydantic",
            "package_guess": False,
            "github": {
                "stargazers_count": 25000,
                "updated_at": "2026-06-20T00:00:00+00:00",
                "open_issues_count": 123,
                "topics": ["python", "validation"],
                "error": None,
            },
            "readme": {"excerpt": "typed validation for production", "error": None},
            "pypi": {
                "name": "pydantic",
                "version": "2.13.4",
                "requires_python": ">=3.9",
                "summary": "Data validation and settings",
                "error": None,
            },
            "releases": {
                "items": [{"version": "2.14.0a1", "uploaded_at": "2026-06-01T00:00:00+00:00"}],
                "error": None,
            },
        }
    ]

    response = json.loads(build_comparison(requirements_json, json.dumps({"candidates": enriched})))
    row = response["ranking"][0]
    evidence = row["evidence"]
    assert evidence["github"]["stars"] == 25000
    assert evidence["github"]["updated_at"] == "2026-06-20T00:00:00+00:00"
    assert evidence["pypi"]["version"] == "2.13.4"
    assert evidence["pypi"]["requires_python"] == ">=3.9"
    assert isinstance(evidence["releases"]["items"], list)
    assert evidence["github"]["open_issues"] == 123
    assert evidence["releases"]["latest_uploaded_at"] == "2026-06-01T00:00:00+00:00"



