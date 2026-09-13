# Buy or Wait? — AI-Powered Financial Affordability Agent

A deterministic financial decision engine that answers the question:
**"Can I afford this?"**

Given a user's request, profile, transaction history, and payment options,
the system produces the safest recommendation — pay in full, pay partially,
use installments, wait, or don't proceed — with a complete payment plan and
a one-sentence explanation.

---

## Quick start

```bash
# 1. Install uv (if you don't have it)
pip install uv

# 2. Create the environment
uv venv
.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate       # Linux/macOS

# 3. Install dependencies
uv pip install -r requirements.txt

# 4. Configure the API key (only needed for vision / LLM explanations)
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY=...

# 5. Load the dataset into SQLite
python -m ingestion.loader

# 6. Run the batch
python evaluation/main.py

# Output: dataset/output.csv