from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tech-radar-radar", log_level="ERROR")

_DEFAULT_WEIGHTS = {
    "fit_to_requirements": 0.45,
    "maintenance_activity": 0.25,
    "release_freshness": 0.20,
    "community_signal": 0.10,
}

_KEYWORDS_USE_CASE = {
    "data validation": ["validation", "validate", "schema", "pydantic", "marshmallow", "attrs"],
    "http client": ["http", "client", "request", "api client", "networking"],
    "orm": ["orm", "database", "sqlalchemy", "peewee", "model layer"],
}


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(value: str | None) -> int | None:
    dt = _to_datetime(value)
    if dt is None:
        return None
    now = datetime.now(UTC)
    return max(0, (now - dt).days)


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def _pick_use_case(text: str) -> str:
    for use_case, words in _KEYWORDS_USE_CASE.items():
        if any(word in text for word in words):
            return use_case
    return "backend development"


def _extract_needs(text: str) -> list[str]:
    needs: list[str] = []
    mapping = [
        ("typed", ["typed", "type hints", "typing"]),
        ("production-ready", ["production", "reliable", "stable"]),
        ("maintained", ["maintained", "active", "well-maintained"]),
        ("async", ["async", "asyncio"]),
        ("http2", ["http/2", "http2"]),
    ]
    for need, words in mapping:
        if any(word in text for word in words):
            needs.append(need)
    if not needs:
        needs = ["maintained", "production-ready"]
    return needs


def _extract_io_model(text: str) -> str:
    if "async-only" in text or "async only" in text or "only async" in text:
        return "async-only"
    if "sync-only" in text or "sync only" in text or "only sync" in text:
        return "sync-only"
    if "async" in text and "sync" in text:
        return "both"
    if "async" in text:
        return "async-preferred"
    return "any"


def _guess_package_name(full_name: str, repo_name: str) -> tuple[str, bool]:
    candidate = repo_name.strip().lower()
    if candidate.startswith("python-"):
        candidate = candidate[len("python-") :]
    candidate = candidate.replace("_", "-")
    package_guess = True
    known_exact = {"pydantic", "marshmallow", "aiohttp", "httpx", "requests", "attrs"}
    if candidate in known_exact:
        package_guess = False
    return candidate or full_name.split("/")[-1], package_guess


def _related_pypi_name(expected: str, actual: str | None) -> bool:
    if not actual:
        return False
    def normalize_token(value: str) -> str:
        return re.sub(r"[-_.]+", "", value.lower())

    return normalize_token(expected) == normalize_token(actual)


def _normalize_enriched_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    github = candidate.get("github") if isinstance(candidate.get("github"), dict) else {}
    readme = candidate.get("readme") if isinstance(candidate.get("readme"), dict) else {}
    pypi = candidate.get("pypi") if isinstance(candidate.get("pypi"), dict) else {}
    releases = candidate.get("releases") if isinstance(candidate.get("releases"), dict) else {}
    release_items = releases.get("items") if isinstance(releases.get("items"), list) else []
    latest_release = (
        release_items[0] if release_items and isinstance(release_items[0], dict) else {}
    )

    return {
        "label": candidate.get("label"),
        "repo": candidate.get("repo"),
        "package": candidate.get("package"),
        "package_guess": bool(candidate.get("package_guess", False)),
        "github": {
            "stars": github.get("stars", github.get("stargazers_count")),
            "updated_at": github.get("updated_at"),
            "open_issues": github.get("open_issues", github.get("open_issues_count")),
            "topics": github.get("topics") if isinstance(github.get("topics"), list) else [],
            "error": github.get("error"),
        },
        "readme": {
            "excerpt": readme.get("excerpt"),
            "error": readme.get("error"),
        },
        "pypi": {
            "version": pypi.get("version"),
            "requires_python": pypi.get("requires_python"),
            "name": pypi.get("name"),
            "summary": pypi.get("summary"),
            "classifiers": pypi.get("classifiers"),
            "latest_release_version": pypi.get(
                "latest_release_version", latest_release.get("version")
            ),
            "latest_release_uploaded_at": pypi.get(
                "latest_release_uploaded_at", latest_release.get("uploaded_at")
            ),
            "error": pypi.get("error"),
        },
        "releases": {
            "items": release_items,
            "latest_version": releases.get("latest_version", latest_release.get("version")),
            "latest_uploaded_at": releases.get(
                "latest_uploaded_at", latest_release.get("uploaded_at")
            ),
            "error": releases.get("error"),
        },
    }


