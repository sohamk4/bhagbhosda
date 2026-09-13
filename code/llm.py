import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_FILE)


def create_llm():

    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            f"OPENROUTER_API_KEY not found. "
            f"Checked: {ENV_FILE}"
        )

    return ChatOpenAI(
        model="mistralai/mistral-medium-3.5",
        api_key=api_key,
        base_url="https://api.xkiro.com/v1",
        temperature=0,
        max_tokens=4096,
        max_retries=3,
    )