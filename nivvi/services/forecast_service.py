from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

from nivvi.domain.models import AccountType, Direction, ForecastPoint
from nivvi.services.utils import utc_now
from nivvi.storage.in_memory import InMemoryStore


class ForecastService:
    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def _daily_net_cashflows(self, household_id: str, lookback_days: int = 90) -> list[float]:
        now = utc_now()
        floor = now - timedelta(days=lookback_days)
        daily_values: dict[datetime.date, float] = defaultdict(float)

        for transaction in self.store.transactions.values():
            if transaction.household_id != household_id:
                continue
            if transaction.booked_at < floor:
                continue
            signed_amount = transaction.amount if transaction.direction == Direction.CREDIT else -transaction.amount
            daily_values[transaction.booked_at.date()] += signed_amount

        if not daily_values:
            return [0.0]

        return list(daily_values.values())

    def _liquid_balance(self, household_id: str) -> float:
        liquid_types = {AccountType.BANK, AccountType.CARD}
        return sum(
            account.balance
            for account in self.store.accounts.values()
            if account.household_id == household_id and account.account_type in liquid_types
        )

    def forecast(self, household_id: str, horizon_days: int) -> list[ForecastPoint]:
        cashflows = self._daily_net_cashflows(household_id)
        mean_cashflow = sum(cashflows) / len(cashflows)
        variance = sum((value - mean_cashflow) ** 2 for value in cashflows) / len(cashflows)
        stddev = math.sqrt(variance)

        start_balance = self._liquid_balance(household_id)
        now = utc_now()
        step = 7

        points: list[ForecastPoint] = []
        for day in range(step, horizon_days + 1, step):
            drift = mean_cashflow * day
            band = 1.2816 * stddev * math.sqrt(day)

            p50 = start_balance + drift
            p10 = p50 - band
            p90 = p50 + band

            flags = []
            if p10 < 0:
                flags.append("shortfall_risk")
            if p50 < 0:
                flags.append("base_case_negative")

            points.append(
                ForecastPoint(
                    date=now + timedelta(days=day),
                    p10_balance=round(p10, 2),
                    p50_balance=round(p50, 2),
                    p90_balance=round(p90, 2),
                    risk_flags=flags,
                )
            )

        if not points or points[-1].date.date() != (now + timedelta(days=horizon_days)).date():
            day = horizon_days
            drift = mean_cashflow * day
            band = 1.2816 * stddev * math.sqrt(max(day, 1))
            p50 = start_balance + drift
            p10 = p50 - band
            p90 = p50 + band
            flags = ["shortfall_risk"] if p10 < 0 else []
            points.append(
                ForecastPoint(
                    date=now + timedelta(days=day),
                    p10_balance=round(p10, 2),
                    p50_balance=round(p50, 2),
                    p90_balance=round(p90, 2),
                    risk_flags=flags,
                )
            )

        return points
