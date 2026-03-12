from __future__ import annotations

from datetime import datetime

from nivvi.domain.models import (
    Account,
    AccountType,
    DeadlineItem,
    Direction,
    GoalPlan,
    Household,
    Transaction,
    UserRule,
)
from nivvi.services.audit_service import AuditService
from nivvi.services.utils import as_utc, generate_id, utc_now
from nivvi.storage.in_memory import InMemoryStore
from nivvi.storage.relational_persistence import RelationalPersistence


class HouseholdService:
    def __init__(
        self,
        store: InMemoryStore,
        audit: AuditService,
        relational_persistence: RelationalPersistence | None = None,
    ) -> None:
        self.store = store
        self.audit = audit
        self.relational_persistence = relational_persistence

    def create_or_get_household(self, household_id: str, household_name: str | None = None) -> Household:
        household = self.store.households.get(household_id)
        if household:
            return household

        household = Household(id=household_id, name=household_name or "Nivvi Household")
        self.store.households[household.id] = household
        self._persist_household(household)
        self.audit.log(household.id, "household.created", household.id, {"name": household.name})
        return household

    def connect_account(
        self,
        household_id: str,
        institution: str,
        account_type: AccountType,
        currency: str,
        balance: float,
        metadata: dict | None = None,
    ) -> Account:
        account = Account(
            id=generate_id("acct"),
            household_id=household_id,
            institution=institution,
            account_type=account_type,
            currency=currency,
            balance=balance,
            metadata=metadata or {},
        )
        self.store.accounts[account.id] = account
        self._persist_account(account)
        self.audit.log(
            household_id,
            "account.connected",
            account.id,
            {
                "institution": institution,
                "account_type": account_type.value,
                "currency": currency,
                "balance": balance,
            },
        )
        return account

    def import_transaction(
        self,
        household_id: str,
        account_id: str,
        amount: float,
        currency: str,
        direction: Direction,
        description: str,
        category: str,
        booked_at: datetime,
    ) -> Transaction:
        transaction = Transaction(
            id=generate_id("txn"),
            household_id=household_id,
            account_id=account_id,
            amount=amount,
            currency=currency,
            direction=direction,
            description=description,
            category=category,
            booked_at=as_utc(booked_at),
        )
        self.store.transactions[transaction.id] = transaction

        account = self.store.accounts.get(account_id)
        if account:
            signed_amount = amount if direction == Direction.CREDIT else -amount
            account.balance += signed_amount
            account.updated_at = utc_now()
            self._persist_account(account)
        self._persist_transaction(transaction)

        self.audit.log(
            household_id,
            "provider.transaction_ingested",
            transaction.id,
            {
                "account_id": account_id,
                "amount": amount,
                "currency": currency,
                "direction": direction.value,
                "category": category,
            },
        )
        return transaction

    def import_deadline(
        self,
        household_id: str,
        source: str,
        title: str,
        jurisdiction: str,
        due_at: datetime,
        penalty_risk: str,
        amount: float | None = None,
    ) -> DeadlineItem:
        deadline = DeadlineItem(
            id=generate_id("ddl"),
            household_id=household_id,
            source=source,
            title=title,
            jurisdiction=jurisdiction,
            due_at=as_utc(due_at),
            penalty_risk=penalty_risk,
            amount=amount,
        )
        self.store.deadlines[deadline.id] = deadline
        self._persist_deadline(deadline)
        self.audit.log(
            household_id,
            "deadline.ingested",
            deadline.id,
            {
                "title": title,
                "jurisdiction": jurisdiction,
                "due_at": deadline.due_at.isoformat(),
                "penalty_risk": penalty_risk,
            },
        )
        return deadline

    def upsert_goal(
        self,
        household_id: str,
        name: str,
        target_amount: float,
        target_date: datetime,
        recommended_contribution: float,
        tradeoffs: list[str] | None = None,
        goal_id: str | None = None,
    ) -> GoalPlan:
        goal = GoalPlan(
            goal_id=goal_id or generate_id("goal"),
            household_id=household_id,
            name=name,
            target_amount=target_amount,
            target_date=as_utc(target_date),
            recommended_contribution=recommended_contribution,
            tradeoffs=tradeoffs or [],
        )
        self.store.goals[goal.goal_id] = goal
        self._persist_goal(goal)
        self.audit.log(
            household_id,
            "goal.upserted",
            goal.goal_id,
            {
                "name": name,
                "target_amount": target_amount,
                "target_date": goal.target_date.isoformat(),
            },
        )
        return goal

    def add_rule(
        self,
        household_id: str,
        scope: str,
        daily_amount_limit: float | None,
        max_single_action: float | None,
        blocked_categories: list[str],
        blocked_action_types: list,
        require_approval_always: bool,
        anomaly_detection_enabled: bool = True,
        anomaly_expense_multiplier: float = 1.75,
        anomaly_income_multiplier: float = 2.0,
        anomaly_min_expense_amount: float = 150.0,
        anomaly_min_income_amount: float = 300.0,
        weekly_planning_enabled: bool = True,
        weekly_drift_threshold_percent: float = 20.0,
        weekly_min_delta_amount: float = 50.0,
        weekly_cooldown_days: int = 6,
    ) -> UserRule:
        existing_rules = self.store.rules[household_id]
        scope_rules = [item for item in existing_rules if item.scope == scope]
        active_scope_rules = [item for item in scope_rules if item.is_active]
        next_version = max((item.version for item in scope_rules), default=0) + 1
        new_rule_id = generate_id("rule")

        superseded_rule_ids: list[str] = []
        if active_scope_rules:
            superseded_at = utc_now()
            for prior in active_scope_rules:
                prior.is_active = False
                prior.superseded_at = superseded_at
                prior.superseded_by_rule_id = new_rule_id
                superseded_rule_ids.append(prior.rule_id)

        rule = UserRule(
            rule_id=new_rule_id,
            household_id=household_id,
            scope=scope,
            version=next_version,
            is_active=True,
            daily_amount_limit=daily_amount_limit,
            max_single_action=max_single_action,
            blocked_categories=blocked_categories,
            blocked_action_types=blocked_action_types,
            require_approval_always=require_approval_always,
            anomaly_detection_enabled=anomaly_detection_enabled,
            anomaly_expense_multiplier=anomaly_expense_multiplier,
            anomaly_income_multiplier=anomaly_income_multiplier,
            anomaly_min_expense_amount=anomaly_min_expense_amount,
            anomaly_min_income_amount=anomaly_min_income_amount,
            weekly_planning_enabled=weekly_planning_enabled,
            weekly_drift_threshold_percent=weekly_drift_threshold_percent,
            weekly_min_delta_amount=weekly_min_delta_amount,
            weekly_cooldown_days=weekly_cooldown_days,
        )
        existing_rules.append(rule)
        self._persist_rule(rule)
        for item in active_scope_rules:
            self._persist_rule(item)
        self.audit.log(
            household_id,
            "rule.upserted",
            rule.rule_id,
            {
                "scope": scope,
                "version": next_version,
                "superseded_rule_ids": superseded_rule_ids,
                "daily_amount_limit": daily_amount_limit,
                "max_single_action": max_single_action,
                "blocked_categories": blocked_categories,
                "blocked_action_types": [value.value for value in blocked_action_types],
                "anomaly_detection_enabled": anomaly_detection_enabled,
                "anomaly_expense_multiplier": anomaly_expense_multiplier,
                "anomaly_income_multiplier": anomaly_income_multiplier,
                "anomaly_min_expense_amount": anomaly_min_expense_amount,
                "anomaly_min_income_amount": anomaly_min_income_amount,
                "weekly_planning_enabled": weekly_planning_enabled,
                "weekly_drift_threshold_percent": weekly_drift_threshold_percent,
                "weekly_min_delta_amount": weekly_min_delta_amount,
                "weekly_cooldown_days": weekly_cooldown_days,
            },
        )
        return rule

    def list_rules(self, household_id: str, include_inactive: bool = False) -> list[UserRule]:
        rules = self.store.rules.get(household_id, [])
        if not include_inactive:
            rules = [rule for rule in rules if rule.is_active]
        return sorted(
            rules,
            key=lambda item: (item.scope, item.version, item.created_at),
            reverse=True,
        )

    def get_ledger(self, household_id: str) -> dict:
        household = self.store.households[household_id]
        accounts = [account for account in self.store.accounts.values() if account.household_id == household_id]
        transactions = [
            transaction
            for transaction in self.store.transactions.values()
            if transaction.household_id == household_id
        ]
        deadlines = [deadline for deadline in self.store.deadlines.values() if deadline.household_id == household_id]
        goals = [goal for goal in self.store.goals.values() if goal.household_id == household_id]

        return {
            "household": household,
            "accounts": accounts,
            "transactions": sorted(transactions, key=lambda item: item.booked_at, reverse=True),
            "deadlines": sorted(deadlines, key=lambda item: item.due_at),
            "goals": sorted(goals, key=lambda item: item.target_date),
        }

    def _persist_household(self, household: Household) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_household(household)

    def _persist_account(self, account: Account) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_account(account)

    def _persist_transaction(self, transaction: Transaction) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_transaction(transaction)

    def _persist_deadline(self, deadline: DeadlineItem) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_deadline(deadline)

    def _persist_goal(self, goal: GoalPlan) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_goal(goal)

    def _persist_rule(self, rule: UserRule) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_rule(rule)
