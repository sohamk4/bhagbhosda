import sqlite3
import pandas as pd

from .schema import infer_schema


PRIMARY_KEYS = {
    "exchange_rates": [],
    "financial_events": ["event_id"],
    "financial_profiles": ["user_id"],
    "images": ["image_id"],
    "messages": ["message_id"],
    "request_payment_options": ["payment_option_id"],
    "requests": ["request_id"],
    "sample_requests": ["request_id"],
}


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize CSV values before inserting into SQLite.
    """

    df = df.copy()

    for column in df.columns:
        # Convert empty strings / whitespace-only strings to NULL.
        if df[column].dtype == object:
            df[column] = df[column].apply(
                lambda value: (
                    None
                    if pd.isna(value)
                    or str(value).strip() == ""
                    else str(value).strip()
                )
            )

    return df


def create_table(
    connection: sqlite3.Connection,
    table_name: str,
    schema: list[dict],
):
    primary_keys = PRIMARY_KEYS.get(table_name, [])

    columns = []

    for column in schema:
        name = column["name"]
        sqlite_type = column["type"]

        definition = (
            f"{quote_identifier(name)} "
            f"{sqlite_type}"
        )

        columns.append(definition)

    if primary_keys:
        pk_columns = ", ".join(
            quote_identifier(column)
            for column in primary_keys
        )

        columns.append(
            f"PRIMARY KEY ({pk_columns})"
        )

    sql = f"""
        CREATE TABLE {quote_identifier(table_name)}
        (
            {", ".join(columns)}
        )
    """

    connection.execute(sql)


def validate_primary_key(
    df: pd.DataFrame,
    table_name: str,
):
    primary_keys = PRIMARY_KEYS.get(table_name, [])

    if not primary_keys:
        return

    missing_columns = [
        column
        for column in primary_keys
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"{table_name}: primary key columns missing: "
            f"{missing_columns}"
        )

    if df[primary_keys].isna().any().any():
        raise ValueError(
            f"{table_name}: NULL found in primary key"
        )

    duplicate_count = int(
        df.duplicated(
            subset=primary_keys
        ).sum()
    )

    if duplicate_count > 0:
        raise ValueError(
            f"{table_name}: "
            f"{duplicate_count} duplicate primary key rows found"
        )


def load_csv(
    connection: sqlite3.Connection,
    file_path,
):
    df = pd.read_csv(
        file_path,
        keep_default_na=True,
    )

    schema = infer_schema(df)

    rename_map = {
        item["original_name"]: item["name"]
        for item in schema
    }

    df = df.rename(columns=rename_map)

    df = normalize_dataframe(df)

    table_name = file_path.stem.lower()

    validate_primary_key(
        df,
        table_name,
    )

    create_table(
        connection,
        table_name,
        schema,
    )

    # Since the database itself is freshly created, append is safe.
    # It also preserves the explicitly created schema and PKs.
    df.to_sql(
        table_name,
        connection,
        if_exists="append",
        index=False,
    )

    return {
        "table": table_name,
        "rows": len(df),
        "columns": len(df.columns),
        "schema": schema,
    }