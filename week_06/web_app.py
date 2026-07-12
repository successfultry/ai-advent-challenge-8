from __future__ import annotations

import hmac
import os
import threading
import time
from dataclasses import asdict

from flask import Flask, jsonify, render_template, request

from shared.client import get_client
from shared.config import PROVIDERS
from week_06.local_client import OllamaClientError
from week_06.workbench import DEFAULT_MODE, MODE_INSTRUCTIONS, WorkbenchService, local_providers

LOCAL_ENDPOINT = "http://localhost:11434/v1"
DEFAULT_LOCAL_PROVIDER = "Qwen2.5 3B (Ollama, local)"
app = Flask(__name__, template_folder="templates")

_LOCAL_PROVIDERS = local_providers()
if not _LOCAL_PROVIDERS:
    raise RuntimeError("No local providers configured in shared/config.py")

_DEFAULT_PROVIDER = (
    os.getenv("LLM_PROVIDER", DEFAULT_LOCAL_PROVIDER).strip() or DEFAULT_LOCAL_PROVIDER
)
if _DEFAULT_PROVIDER not in _LOCAL_PROVIDERS:
    raise RuntimeError(
        f"LLM_PROVIDER={_DEFAULT_PROVIDER!r} is not local. Expected one of: "
        f"{', '.join(_LOCAL_PROVIDERS)}"
    )

_PRIVATE_API_KEY = os.getenv("PRIVATE_LLM_API_KEY", "").strip()
if not _PRIVATE_API_KEY:
    raise RuntimeError("PRIVATE_LLM_API_KEY is required")

MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "4000"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "10"))
_services: dict[str, WorkbenchService] = {}


class _FixedWindowRateLimiter:
    def __init__(self, *, limit_per_min: int) -> None:
        self.limit_per_min = max(1, limit_per_min)
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], tuple[int, int]] = {}

    def check(self, api_key: str, client_ip: str) -> tuple[bool, int]:
        now = int(time.time())
        window_start = now - (now % 60)
        key = (api_key, client_ip)
        with self._lock:
            prev_start, prev_count = self._windows.get(key, (window_start, 0))
            if prev_start != window_start:
                prev_start, prev_count = window_start, 0
            if prev_count >= self.limit_per_min:
                retry_after = max(1, 60 - (now - window_start))
                self._windows[key] = (prev_start, prev_count)
                return False, retry_after
            self._windows[key] = (prev_start, prev_count + 1)
            return True, 0


_rate_limiter = _FixedWindowRateLimiter(limit_per_min=RATE_LIMIT_PER_MIN)


def _json_error(status: int, message: str):
    return jsonify({"error": message, "code": status}), status


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _bearer_key() -> str:
    auth = request.headers.get("Authorization", "").strip()
    if not auth.lower().startswith("bearer "):
        return ""
    return auth[7:].strip()


def _authorize():
    presented = _bearer_key()
    if not presented or not hmac.compare_digest(presented, _PRIVATE_API_KEY):
        return _json_error(401, "unauthorized")
    allowed, retry_after = _rate_limiter.check(presented, _client_ip())
    if not allowed:
        response = jsonify({"error": "rate limit exceeded", "code": 429})
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    return None


def _validate_provider(provider_name: str) -> str:
    if provider_name not in _LOCAL_PROVIDERS:
        raise ValueError(
            f"Unsupported provider: {provider_name}. Expected one of: {', '.join(_LOCAL_PROVIDERS)}"
        )
    return provider_name


def _validate_prompt(prompt: str) -> str:
    clean = prompt.strip()
    if not clean:
        raise ValueError("Prompt must not be empty")
    if len(clean) > MAX_PROMPT_CHARS:
        raise OverflowError(f"prompt too large (max {MAX_PROMPT_CHARS} chars)")
    return clean


def _get_service(provider_name: str) -> WorkbenchService:
    name = _validate_provider(provider_name)
    if name not in _services:
        _services[name] = WorkbenchService(provider_name=name)
    return _services[name]


def _parse_payload() -> tuple[str, str, str]:
    payload = request.get_json(silent=True) or {}
    prompt = _validate_prompt(str(payload.get("prompt", "")))
    mode = str(payload.get("mode", DEFAULT_MODE)).strip() or DEFAULT_MODE
    provider_name = str(payload.get("provider", _DEFAULT_PROVIDER)).strip() or _DEFAULT_PROVIDER
    return prompt, mode, provider_name


@app.get("/")
def index():
    return render_template(
        "workbench.html",
        default_provider=_DEFAULT_PROVIDER,
        providers=_LOCAL_PROVIDERS,
        modes=[{"id": mode, "label": mode.replace("_", " ").title()} for mode in MODE_INSTRUCTIONS],
        endpoint=LOCAL_ENDPOINT,
        max_prompt_chars=MAX_PROMPT_CHARS,
        rate_limit_per_min=RATE_LIMIT_PER_MIN,
    )


@app.get("/api/health")
def api_health():
    auth_error = _authorize()
    if auth_error is not None:
        return auth_error
    return _health_impl()


def _health_impl():
    provider_name = request.args.get("provider", _DEFAULT_PROVIDER)
    try:
        provider_name = _validate_provider(provider_name)
        client, model_id = get_client(provider_name)
        client.models.list()
    except Exception as exc:
        return _json_error(502, f"health check failed: {exc}")
    return jsonify(
        {
            "ok": True,
            "provider": provider_name,
            "model": model_id,
            "endpoint": PROVIDERS[provider_name].base_url,
            "max_prompt_chars": MAX_PROMPT_CHARS,
            "rate_limit_per_min": RATE_LIMIT_PER_MIN,
        }
    )


@app.get("/api/history")
def api_history():
    auth_error = _authorize()
    if auth_error is not None:
        return auth_error
    return _history_impl()


def _history_impl():
    return jsonify({"items": [], "storage": "client-side"})


@app.post("/api/chat")
def api_chat():
    auth_error = _authorize()
    if auth_error is not None:
        return auth_error
    return _chat_impl()


def _chat_impl():
    try:
        prompt, mode, provider_name = _parse_payload()
        result = _get_service(provider_name).ask(mode=mode, prompt=prompt)
    except ValueError as exc:
        return _json_error(400, str(exc))
    except OverflowError as exc:
        return _json_error(413, str(exc))
    except OllamaClientError as exc:
        message = f"{exc}. Local model unavailable. Ensure Ollama is running (`ollama serve`)."
        return _json_error(502, message)
    payload = asdict(result)
    return jsonify(payload)


@app.post("/ask")
def ask():
    auth_error = _authorize()
    if auth_error is not None:
        return auth_error
    return _chat_impl()


@app.get("/history")
def history():
    auth_error = _authorize()
    if auth_error is not None:
        return auth_error
    return _history_impl()


@app.get("/health")
def health():
    auth_error = _authorize()
    if auth_error is not None:
        return auth_error
    return _health_impl()


def run() -> int:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    app.run(host=host, port=port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
