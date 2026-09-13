import sqlite3


SEMANTIC_RELATIONSHIPS = [
    # --------------------------------------------------
    # User -> Profile
    # --------------------------------------------------

    {
        "from_table": "requests",
        "from_column": "user_id",
        "to_table": "financial_profiles",
        "to_column": "user_id",
    },
    {
        "from_table": "financial_events",
        "from_column": "user_id",
        "to_table": "financial_profiles",
        "to_column": "user_id",
    },
    {
        "from_table": "messages",
        "from_column": "user_id",
        "to_table": "financial_profiles",
        "to_column": "user_id",
    },
    {
        "from_table": "images",
        "from_column": "user_id",
        "to_table": "financial_profiles",
        "to_column": "user_id",
    },

    # --------------------------------------------------
    # Request -> User
    # --------------------------------------------------

    {
        "from_table": "messages",
        "from_column": "request_id",
        "to_tables": [
            "requests",
            "sample_requests",
        ],
        "to_column": "request_id",
    },
    {
        "from_table": "images",
        "from_column": "request_id",
        "to_tables": [
            "requests",
            "sample_requests",
        ],
        "to_column": "request_id",
    },
    {
        "from_table": "request_payment_options",
        "from_column": "request_id",
        "to_tables": [
            "requests",
            "sample_requests",
        ],
        "to_column": "request_id",
    },

    # --------------------------------------------------
    # Message/Image -> Financial Event
    # --------------------------------------------------

    {
        "from_table": "messages",
        "from_column": "related_event_id",
        "to_tables": [
            "financial_events",
        ],
        "to_column": "event_id",
    },
    {
        "from_table": "images",
        "from_column": "related_event_id",
        "to_tables": [
            "financial_events",
        ],
        "to_column": "event_id",
    },

    # --------------------------------------------------
    # Financial Event -> Financial Event
    # --------------------------------------------------

    {
        "from_table": "financial_events",
        "from_column": "linked_event_id",
        "to_tables": [
            "financial_events",
        ],
        "to_column": "event_id",
    },
]


INDEX_COLUMNS = {
    "exchange_rates": [
        "rate_date",
        "from_currency",
        "to_currency",
    ],

    "financial_events": [
        "event_id",
        "user_id",
        "event_date",
        "settlement_date",
        "status",
        "linked_event_id",
    ],

    "financial_profiles": [
        "user_id",
    ],

    "images": [
        "image_id",
        "user_id",
        "request_id",
        "related_event_id",
    ],

    "messages": [
        "message_id",
        "user_id",
        "request_id",
        "related_event_id",
        "sent_at",
    ],

    "request_payment_options": [
        "payment_option_id",
        "request_id",
        "payment_method",
        "first_payment_date",
    ],

    "requests": [
        "request_id",
        "user_id",
        "request_date",
        "desired_completion_date",
    ],

    "sample_requests": [
        "request_id",
        "user_id",
    ],
}


def table_exists(
    connection: sqlite3.Connection,
    table_name: str,
) -> bool:

    result = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return result is not None


def column_exists(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:

    rows = connection.execute(
        f'PRAGMA table_info("{table_name}")'
    ).fetchall()

    return any(
        row[1] == column_name
        for row in rows
    )


def create_indexes(
    connection: sqlite3.Connection,
):
    for table_name, columns in INDEX_COLUMNS.items():

        if not table_exists(
            connection,
            table_name,
        ):
            continue

        for column in columns:

            if not column_exists(
                connection,
                table_name,
                column,
            ):
                continue

            index_name = (
                f"idx_{table_name}_{column}"
            )

            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                "{index_name}"
                ON "{table_name}"
                ("{column}")
                """
            )

    connection.commit()


def validate_relationship(
    connection: sqlite3.Connection,
    relationship: dict,
):
    from_table = relationship["from_table"]
    from_column = relationship["from_column"]

    if "to_tables" in relationship:
        to_tables = relationship["to_tables"]
    else:
        to_tables = [relationship["to_table"]]

    to_column = relationship["to_column"]

    if not table_exists(
        connection,
        from_table,
    ):
        return None

    if not column_exists(
        connection,
        from_table,
        from_column,
    ):
        return None

    existing_targets = [
        table
        for table in to_tables
        if table_exists(
            connection,
            table,
        )
        and column_exists(
            connection,
            table,
            to_column,
        )
    ]

    if not existing_targets:
        return None

    # Build a UNION containing every valid target table.
    target_queries = []

    for table in existing_targets:
        target_queries.append(
            f"""
            SELECT "{to_column}" AS target_id
            FROM "{table}"
            WHERE "{to_column}" IS NOT NULL
            """
        )

    target_union = "\nUNION\n".join(
        target_queries
    )

    sql = f"""
        SELECT COUNT(*)
        FROM "{from_table}" source
        LEFT JOIN (
            {target_union}
        ) targets
            ON source."{from_column}"
             = targets.target_id
        WHERE source."{from_column}" IS NOT NULL
          AND targets.target_id IS NULL
    """

    return connection.execute(
        sql
    ).fetchone()[0]


def validate_relationships(
    connection: sqlite3.Connection,
):
    print("\nRELATIONSHIP VALIDATION")
    print("=" * 60)

    for relationship in SEMANTIC_RELATIONSHIPS:

        orphan_count = validate_relationship(
            connection,
            relationship,
        )

        if orphan_count is None:
            continue

        from_table = relationship["from_table"]
        from_column = relationship["from_column"]

        if "to_tables" in relationship:
            to_tables = relationship["to_tables"]
        else:
            to_tables = [relationship["to_table"]]

        to_column = relationship["to_column"]

        target_description = " OR ".join(
            f"{table}.{to_column}"
            for table in to_tables
        )

        print(
            f"{from_table}.{from_column}"
            f" -> "
            f"{target_description}"
            f" | orphans={orphan_count}"
        )

    print()


def print_relationships():
    print("\nSEMANTIC RELATIONSHIPS")
    print("=" * 60)

    for relationship in SEMANTIC_RELATIONSHIPS:
        from_table = relationship["from_table"]
        from_column = relationship["from_column"]
        to_column = relationship["to_column"]

        # Normal relationship:
        # table.column -> table.column
        if "to_table" in relationship:
            print(
                f"{from_table}.{from_column} "
                f"-> {relationship['to_table']}.{to_column}"
            )

        # Polymorphic relationship:
        # table.column -> table1.column OR table2.column
        elif "to_tables" in relationship:
            targets = " OR ".join(
                f"{table}.{to_column}"
                for table in relationship["to_tables"]
            )

            print(
                f"{from_table}.{from_column} "
                f"-> {targets}"
            )