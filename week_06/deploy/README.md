# Day 30 VPS Deploy (native, CPU-only)

This deploy keeps Ollama private on localhost and exposes only the Flask service.

## 1) Pick a VPS size

- Recommended for stable demo with `qwen2.5:3b`: **4 vCPU / 8 GB RAM**
- Minimal (works but slower/riskier): **2 vCPU / 4 GB RAM**
- `qwen2.5-coder:3b` is kept as the code-focused provider.
- `7b` on cheap CPU VPS is usually too slow for a live demo and is optional only.

## 2) Install base packages

```bash
sudo apt update
sudo apt install -y curl git ca-certificates
```

## 3) Install Ollama and pull model

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b
ollama pull qwen2.5-coder:3b
```

Check:

```bash
ollama list
```

## 4) Install uv and clone project

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
git clone <your-repo-url> /opt/ai-advent-challenge-8
cd /opt/ai-advent-challenge-8
uv sync
```

## 5) Run service manually (smoke)

```bash
export PRIVATE_LLM_API_KEY=change-me
export LLM_PROVIDER="Qwen2.5 3B (Ollama, local)"
export HOST=127.0.0.1
export PORT=8000
export MAX_PROMPT_CHARS=4000
export RATE_LIMIT_PER_MIN=10
export LLM_TEMPERATURE=0.2
export LLM_TOP_P=0.9
export LLM_MAX_TOKENS=220

uv run python -m week_06.web_app
```

In another shell:

```bash
curl http://127.0.0.1:8000/api/health \
  -H "Authorization: Bearer $PRIVATE_LLM_API_KEY"
```

## 6) Install systemd service

Copy `week_06/deploy/private-llm.service` to `/etc/systemd/system/private-llm.service`
and adjust:

- `WorkingDirectory`
- `Environment=PRIVATE_LLM_API_KEY=...`
- user/group if needed

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now private-llm
sudo systemctl status private-llm --no-pager
```

Ollama service should also be enabled:

```bash
sudo systemctl enable --now ollama
sudo systemctl status ollama --no-pager
```

## 7) Expose service

### Option A: direct public IP (quick demo)

Keep app on `0.0.0.0:8000` and open port 8000 in firewall/security group.

### Option B (recommended): Caddy reverse proxy + HTTPS

Use `week_06/deploy/Caddyfile`, then:

```bash
sudo apt install -y caddy
sudo cp week_06/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

Set app back to `HOST=127.0.0.1`, keep only Caddy public.

## 8) Verify from outside

Health:

```bash
curl https://your-domain.example.com/api/health \
  -H "Authorization: Bearer change-me"
```

Chat:

```bash
curl https://your-domain.example.com/api/chat \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"mode":"general","prompt":"Коротко объясни, что такое локальная LLM"}'
```

Rate limit (expect some `429`):

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    https://your-domain.example.com/api/health \
    -H "Authorization: Bearer change-me"
done
```

Max prompt check (expect `413`):

```bash
python - <<'PY'
import requests
url = "https://your-domain.example.com/api/chat"
headers = {"Authorization": "Bearer change-me"}
payload = {"mode": "general", "prompt": "x" * 5000}
r = requests.post(url, headers=headers, json=payload, timeout=60)
print(r.status_code)
print(r.text)
PY
```

## Security notes

- Keep Ollama private (`127.0.0.1:11434`), do not expose it directly.
- Expose only Flask/Caddy.
- Use a strong `PRIVATE_LLM_API_KEY`.
- Rotate key if shared publicly in demo messages.
