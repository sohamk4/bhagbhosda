import sqlite3
from pathlib import Path


def create_connection(database_path: Path) -> sqlite3.Connection:

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        database_path,
        check_same_thread=False,
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    connection.execute(
        "PRAGMA journal_mode = WAL"
    )

    connection.execute(
        "PRAGMA synchronous = NORMAL"
    )

    connection.execute(
        "PRAGMA temp_store = MEMORY"
    )

    return connection