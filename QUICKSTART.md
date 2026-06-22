# Quick start

Get the retail kiosk running on a **display PC** and an **Arduino UNO Q** on the same Wi‑Fi network.

---

## Prerequisites

| Machine | Role | What to install |
|---------|------|-----------------|
| **Display PC** | React UI + `retail-kiosk-api` | Python 3.10+, Node.js 18+, `pip install .` from this repo |
| **Arduino UNO Q** | Moorcheh Edge + Ollama + voice | Python venv, `pip install moorcheh-edge`, Docker |

**Hardware (mic, speaker, wiring):** [Retail Kiosk with Moorcheh (Figma)](https://www.figma.com/board/YiBj2eVpuqvkqL2RNyDmp2/Retail-Kiosk-with-Moorcheh?node-id=17-113&t=LmeUJtEsBJ6TDGrI-0)

On the UNO Q, create a Python venv and activate it in every new shell:

```bash
source ~/moorcheh-venv/bin/activate
```

If you develop from the **moorcheh-edge-private** monorepo, install the client on the board with `pip install -e ~/moorcheh-edge-client` after SCP (see your board deploy guide).

---

## Ports

| Port | Machine | Service |
|------|---------|---------|
| **5173** | PC | React UI (`npm run dev`) |
| **8765** | PC | `retail-kiosk-api` — browser always talks here |
| **8766** | Arduino UNO Q | `moorcheh-edge voice serve` |
| **8080** | Arduino UNO Q | Moorcheh Edge (Docker) — search + RAG |
| **11434** | Arduino UNO Q | Ollama (host) |

The browser never talks to the UNO Q directly. The PC API uses `MOORCHEH_EDGE_URL` and `MOORCHEH_VOICE_PROXY_URL` to reach the board.

---

## Configuration

| Variable | Where | Description |
|----------|-------|-------------|
| `MOORCHEH_EDGE_URL` | PC API | Moorcheh Edge on UNO Q (e.g. `http://192.168.1.50:8080`) |
| `MOORCHEH_VOICE_PROXY_URL` | PC API | Voice server on UNO Q (e.g. `http://192.168.1.50:8766`) |
| `VITE_API_URL` | Frontend | PC API URL (e.g. `http://127.0.0.1:8765`) |

---

## 1. Arduino UNO Q — connect and install (once)

**Find the board IP:** Wi‑Fi connected → **Arduino App Lab** → **Settings** (left corner) → **Network Connections**.

**SSH from the PC:**

```bash
ssh arduino@<UNO_Q_IP>
```

Example: `ssh arduino@10.0.0.196`

Install once (Debian needs a **venv**, PEP 668):

```bash
sudo apt-get update && sudo apt-get install -y python3-venv curl zstd
python3 -m venv ~/moorcheh-venv
source ~/moorcheh-venv/bin/activate
pip install moorcheh-edge
docker version   # must work
```

---

## 2. Arduino UNO Q — every session

**Terminal 1 — RAG + Ollama:**

```bash
source ~/moorcheh-venv/bin/activate
moorcheh-edge up --with-llm --warm-llm -y
moorcheh-edge status
```

If **`embedding_model`** and **`dimension`** are `null`, that is normal until catalog upload (step 6).

**Voice — once per board** (after first successful `up`): `voice setup`, `voice check`, `voice cache-holding`. See [moorcheh-edge voice docs](https://github.com/moorcheh-ai/moorcheh-edge) or your CLI help.

**Terminal 2 — voice server (required for mic/speaker):**

```bash
source ~/moorcheh-venv/bin/activate
moorcheh-edge voice serve --port 8766
```

---

## 3. Display PC — install (once)

```bash
git clone https://github.com/moorcheh-ai/retail-kiosk.git
cd retail-kiosk
pip install .
cd frontend && npm install
```

Monorepo:

```powershell
pip install -e ".\moorcheh-edge-client"
pip install -e ".\retail-kiosk"
cd retail-kiosk\frontend ; npm install
```

---

## 4. Display PC — run (two terminals)

Use `<UNO_Q_IP>` from step 1 (no trailing dot).

**Terminal 1 — API:**

```powershell
$env:MOORCHEH_EDGE_URL = "http://<UNO_Q_IP>:8080"
$env:MOORCHEH_VOICE_PROXY_URL = "http://<UNO_Q_IP>:8766"
retail-kiosk-api
```

**Terminal 2 — UI:**

```powershell
cd frontend
$env:VITE_API_URL = "http://127.0.0.1:8765"
npm run dev
```

- **Customer:** http://localhost:5173/
- **Admin:** http://localhost:5173/admin

---

## 5. Verify

**UNO Q:**

```bash
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8766/health
```

**PC:**

```bash
curl -s http://127.0.0.1:8765/health
```

Expect `"status":"ok"`, `"edge_url"` → UNO Q, `"voice_proxy_url"` set.

---

## 6. Load demo catalog on UNO Q (required before Customer)

`moorcheh-edge up` must be running.

**From the PC** (in `retail-kiosk`):

```powershell
scp tests/brew-corner-catalog.json arduino@<UNO_Q_IP>:~/
scp tests/upload-catalog-to-edge.py arduino@<UNO_Q_IP>:~/
```

**On the UNO Q:**

```bash
source ~/moorcheh-venv/bin/activate
python ~/upload-catalog-to-edge.py --catalog ~/brew-corner-catalog.json -y
```

Use `--clear -y` to replace an existing catalog. Then `moorcheh-edge status` should show **`dimension`** and **`embedding_model`** set.

**On the PC:** open **Admin → Prompts** if you want to customize header/footer (defaults work for The Brew Corner).

---

## 7. Try the kiosk

1. **Text:** type a question → **Send** → streaming answer.
2. **Voice:** mic → speak → answer on screen + UNO Q speaker.

---

## What Admin and Customer do today

### Admin (PC)

- **Prompts** — edit header/footer LLM instructions (stored in SQLite on PC, sent with each question)
- **Voice settings** — store name, holding message (optional)
- **Documents** — manual add/edit forms exist; **demo catalog uses the UNO Q upload script instead** (no JSON import button yet)

### Customer (PC UI → UNO Q AI)

- Multi-turn chat (history on PC, max 4 customer questions per conversation)
- **Text** — streamed tokens from Moorcheh Edge on the UNO Q
- **Voice** — mic and speaker on the UNO Q via voice proxy

---

## Demo catalog files

| File | Purpose |
|------|---------|
| `tests/brew-corner-catalog.json` | Demo store documents + prompts (The Brew Corner) |
| `tests/upload-catalog-to-edge.py` | Embed on UNO Q and upload chunks to Moorcheh Edge `:8080` |
| `data/brew-corner/` | Extended catalog dataset and seeding notes |

---

## Tests

```bash
pip install ".[dev]"
pytest -q
```

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---------|----------------|------------|
| Empty or wrong answers | No catalog on UNO Q | Run step 6 (`upload-catalog-to-edge.py`) |
| `LLM request failed` | Ollama slow or overloaded | On UNO Q: `ollama ps`; ask one question at a time |
| Stream stops with no answer | `voice serve` down or env unset | Restart `:8766`; check PC `/health` |
| `getaddrinfo failed` | Trailing dot on IP | Use `10.0.0.196` not `10.0.0.196.` |
| Voice mic does nothing | Proxy not configured | Set `MOORCHEH_VOICE_PROXY_URL`; start `voice serve` |
| `pip install` fails on Windows | API still running | Stop `retail-kiosk-api`, then reinstall |
