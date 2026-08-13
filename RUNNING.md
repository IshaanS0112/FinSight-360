# Running FinSight 360

Two ways. **Path A (Docker)** is one command and runs everything. **Path B (manual)**
gives you hot reload and is what you want while writing code.

The project folder is:

```
/Users/ishaansingh/BASE/02-projects/FinSight360
```

---

## Step 0 — open a terminal in the right place

Open Terminal on your Mac and run:

```bash
cd ~/BASE/02-projects/FinSight360
```

Confirm you are in the right folder — you should see `backend`, `frontend`,
`data`, `docs`, `docker-compose.yml`:

```bash
ls
```

Everything below assumes you are in this folder unless a step says otherwise.

---

## Path A — Docker (easiest, run this first)

### A1. Check Docker is running

```bash
docker --version
docker compose version
```

If either errors, open Docker Desktop and wait until the whale icon in the menu
bar stops animating. If Docker Desktop is not installed, use **Path B** instead.

### A2. (Optional) add your Claude API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Skip this and everything still works. Without a key the written assessment comes
from the deterministic template fallback — **every ratio, Z-score and health score
is identical**, only the prose is missing. That fallback is deliberate, not a
degraded mode.

### A3. Start everything

```bash
docker compose up --build
```

First run takes 2–4 minutes (pulling Postgres, building two images). You are
ready when you see:

```
finsight360-backend-1   | INFO:     Application startup complete.
finsight360-backend-1   | INFO:     Uvicorn running on http://0.0.0.0:8000
```

Leave this terminal running. Open a **second terminal** for the next steps.

### A4. Load the three real companies

In the second terminal:

```bash
cd ~/BASE/02-projects/FinSight360
python3 backend/scripts/load_sample_filings.py
```

### A5. Open it

- Dashboard → <http://localhost:5173>
- API docs → <http://localhost:8000/docs>
- Methodology → <http://localhost:8000/methodology>

### A6. Stop it

`Ctrl+C` in the first terminal, then:

```bash
docker compose down          # stop
docker compose down -v       # stop AND wipe the database
```

---

## Path B — manual (no Docker, hot reload)

You need **two terminals**, both in the project folder.

### B1. Check your Python version

```bash
python3 --version
```

Must be **3.10 or higher**. If it says 3.9 or lower:

```bash
brew install python@3.12
```

...then use `python3.12` everywhere below instead of `python3`.

### B2. Terminal 1 — backend

```bash
cd ~/BASE/02-projects/FinSight360/backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

The default config points at Postgres. To run without it, use SQLite:

```bash
export DATABASE_URL="sqlite:///./finsight.db"
export ANTHROPIC_API_KEY=""        # or your real key

uvicorn app.main:app --reload --port 8000
```

You are ready when you see `Application startup complete.` Leave this running.

> **Note:** SQLite is fine for local development and is what the test suite uses.
> Postgres is the deployment target. Nothing in the analysis differs — the models
> declare JSONB and UUID as dialect variants so the same schema loads on both.

### B3. Terminal 2 — frontend

```bash
cd ~/BASE/02-projects/FinSight360/frontend

npm install
npm run dev
```

You are ready when you see `Local: http://localhost:5173/`. Leave this running.

> If `npm` is not found: `brew install node`

### B4. Terminal 3 (or reuse terminal 2 after backgrounding) — load the data

```bash
cd ~/BASE/02-projects/FinSight360
python3 backend/scripts/load_sample_filings.py
```

---

## Checking it actually works

Run these in order. Each one tells you something different.

### Check 1 — the test suite (no server needed)

This is the fastest and most complete check. It needs **no database and no
running server**.

```bash
cd ~/BASE/02-projects/FinSight360/backend
python3 -m pytest -q
```

**Expected:**

```
88 passed in 0.9s
```

If this passes, every analytical claim the project makes is verified: the ratio
arithmetic, the published Altman coefficients, the model-selection logic, the
sector refusal, the missing-input handling, and the full HTTP contract.

### Check 2 — the API is up

```bash
curl http://localhost:8000/health
```

**Expected:** `{"status":"ok"}`

If you get `Connection refused`, the backend is not running — go back to A3 or B2.

### Check 3 — the sample data loads and the validation passes

```bash
cd ~/BASE/02-projects/FinSight360
python3 backend/scripts/load_sample_filings.py
```

**Expected — the three `OK` lines are the validation result:**

```
Loading 3 sample filing(s) into http://localhost:8000
  OK Caterpillar Inc.: Z_1968 = 3.9203 -> SAFE (expected SAFE, confidence COMPLETE), health 63.81, narrative by template_fallback
  OK Infosys Limited: Z_DOUBLE_PRIME = 8.6494 -> SAFE (expected SAFE, confidence COMPLETE), health 65.11, narrative by template_fallback
  OK Vodafone Idea Limited: Z_DOUBLE_PRIME = -5.9633 -> DISTRESS (expected DISTRESS, confidence PARTIAL), health 12.97, narrative by template_fallback
     omitted components: ['x3']
```

**What to look at:**

- `OK` on every line — each company landed in the zone its real-world outcome
  says it should. A `!!` would mean a mismatch.
- Caterpillar gets `Z_1968`, the other two get `Z_DOUBLE_PRIME` — **the model
  selection is working.** Caterpillar is a manufacturer; Infosys and Vodafone Idea
  are not.
