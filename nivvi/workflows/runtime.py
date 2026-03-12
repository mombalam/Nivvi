from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from nivvi.domain.models import ChatChannel, ChatMessage, RuntimeCycleMetric
from nivvi.services.audit_service import AuditService
from nivvi.services.timeline_service import TimelineService
from nivvi.services.utils import generate_id, utc_now
from nivvi.storage.in_memory import InMemoryStore
from nivvi.workflows.orchestrator import AgentOrchestrator


@dataclass
class AgentRuntimeStatus:
    running: bool
    interval_seconds: int
    cycles_run: int
    last_run_at: str | None
    last_error: str | None


class AgentRuntime:
    """Background runtime that executes periodic agent cycles for all households."""

    def __init__(
        self,
        store: InMemoryStore,
        orchestrator: AgentOrchestrator,
        timeline_service: TimelineService,
        audit_service: AuditService,
        interval_seconds: int = 120,
        on_cycle_complete: Callable[[], None] | None = None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.timeline_service = timeline_service
        self.audit_service = audit_service
        self.interval_seconds = max(10, interval_seconds)
        self.on_cycle_complete = on_cycle_complete

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self.cycles_run = 0
        self.last_run_at: str | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="nivvi-agent-runtime")

    async def stop(self) -> None:
        if not self.running:
            return
        self._stop_event.set()
        assert self._task is not None
        await self._task
        self._task = None

    async def run_cycle(self) -> dict:
        cycle_started = utc_now()
        households = list(self.store.households.keys())
        processed = 0
        emitted = 0
        interventions_sent = 0
        emitted_by_loop = {"daily_monitor": 0, "anomaly_loop": 0, "weekly_planning": 0}

        for household_id in households:
            processed += 1
            daily_emitted = self.orchestrator.run_daily_monitor(household_id)
            emitted += len(daily_emitted)
            emitted_by_loop["daily_monitor"] += len(daily_emitted)

            anomaly_result = self.orchestrator.run_event_anomaly_loop(household_id)
            anomaly_emitted = anomaly_result["actions_emitted"]
            emitted += len(anomaly_emitted)
            emitted_by_loop["anomaly_loop"] += len(anomaly_emitted)
            for intervention in anomaly_result["interventions"]:
                self._send_agent_intervention(
                    household_id=household_id,
                    text=intervention["text"],
                    kind=intervention["kind"],
                    metadata={
                        "transaction_id": intervention["transaction_id"],
                        "action_id": intervention["action_id"],
                    },
                )
                interventions_sent += 1

            weekly_result = self.orchestrator.run_weekly_planning_loop(household_id)
            weekly_emitted = weekly_result["actions_emitted"]
            emitted += len(weekly_emitted)
            emitted_by_loop["weekly_planning"] += len(weekly_emitted)
            for intervention in weekly_result["interventions"]:
                self._send_agent_intervention(
                    household_id=household_id,
                    text=intervention["text"],
                    kind=intervention["kind"],
                    metadata={
                        "week_key": intervention["week_key"],
                        "action_id": intervention["action_id"],
                    },
                )
                interventions_sent += 1

            self._run_deadline_guard(household_id)

        cycle_ended = utc_now()
        duration_ms = int(max((cycle_ended - cycle_started).total_seconds() * 1000, 0))
        dispatch_attempts = [
            item
            for attempts in self.store.execution_attempts.values()
            for item in attempts
            if item.attempted_at >= cycle_started
        ]
        dispatch_successes = len([item for item in dispatch_attempts if item.result == "success"])
        dispatch_failures = len([item for item in dispatch_attempts if item.result == "failed"])
        provider_sync_failures = len(
            [
                job
                for job in self.store.provider_sync_jobs.values()
                if job.started_at >= cycle_started and job.status.value == "failed"
            ]
        )
        metric = RuntimeCycleMetric(
            id=generate_id("rtm"),
            run_at=cycle_started,
            duration_ms=duration_ms,
            processed_households=processed,
            emitted_actions=emitted,
            emitted_by_loop=emitted_by_loop,
            interventions_sent=interventions_sent,
            dispatch_successes=dispatch_successes,
            dispatch_failures=dispatch_failures,
            provider_failures=provider_sync_failures + dispatch_failures,
        )
        self.store.runtime_cycle_metrics.append(metric)
        if len(self.store.runtime_cycle_metrics) > 500:
            del self.store.runtime_cycle_metrics[:-500]

        self.cycles_run += 1
        self.last_run_at = cycle_started.isoformat()
        self.last_error = None
        if self.on_cycle_complete is not None:
            self.on_cycle_complete()

        return {
            "processed_households": processed,
            "emitted_actions": emitted,
            "emitted_by_loop": emitted_by_loop,
            "interventions_sent": interventions_sent,
            "duration_ms": duration_ms,
            "dispatch_successes": dispatch_successes,
            "dispatch_failures": dispatch_failures,
            "provider_failures": metric.provider_failures,
            "metric_id": metric.id,
            "run_at": self.last_run_at,
        }

    def status(self) -> AgentRuntimeStatus:
        return AgentRuntimeStatus(
            running=self.running,
            interval_seconds=self.interval_seconds,
            cycles_run=self.cycles_run,
            last_run_at=self.last_run_at,
            last_error=self.last_error,
        )

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_cycle()
            except Exception as error:  # noqa: BLE001
                self.last_error = str(error)
                self.audit_service.log(
                    household_id="system",
                    event_type="runtime.cycle_error",
                    entity_id="agent_runtime",
                    details={"error": str(error)},
                )

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue

    def metrics(self, limit: int = 50) -> dict:
        safe_limit = max(1, min(limit, 500))
        items = sorted(self.store.runtime_cycle_metrics, key=lambda item: item.run_at, reverse=True)[:safe_limit]
        avg_duration = int(sum(item.duration_ms for item in items) / len(items)) if items else 0
        return {
            "items": items,
            "summary": {
                "count": len(items),
                "average_duration_ms": avg_duration,
                "dispatch_successes": sum(item.dispatch_successes for item in items),
                "dispatch_failures": sum(item.dispatch_failures for item in items),
                "provider_failures": sum(item.provider_failures for item in items),
            },
        }

    def _run_deadline_guard(self, household_id: str) -> None:
        items = self.timeline_service.timeline(household_id, lookahead_days=3)
        if not items:
            return

        earliest = items[0]
        text = (
            f"Upcoming deadline: {earliest.title} due {earliest.due_at.date().isoformat()} "
            f"(risk: {earliest.penalty_risk})."
        )

        already_sent = any(
            message.household_id == household_id
            and message.sender == "agent"
            and message.metadata.get("kind") == "deadline_guard"
            and message.metadata.get("deadline_title") == earliest.title
            and message.created_at >= (utc_now() - timedelta(hours=24))
            for message in self.store.chat_messages
        )
        if already_sent:
            return

        self.store.chat_messages.append(
            ChatMessage(
                id=generate_id("msg"),
                household_id=household_id,
                channel=ChatChannel.WHATSAPP,
                user_id=None,
                sender="agent",
                text=text,
                metadata={"kind": "deadline_guard", "deadline_title": earliest.title},
            )
        )
        self.audit_service.log(
            household_id,
            "runtime.deadline_guard_message",
            earliest.id,
            {"title": earliest.title, "due_at": earliest.due_at.isoformat()},
        )

    def _send_agent_intervention(self, household_id: str, text: str, kind: str, metadata: dict) -> None:
        payload = {"kind": kind, **metadata}
        self.store.chat_messages.append(
            ChatMessage(
                id=generate_id("msg"),
                household_id=household_id,
                channel=ChatChannel.WHATSAPP,
                user_id=None,
                sender="agent",
                text=text,
                metadata=payload,
            )
        )
        self.audit_service.log(
            household_id,
            "runtime.agent_intervention",
            household_id,
            {"kind": kind, "metadata": payload},
        )
