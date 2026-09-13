class RequestService:

    def __init__(self, connection):
        self.connection = connection

    def get_request(
        self,
        request_id: str,
    ) -> dict | None:

        row = self.connection.execute(
            """
            SELECT
                request_id,
                user_id,
                request_date,
                request_type,
                requested_amount,
                desired_completion_date,
                allows_partial_payment,
                request_text
            FROM requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is not None:
            return self._row_to_dict(
                row,
                "requests",
            )

        row = self.connection.execute(
            """
            SELECT
                request_id,
                user_id,
                request_date,
                request_type,
                requested_amount,
                desired_completion_date,
                allows_partial_payment,
                request_text
            FROM sample_requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()

        if row is not None:
            return self._row_to_dict(
                row,
                "sample_requests",
            )

        return None

    @staticmethod
    def _row_to_dict(
        row,
        source: str,
    ) -> dict:

        return {
            "request_id": row[0],
            "user_id": row[1],
            "request_date": row[2],
            "request_type": row[3],
            "requested_amount": row[4],
            "desired_completion_date": row[5],
            "allows_partial_payment": bool(row[6]),
            "request_text": row[7],
            "source": source,
        }