- Vodafone Idea says `confidence PARTIAL` and `omitted components: ['x3']` — its
  EBIT genuinely is not in the source data, so the engine reports a four-term
  partial sum rather than inventing a number. **That is correct behaviour, not a
  bug.**

Re-running is safe — companies already loaded are skipped, not duplicated.

### Check 4 — the UI

Open <http://localhost:5173>. You should see three companies. Click **Caterpillar
Inc.** and confirm:

- A **Z-score gauge** reading 3.9203, marked `SAFE`, on a green/amber/red bar
- A **component table** showing x1–x5 with each ratio, its coefficient, and its
  contribution. The five contributions sum to 3.9203.
- A **ratio dashboard** with all four categories filled and no omissions
- A **health score** with the line "Project-defined composite, not an established
  model" above it
- An assessment panel with a `template fallback` chip (or `LLM narration` if you
  set an API key)

Now click **Vodafone Idea Limited**. This is the more interesting one:

- Score **−5.9633**, marked `DISTRESS`
- An amber warning that the score is a partial sum
- A block listing **x3 omitted — ebit (operating income) not reported**
- Under "5 ratios not computed": **ROE is absent** with the reason
  "shareholder_equity is zero or negative; ROE is undefined here"

That last point is the thing to understand before an interview. Vodafone Idea's
ROE would naively compute to **+29.99%** — a ₹312bn loss divided by negative
equity. It reads like excellent performance. The engine refuses to report it.

### Check 5 — the methodology endpoint

```bash
curl -s http://localhost:8000/methodology | python3 -m json.tool | head -40
```

This returns every coefficient, cutoff and weight the running service is actually
using. It exists so the claim "these numbers are computed, not generated" is
checkable without reading the source. Also visible in the UI at
<http://localhost:5173/methodology>.

### Check 6 — the sector refusal

Prove the model refuses to score a bank:

```bash
curl -s -X POST http://localhost:8000/companies \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test Bank Ltd","industry":"banking","sector_class":"FINANCIAL",
       "fiscal_year":2024,"currency":"USD","units":"MILLIONS",
       "data_source":"manual test"}'
```

Copy the `id` from the response, then:

```bash
COMPANY_ID=<paste-the-id-here>

curl -s -X POST "http://localhost:8000/companies/$COMPANY_ID/financial-statements" \
  -H 'Content-Type: application/json' \
  -d '{"statement_type":"BALANCE_SHEET",
       "line_items":{"total_assets":1000,"total_liabilities":900,
                     "shareholder_equity":100,"retained_earnings":50,
                     "current_assets":400,"current_liabilities":300}}'

curl -s -X POST "http://localhost:8000/companies/$COMPANY_ID/compute-bankruptcy-risk" \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
```

**Expected:** `"altman_z_score": null`, `"zone": "NOT_APPLICABLE"`, and a
`model_selection` field explaining that Altman excluded financial-sector issuers
from every estimation sample.

### Check 7 — the balance-sheet guard

Try to upload a balance sheet with a dropped digit:

```bash
curl -s -X POST "http://localhost:8000/companies/$COMPANY_ID/financial-statements" \
  -H 'Content-Type: application/json' \
  -d '{"statement_type":"BALANCE_SHEET",
       "line_items":{"total_assets":1000,"total_liabilities":900,
                     "shareholder_equity":10}}'
```

**Expected:** HTTP 422 with a message naming the residual and saying it is almost
always a transcription error.

---

## The 30-second version

```bash
cd ~/BASE/02-projects/FinSight360
docker compose up --build          # terminal 1, wait for "startup complete"

# terminal 2:
cd ~/BASE/02-projects/FinSight360
python3 backend/scripts/load_sample_filings.py    # expect 3x "OK"
cd backend && python3 -m pytest -q                # expect "88 passed"
open http://localhost:5173
```

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Connection refused` on port 8000 | Backend not running. Docker: check terminal 1 for errors. Manual: is the venv activated? |
| `Cannot reach http://localhost:8000` from the loader script | Same — start the backend first. |
| `docker: command not found` | Docker Desktop is not installed or not running. Use Path B. |
| `port is already allocated` | Something else is on 8000/5173/5432. Find it: `lsof -i :8000`, then `kill <PID>`. |
| `npm: command not found` | `brew install node` |
| `ModuleNotFoundError: No module named 'fastapi'` | Virtualenv not activated. `source .venv/bin/activate` |
| `SyntaxError` on `X \| None` | Python 3.9 or older. Needs 3.10+. `brew install python@3.12` |
| Frontend loads but shows "Could not reach the API" | Backend is down, or you started the frontend without the Vite proxy. Confirm `curl localhost:8000/health` works. |
| `You installed esbuild for another platform` | `rm -rf frontend/node_modules && cd frontend && npm install` |
| Tests pass but the UI is empty | You never ran the loader. `python3 backend/scripts/load_sample_filings.py` |
| Assessment says `template fallback` | Expected without `ANTHROPIC_API_KEY`. Every number is identical either way; only the prose is missing. |
| Postgres data is stale or wrong | `docker compose down -v` wipes the volume, then `docker compose up --build`. |

---

## Pushing to GitHub

Once the checks above pass:

```bash
cd ~/BASE/02-projects/FinSight360
gh auth login          # once, if you have not already
./PUSH_TO_GITHUB.sh
```

The script runs the test suite **first** and refuses to push if anything fails.
No `gh` CLI? The script's last comment block has the manual git commands.
