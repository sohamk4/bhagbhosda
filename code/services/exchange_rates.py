from __future__ import annotations


class ExchangeRateService:
    """
    Dated currency conversion backed by `exchange_rates.csv`.

    Resolution order for a pair (from, to) on a given date:

      1. Same currency -> 1.0
      2. Exact-date direct row    (from -> to)
      3. Exact-date inverse row   (to   -> from), inverted
      4. Nearest-date direct row  within NEAREST_WINDOW_DAYS
      5. Nearest-date inverse row within NEAREST_WINDOW_DAYS
      6. None  (caller must skip the event; do NOT treat as 1.0)

    All lookups are cached in memory.
    """

    NEAREST_WINDOW_DAYS = 7

    def __init__(self, connection):
        self.connection = connection

        # (rate_date, from, to) -> float | None
        self._rate_cache: dict[tuple[str, str, str], float | None] = {}

        # (from, to) -> list of (rate_date, rate), populated lazily
        self._pair_table_cache: dict[tuple[str, str], list[tuple[str, float]]] = {}

    # ==========================================================
    # Normalization
    # ==========================================================

    @staticmethod
    def _norm(currency: str) -> str:
        return str(currency or "").strip().upper()

    # ==========================================================
    # Strict API (raises) — for callers that require a rate
    # ==========================================================

    def get_rate(
        self,
        rate_date: str,
        from_currency: str,
        to_currency: str,
    ) -> float:
        rate = self.get_rate_or_none(rate_date, from_currency, to_currency)
        if rate is None:
            raise ValueError(
                f"No exchange rate for {rate_date}: "
                f"{from_currency}->{to_currency}"
            )
        return rate

    # ==========================================================
    # Non-raising API — what the forecast engine uses
    # ==========================================================

    def get_rate_or_none(
        self,
        rate_date: str,
        from_currency: str,
        to_currency: str,
    ) -> float | None:
        src = self._norm(from_currency)
        dst = self._norm(to_currency)
        date_str = str(rate_date)

        if src == dst:
            return 1.0

        cache_key = (date_str, src, dst)
        if cache_key in self._rate_cache:
            return self._rate_cache[cache_key]

        rate = self._resolve(date_str, src, dst)
        self._rate_cache[cache_key] = rate
        return rate

    # ==========================================================
    # Conversion helper
    # ==========================================================

    def convert(
        self,
        amount: float,
        rate_date: str,
        from_currency: str,
        to_currency: str,
    ) -> float | None:
        rate = self.get_rate_or_none(rate_date, from_currency, to_currency)
        if rate is None:
            return None
        return float(amount) * rate

    # ==========================================================
    # Adapter — matches ForecastEngine's expected callback signature
    # ==========================================================

    def converter(
        self,
        from_currency: str,
        to_currency: str,
        on_date: str,
        request_date: str | None = None,
    ) -> float | None:
        """
        ForecastEngine calls:
            converter(src, dst, event_date, request_date)

        `request_date` is accepted for interface compatibility but not
        used — the event's own date drives the lookup.
        """
        return self.get_rate_or_none(on_date, from_currency, to_currency)

    # ==========================================================
    # Resolution
    # ==========================================================

    def _resolve(
        self,
        date_str: str,
        src: str,
        dst: str,
    ) -> float | None:

        # 1. Exact-date direct.
        direct = self._lookup_exact(date_str, src, dst)
        if direct is not None:
            return direct

        # 2. Exact-date inverse.
        inverse = self._lookup_exact(date_str, dst, src)
        if inverse is not None and inverse != 0:
            return 1.0 / inverse

        # 3. Nearest-date direct.
        direct_near = self._lookup_nearest(date_str, src, dst)
        if direct_near is not None:
            return direct_near

        # 4. Nearest-date inverse.
        inverse_near = self._lookup_nearest(date_str, dst, src)
        if inverse_near is not None and inverse_near != 0:
            return 1.0 / inverse_near

        return None

    def _lookup_exact(
        self,
        date_str: str,
        src: str,
        dst: str,
    ) -> float | None:
        row = self.connection.execute(
            """
            SELECT rate
            FROM exchange_rates
            WHERE rate_date = ?
              AND from_currency = ?
              AND to_currency = ?
            """,
            (date_str, src, dst),
        ).fetchone()

        if row is None:
            return None

        return float(row[0])

    def _lookup_nearest(
        self,
        date_str: str,
        src: str,
        dst: str,
    ) -> float | None:
        """
        Nearest-date match within +/- NEAREST_WINDOW_DAYS.

        Uses SQLite's julianday() to measure day distance.
        """
        row = self.connection.execute(
            """
            SELECT rate
            FROM exchange_rates
            WHERE from_currency = ?
              AND to_currency = ?
              AND ABS(julianday(rate_date) - julianday(?)) <= ?
            ORDER BY ABS(julianday(rate_date) - julianday(?))
            LIMIT 1
            """,
            (src, dst, date_str, self.NEAREST_WINDOW_DAYS, date_str),
        ).fetchone()

        if row is None:
            return None

        return float(row[0])

    # ==========================================================
    # Diagnostics — useful while debugging the batch
    # ==========================================================

    def available_pairs(self) -> set[tuple[str, str]]:
        rows = self.connection.execute(
            """
            SELECT DISTINCT from_currency, to_currency
            FROM exchange_rates
            """
        ).fetchall()
        return {
            (self._norm(r[0]), self._norm(r[1]))
            for r in rows
        }

    def available_dates(
        self,
        from_currency: str,
        to_currency: str,
    ) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT rate_date
            FROM exchange_rates
            WHERE from_currency = ?
              AND to_currency = ?
            ORDER BY rate_date
            """,
            (self._norm(from_currency), self._norm(to_currency)),
        ).fetchall()
        return [r[0] for r in rows]