from __future__ import annotations

import os
from dataclasses import asdict

from flask import Flask, jsonify, render_template, request

from shared.client import get_client
from shared.config import PROVIDERS
from week_06.local_client import OllamaClientError
from week_06.workbench import DEFAULT_MODE, MODE_INSTRUCTIONS, WorkbenchService, local_providers

LOCAL_ENDPOINT = "http://localhost:11434/v1"
app = Flask(__name__, template_folder="templates")

_LOCAL_PROVIDERS = local_providers()
if not _LOCAL_PROVIDERS:
    raise RuntimeError("No local providers configured in shared/config.py")

_DEFAULT_PROVIDER = _LOCAL_PROVIDERS[0]
_services: dict[str, WorkbenchService] = {}


def _validate_provider(provider_name: str) -> str:
    if provider_name not in _LOCAL_PROVIDERS:
        raise ValueError(
            f"Unsupported provider: {provider_name}. Expected one of: {', '.join(_LOCAL_PROVIDERS)}"
        )
    return provider_name


def _get_service(provider_name: str) -> WorkbenchService:
    name = _validate_provider(provider_name)
    if name not in _services:
        _services[name] = WorkbenchService(provider_name=name)
    return _services[name]


@app.get("/")
def index():
    return render_template(
        "workbench.html",
        default_provider=_DEFAULT_PROVIDER,
        providers=_LOCAL_PROVIDERS,
        modes=[{"id": mode, "label": mode.replace("_", " ").title()} for mode in MODE_INSTRUCTIONS],
        endpoint=LOCAL_ENDPOINT,
    )


@app.get("/health")
def health():
    provider_name = request.args.get("provider", _DEFAULT_PROVIDER)
    try:
        provider_name = _validate_provider(provider_name)
        client, model_id = get_client(provider_name)
        client.models.list()
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "provider": provider_name,
                "endpoint": LOCAL_ENDPOINT,
                "error": str(exc),
            }
        )
    return jsonify(
        {
            "ok": True,
            "provider": provider_name,
            "model": model_id,
            "endpoint": PROVIDERS[provider_name].base_url,
        }
    )


@app.get("/history")
def history():
    provider_name = request.args.get("provider", _DEFAULT_PROVIDER)
    try:
        items = _get_service(provider_name).history()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"items": items})


@app.post("/ask")
def ask():
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    mode = str(payload.get("mode", DEFAULT_MODE)).strip() or DEFAULT_MODE
    provider_name = str(payload.get("provider", _DEFAULT_PROVIDER)).strip() or _DEFAULT_PROVIDER

    if not prompt:
        return jsonify({"error": "Prompt must not be empty"}), 400

    try:
        result = _get_service(provider_name).ask(mode=mode, prompt=prompt)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OllamaClientError as exc:
        message = (
            f"{exc}. Local model unavailable. Ensure Ollama is running "
            "(`ollama serve`)."
        )
        return (
            jsonify({"error": message}),
            502,
        )

    return jsonify(asdict(result))


def run() -> int:
    port = int(os.getenv("PORT", "8000"))
    app.run(host="127.0.0.1", port=port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
