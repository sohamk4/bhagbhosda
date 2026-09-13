from pathlib import Path


# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Competition dataset
DATASET_DIR = PROJECT_ROOT / "dataset"

# Generated application data
DATA_DIR = PROJECT_ROOT / "data"

# SQLite database
DATABASE_PATH = DATA_DIR / "financial_agent.db"