# Deterministic numeric scoring is intentional in MCP (arithmetic only).
# Narrative analysis/recommendations must be produced by the LLM agent.
def _maintenance_score(candidate: dict[str, Any]) -> float:
    gh = candidate["github"]
    if gh.get("error"):
        return 0.1
    days = _days_since(gh.get("updated_at"))
    if days is None:
        return 0.35
    if days <= 30:
        return 1.0
    if days <= 90:
        return 0.8
    if days <= 180:
        return 0.6
    if days <= 365:
        return 0.4
    return 0.2


def _freshness_score(candidate: dict[str, Any]) -> float:
    releases = candidate["releases"]
    if releases.get("error"):
        return 0.1
    items = releases.get("items") or []
    latest = items[0].get("uploaded_at") if items else None
    days = _days_since(latest)
    if days is None:
        return 0.3
    if days <= 30:
        return 1.0
    if days <= 90:
        return 0.8
    if days <= 180:
        return 0.6
    if days <= 365:
        return 0.4
    return 0.2


def _community_score(candidate: dict[str, Any]) -> float:
    gh = candidate["github"]
    stars = gh.get("stars")
    if gh.get("error") or not isinstance(stars, (int, float)):
        return 0.15
    if stars >= 50_000:
        return 1.0
    if stars >= 10_000:
        return 0.8
    if stars >= 3_000:
        return 0.6
    if stars >= 500:
        return 0.4
    return 0.2


def _fit_score(candidate: dict[str, Any], requirements: dict[str, Any]) -> float:
    text_parts = [
        str(candidate.get("label") or ""),
        str((candidate.get("readme") or {}).get("excerpt") or ""),
        str((candidate.get("pypi") or {}).get("summary") or ""),
        " ".join((candidate.get("pypi") or {}).get("classifiers") or []),
    ]
    haystack = " ".join(text_parts).lower()
    score = 0.4
    needs = requirements.get("needs") or []
    for need in needs:
        if need == "typed" and ("typing" in haystack or "type" in haystack):
            score += 0.12
        elif need == "production-ready" and (
            "production" in haystack or "stable" in haystack or "mature" in haystack
        ):
            score += 0.12
        elif need == "maintained" and not (candidate.get("github") or {}).get("error"):
            score += 0.10
        elif need == "async" and ("async" in haystack or "asyncio" in haystack):
            score += 0.16
        elif need == "http2" and ("http/2" in haystack or "http2" in haystack):
            score += 0.10
    if requirements.get("io_model") == "async-only" and "async" not in haystack:
        score -= 0.25
    if requirements.get("io_model") == "sync-only" and "async" in haystack:
        score -= 0.10
    return _clamp(score)


@mcp.tool(description="Extract structured requirements from a natural language user prompt.")
def extract_requirements(user_prompt: str) -> str:
    text = user_prompt.strip()
    if not text:
        return _json_dumps({"error": "user_prompt must be a non-empty string"})

    lower = text.lower()
    use_case = _pick_use_case(lower)
    requirements = {
        "io_model": _extract_io_model(lower),
        "use_case": use_case,
        "needs": _extract_needs(lower),
        "weights": _DEFAULT_WEIGHTS,
    }
    return _json_dumps(requirements)


@mcp.tool(description="Normalize search results into stable candidates with repo/package fields.")
def normalize_candidates(search_results_json: str, max_candidates: int = 3) -> str:
    try:
        data = json.loads(search_results_json)
    except json.JSONDecodeError:
        return _json_dumps({"error": "search_results_json must be valid JSON"})

    if isinstance(data, dict) and data.get("error"):
        return _json_dumps({"error": data.get("error")})

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return _json_dumps({"error": "search_results_json must contain an items list"})

    candidates: list[dict[str, Any]] = []
    for item in items:
        full_name = str(item.get("full_name") or "").strip()
        repo_name = str(item.get("name") or "").strip()
        if "/" not in full_name or not repo_name:
            continue
        package, package_guess = _guess_package_name(full_name=full_name, repo_name=repo_name)
        reason = f"{item.get('stargazers_count', 0)} stars, language={item.get('language')}"
        candidates.append(
            {
                "label": repo_name,
                "repo": full_name,
                "package": package,
                "reason": reason,
                "package_guess": package_guess,
            }
        )
        if len(candidates) >= max(1, max_candidates):
            break

    return _json_dumps({"count": len(candidates), "candidates": candidates})


