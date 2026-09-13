import pandas as pd
from pathlib import Path


def profile_csv(file_path: Path) -> dict:

    df = pd.read_csv(file_path)

    columns = []

    for column in df.columns:

        series = df[column]

        non_null = series.dropna()

        columns.append({
            "name": column,
            "dtype": str(series.dtype),
            "rows": len(series),
            "nulls": int(series.isna().sum()),
            "unique": int(series.nunique()),
            "samples": non_null.head(5).tolist()
        })

    return {
        "file": file_path.name,
        "rows": len(df),
        "columns": columns
    }