## Quick start

### 1. Get an API key

The pipeline uses [xKiro](https://xkiro.com) for the two LLM-powered
steps (reading amounts from images, and optionally rewriting the
explanation sentence). Everything else is pure Python and needs no
network access.

1. Go to **https://xkiro.com** and sign up — the Free tier gives you
   5,000,000 tokens/day with 40+ free models, no credit card required.
2. Open the dashboard → **API Keys** → **Create new key**.
3. Copy the key (it's shown only once) — it looks like `xk-...`.

### 2. Set up the project

```bash
# Install uv (if you don't have it)
pip install uv

# Create the environment
uv venv
.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate       # Linux/macOS

# Install dependencies
uv pip install -r requirements.txt
```

### 3. Configure the key

```bash
cp .env.example .env
```

Open `.env` and paste your key:

```env
# .env
API_KEY=xk-your-key-here
```

> **Note:** the code also accepts `OPENROUTER_API_KEY` as an alias for
> backwards compatibility. Either name works — the client always points
> at `https://api.xkiro.com/v1`.

Make sure `.env` is gitignored (it should be by default):

```bash
git check-ignore .env          # should print: .env
```

### 4. Load the dataset

```bash
python -m ingestion.loader
```

This reads every CSV under `dataset/` and populates the local SQLite
database (`DATABASE_PATH` in `config.py`).

### 5. Run the batch

```bash
python evaluation/main.py
```

Output lands at `dataset/output.csv` — 250 rows, one per request in
`dataset/requests.csv`. Runtime is ~13 seconds and makes **zero LLM
calls** on the deterministic path.

### 6. (Optional) Single-request test

```bash
python main.py request_19              # deterministic only
python main.py request_19 --llm        # with LLM-generated explanation
```

### 7. (Optional) Score against samples

```bash
python evaluate_samples.py
```

Prints per-field accuracy against the 25 labeled rows in
`sample_requests.csv`. Press `q` at any time to stop early.

---

## API reference

### `.env` variables

| Variable | Required | Purpose |
|----------|:--------:|---------|
| `API_KEY` | Required | API key for vision extraction and explanation rewriting.|

### Endpoint

The client is configured for:

```
base_url = "https://api.xkiro.com/v1"
```

which is OpenAI-SDK compatible. Any model available on xKiro can be
selected by changing the `MODEL` constant in `services/vision.py` or
`llm.py`. Defaults used in this submission:

| Purpose | Model |
|---------|-------|
| Vision (image → amount) | `mistralai/mistral-large-2512` |
| Explanation rewriting   | `mistralai/mistral-medium-3.5` |

Both are on the Free tier. To swap, set the `MODEL` constant — no other
code changes required.

### Cost

The submitted `dataset/output.csv` was produced with **0 LLM calls** —
see `evaluation/usage_report.md` for the full accounting. If you enable
the optional explanation pass (`evaluation/add_explanations.py`), the
full 250-row run costs under $0.05 at xKiro's pricing.