class ProfileService:

    def __init__(self, connection):
        self.connection = connection

    def get_profile(self, user_id: str) -> dict | None:

        row = self.connection.execute(
            """
            SELECT
                user_id,
                home_currency,
                current_available_balance,
                minimum_balance_to_keep,
                financial_priorities,
                expense_categories_to_protect,
                expense_categories_user_is_willing_to_reduce,
                expense_categories_user_is_willing_to_stop,
                payment_methods_user_will_consider,
                max_installment_months
            FROM financial_profiles
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            "user_id": row[0],
            "home_currency": row[1],
            "current_available_balance": row[2],
            "minimum_balance_to_keep": row[3],
            "financial_priorities": self._parse_list(row[4]),
            "protected_categories": self._parse_list(row[5]),
            "reducible_categories": self._parse_list(row[6]),
            "stoppable_categories": self._parse_list(row[7]),
            "accepted_payment_methods": self._parse_list(row[8]),
            "max_installment_months": row[9],
        }

    @staticmethod
    def _parse_list(value):
        if value is None:
            return []
    
        value = str(value).strip()
    
        if not value:
            return []
    
        value = value.replace(",", "|")
    
        return [
            item.strip()
            for item in value.split("|")
            if item.strip()
        ]