class PaymentOptionsService:

    def __init__(self, connection):
        self.connection = connection

    def get_payment_options(
        self,
        request_id: str,
    ) -> list[dict]:

        rows = self.connection.execute(
            """
            SELECT
                payment_option_id,
                request_id,
                payment_method,
                payment_amount,
                number_of_payments,
                first_payment_date,
                payment_frequency_days,
                financing_fee,
                total_payable_amount
            FROM request_payment_options
            WHERE request_id = ?
            ORDER BY payment_option_id
            """,
            (request_id,),
        ).fetchall()

        return [
            self._row_to_dict(row)
            for row in rows
        ]

    @staticmethod
    def _row_to_dict(row) -> dict:

        return {
            "payment_option_id": row[0],
            "request_id": row[1],
            "payment_method": row[2],
            "payment_amount": row[3],
            "number_of_payments": row[4],
            "first_payment_date": row[5],
            "payment_frequency_days": row[6],
            "financing_fee": row[7],
            "total_payable_amount": row[8],
        }