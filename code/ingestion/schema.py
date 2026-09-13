import re
import pandas as pd


DATE_COLUMN_PATTERNS = (
    "_date",
    "_at",
    "date",
)


INTEGER_COLUMNS = {
    "allows_partial_payment",
    "number_of_payments",
    "payment_frequency_days",
    "minimum_balance_to_keep",
    "max_installment_months",
}


def clean_column_name(name: str) -> str:
    name = str(name).strip().lower()

    name = re.sub(r"[^a-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")

    if not name:
        name = "column"

    if name[0].isdigit():
        name = "_" + name

    return name


def infer_sqlite_type(series: pd.Series, column_name: str) -> str:
    """
    Deterministic SQLite type inference.

    We intentionally do NOT attempt generic datetime inference because
    pandas can produce ambiguous date parsing warnings and inconsistent
    behavior across datasets.
    """

    column_name = column_name.lower()

    if column_name in INTEGER_COLUMNS:
        return "INTEGER"

    if any(
        column_name == pattern
        or column_name.endswith(pattern)
        for pattern in DATE_COLUMN_PATTERNS
    ):
        return "TEXT"

    non_null = series.dropna()

    if len(non_null) == 0:
        return "TEXT"

    values = {
        str(value).strip().lower()
        for value in non_null
    }

    if values.issubset({"true", "false", "yes", "no"}):
        return "INTEGER"

    numeric = pd.to_numeric(non_null, errors="coerce")

    if numeric.notna().all():
        if (numeric % 1 == 0).all():
            return "INTEGER"

        return "REAL"

    return "TEXT"


def infer_schema(df: pd.DataFrame) -> list[dict]:
    schema = []

    used_names = set()

    for original_name in df.columns:
        clean_name = clean_column_name(original_name)

        # Protect against two source columns becoming the same
        # cleaned name.
        base_name = clean_name
        counter = 2

        while clean_name in used_names:
            clean_name = f"{base_name}_{counter}"
            counter += 1

        used_names.add(clean_name)

        sqlite_type = infer_sqlite_type(
            df[original_name],
            clean_name,
        )

        schema.append(
            {
                "original_name": original_name,
                "name": clean_name,
                "type": sqlite_type,
            }
        )

    return schema