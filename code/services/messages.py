class MessagesService:

    def __init__(self, connection):
        self.connection = connection

    def get_messages(
        self,
        user_id: str,
        request_id: str | None = None,
        related_event_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:

        query = """
            SELECT
                message_id,
                user_id,
                request_id,
                related_event_id,
                sent_at,
                source_type,
                message_text
            FROM messages
            WHERE user_id = ?
        """

        params = [user_id]

        if request_id:
            query += """
                AND request_id = ?
            """
            params.append(request_id)

        if related_event_id:
            query += """
                AND related_event_id = ?
            """
            params.append(related_event_id)

        if start_date:
            query += """
                AND sent_at >= ?
            """
            params.append(start_date)

        if end_date:
            query += """
                AND sent_at <= ?
            """
            params.append(end_date)

        query += """
            ORDER BY sent_at ASC, message_id ASC
        """

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
            "message_id": row[0],
            "user_id": row[1],
            "request_id": row[2],
            "related_event_id": row[3],
            "sent_at": row[4],
            "source_type": row[5],
            "message_text": row[6],
        }