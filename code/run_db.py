from database import create_connection
from config import DATASET_DIR, DATABASE_PATH
from ingestion.scanner import find_csv_files
from ingestion.profiler import profile_csv
from ingestion.loader import load_csv
from ingestion.relationships import (
    create_indexes,
    validate_relationships,
    print_relationships,
)


def reset_database():
    """
    Delete the previous generated database.

    The CSV dataset is the source of truth.
    """

    if DATABASE_PATH.exists():
        print("\nRemoving existing database...")
        DATABASE_PATH.unlink()

    # Remove SQLite WAL/SHM files if they exist.
    wal_file = DATABASE_PATH.with_name(
        DATABASE_PATH.name + "-wal"
    )

    shm_file = DATABASE_PATH.with_name(
        DATABASE_PATH.name + "-shm"
    )

    if wal_file.exists():
        wal_file.unlink()

    if shm_file.exists():
        shm_file.unlink()


def print_database_schema(connection):
    print("\nDATABASE SCHEMA")
    print("=" * 60)

    tables = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
        """
    ).fetchall()

    for (table_name,) in tables:

        print(f"\nTABLE: {table_name}")

        columns = connection.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()

        for column in columns:
            (
                _cid,
                name,
                data_type,
                not_null,
                default_value,
                primary_key,
            ) = column

            print(
                f"  {name:<35}"
                f"{data_type:<10}"
                f"PK={bool(primary_key)}"
            )


def verify_row_counts(
    connection,
    expected_counts,
):
    print("\nROW COUNT VERIFICATION")
    print("=" * 60)

    for table_name, expected_count in expected_counts.items():

        actual_count = connection.execute(
            f'SELECT COUNT(*) FROM "{table_name}"'
        ).fetchone()[0]

        status = "OK" if (
            actual_count == expected_count
        ) else "ERROR"

        print(
            f"{table_name:<30}"
            f"expected={expected_count:<8}"
            f"actual={actual_count:<8}"
            f"{status}"
        )

        if actual_count != expected_count:
            raise RuntimeError(
                f"Row count mismatch for {table_name}: "
                f"expected {expected_count}, "
                f"got {actual_count}"
            )


def main():

    print("=" * 60)
    print("Financial Agent - Dataset Ingestion")
    print("=" * 60)

    print(f"\nDataset: {DATASET_DIR}")
    print(f"Database: {DATABASE_PATH}")

    if not DATASET_DIR.exists():
        raise RuntimeError(
            f"Dataset directory does not exist: "
            f"{DATASET_DIR}"
        )

    csv_files = find_csv_files(
        DATASET_DIR
    )

    print(
        f"\nFound {len(csv_files)} CSV files"
    )

    if not csv_files:
        raise RuntimeError(
            "No CSV files found."
        )

    # --------------------------------------------------
    # 1. Reset
    # --------------------------------------------------

    reset_database()

    # --------------------------------------------------
    # 2. Create fresh database
    # --------------------------------------------------

    connection = create_connection(
        DATABASE_PATH
    )

    expected_counts = {}

    try:

        # --------------------------------------------------
        # 3. Load CSV files
        # --------------------------------------------------

        for file_path in csv_files:

            print(
                f"\nLoading: {file_path.name}"
            )

            profile = profile_csv(
                file_path
            )

            print(
                f"  Rows: {profile['rows']}"
            )

            result = load_csv(
                connection,
                file_path,
            )

            expected_counts[
                result["table"]
            ] = result["rows"]

            print(
                f"  Table: {result['table']}"
            )

            print(
                f"  Columns: {result['columns']}"
            )

            print(
                f"  ✓ Loaded {result['rows']} rows"
            )

        # --------------------------------------------------
        # 4. Create indexes
        # --------------------------------------------------

        print("\nCreating indexes...")

        create_indexes(
            connection
        )

        print("✓ Indexes created")

        # --------------------------------------------------
        # 5. Validate row counts
        # --------------------------------------------------

        verify_row_counts(
            connection,
            expected_counts,
        )

        # --------------------------------------------------
        # 6. Validate relationships
        # --------------------------------------------------

        print_relationships()

        validate_relationships(
            connection
        )

        # --------------------------------------------------
        # 7. Print schema
        # --------------------------------------------------

        print_database_schema(
            connection
        )

        # --------------------------------------------------
        # 8. Final verification
        # --------------------------------------------------

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        print(
            "\nDATABASE INTEGRITY"
        )
        print("=" * 60)
        print(
            f"SQLite integrity check: {integrity}"
        )

        if integrity != "ok":
            raise RuntimeError(
                f"SQLite integrity check failed: "
                f"{integrity}"
            )

        print("\n" + "=" * 60)
        print("DATABASE READY")
        print("=" * 60)

        print(
            f"\nSQLite database:\n"
            f"{DATABASE_PATH}"
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()