@mcp.tool(
    description=(
        "Build deterministic scoring comparison. Expects enriched candidates containing "
        "candidate metadata + github/readme/pypi/releases evidence."
    )
)
def build_comparison(requirements_json: str, enriched_candidates_json: str) -> str:
    try:
        requirements = json.loads(requirements_json)
    except json.JSONDecodeError:
        return _json_dumps({"error": "requirements_json must be valid JSON"})

    if isinstance(requirements, dict) and requirements.get("error"):
        return _json_dumps({"error": requirements.get("error")})
    if not isinstance(requirements, dict):
        return _json_dumps({"error": "requirements_json must decode to an object"})

    try:
        raw = json.loads(enriched_candidates_json)
    except json.JSONDecodeError:
        return _json_dumps({"error": "enriched_candidates_json must be valid JSON"})

    if isinstance(raw, dict):
        candidates_raw = raw.get("candidates")
    else:
        candidates_raw = raw
    if not isinstance(candidates_raw, list):
        return _json_dumps({"error": "enriched_candidates_json must contain a candidates list"})

    weights = requirements.get("weights")
    if not isinstance(weights, dict):
        weights = _DEFAULT_WEIGHTS

    scored: list[dict[str, Any]] = []
    for item in candidates_raw:
        normalized = _normalize_enriched_candidate(item if isinstance(item, dict) else {})

        fit = _fit_score(normalized, requirements)
        maintenance = _maintenance_score(normalized)
        freshness = _freshness_score(normalized)
        community = _community_score(normalized)

        confidence_penalty = 0.0
        if normalized["package_guess"]:
            pypi_name = normalized["pypi"].get("name")
            has_pypi_error = normalized["pypi"].get("error") or normalized["releases"].get("error")
            unrelated = not _related_pypi_name(str(normalized["package"]), pypi_name)
            if has_pypi_error or unrelated:
                confidence_penalty = 0.10

        total = (
            fit * float(weights.get("fit_to_requirements", _DEFAULT_WEIGHTS["fit_to_requirements"]))
            + maintenance
            * float(weights.get("maintenance_activity", _DEFAULT_WEIGHTS["maintenance_activity"]))
            + freshness
            * float(weights.get("release_freshness", _DEFAULT_WEIGHTS["release_freshness"]))
            + community
            * float(weights.get("community_signal", _DEFAULT_WEIGHTS["community_signal"]))
        )
        total = _clamp(total - confidence_penalty)

        scored.append(
            {
                "label": normalized["label"],
                "repo": normalized["repo"],
                "package": normalized["package"],
                "package_guess": normalized["package_guess"],
                "components": {
                    "fit_to_requirements": round(fit, 3),
                    "maintenance_activity": round(maintenance, 3),
                    "release_freshness": round(freshness, 3),
                    "community_signal": round(community, 3),
                },
                "confidence_penalty": round(confidence_penalty, 3),
                "score": round(total, 4),
                "evidence": normalized,
            }
        )

    scored.sort(key=lambda row: row["score"], reverse=True)

    summary = []
    for row in scored:
        summary.append(
            f"{row['label']}: score={row['score']:.3f}, "
            f"fit={row['components']['fit_to_requirements']:.2f}, "
            f"maintenance={row['components']['maintenance_activity']:.2f}, "
            f"freshness={row['components']['release_freshness']:.2f}, "
            f"community={row['components']['community_signal']:.2f}, "
            f"penalty={row['confidence_penalty']:.2f}"
        )

    payload = {
        "requirements": requirements,
        "weights": weights,
        "count": len(scored),
        "ranking": scored,
        "summary": summary,
    }
    return _json_dumps(payload)


if __name__ == "__main__":
    mcp.run(transport="stdio")

