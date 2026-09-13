# config.py
from pathlib import Path


# Where config.py itself lives: .../code/
CODE_DIR = Path(__file__).resolve().parent

# Repo root: .../hackerrank-orchestrate-september26/
PROJECT_ROOT = CODE_DIR.parent

# Competition dataset (lives at repo root)
DATASET_DIR = PROJECT_ROOT / "dataset"

# Generated application data (lives inside code/)
DATA_DIR = CODE_DIR / "data"

# SQLite database
DATABASE_PATH = DATA_DIR / "financial_agent.db"

# Ensure the data directory exists on import
DATA_DIR.mkdir(parents=True, exist_ok=True)