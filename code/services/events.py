class EventsService:

    def __init__(self, connection):
        self.connection = connection

    def get_events(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        event_type: str | None = None,
        category: str | None = None,
        direction: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:

        query = """
            SELECT
                event_id,
                user_id,
                event_type,
                description,
                category,
                direction,
                amount,
                currency,
                event_date,
                settlement_date,
                status,
                linked_event_id,
                flexibility,
                minimum_allowed_amount
            FROM financial_events
            WHERE user_id = ?
        """

        params = [user_id]

        if start_date:
            query += """
                AND event_date >= ?
            """
            params.append(start_date)

        if end_date:
            query += """
                AND event_date <= ?
            """
            params.append(end_date)

        if event_type:
            query += """
                AND event_type = ?
            """
            params.append(event_type)

        if category:
            query += """
                AND category = ?
            """
            params.append(category)

        if direction:
            query += """
                AND direction = ?
            """
            params.append(direction)

        if status:
            query += """
                AND status = ?
            """
            params.append(status)

        query += """
            ORDER BY event_date ASC, event_id ASC
        """

        if limit is not None:
            query += """
                LIMIT ?
            """
            params.append(limit)

        rows = self.connection.execute(
            query,
            params,
        ).fetchall()

        return [
            self._row_to_dict(row)
            for row in rows
        ]

    @staticmethod
    def _row_to_dict(row) -> dict:

        return {
            "event_id": row[0],
            "user_id": row[1],
            "event_type": row[2],
            "description": row[3],
            "category": row[4],
            "direction": row[5],
            "amount": row[6],
            "currency": row[7],
            "event_date": row[8],
            "settlement_date": row[9],
            "status": row[10],
            "linked_event_id": row[11],
            "flexibility": row[12],
            "minimum_allowed_amount": row[13],
        }