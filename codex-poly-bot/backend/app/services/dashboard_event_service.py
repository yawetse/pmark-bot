"""Commit-driven dashboard invalidation delivery.

REQ: REQ-DB-010, REQ-UI-015
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import json
import logging
from threading import RLock
from typing import AsyncIterator

import psycopg
from psycopg import sql

from app.db import PersistentDatabaseState


LOGGER = logging.getLogger(__name__)
DASHBOARD_EVENT_CHANNEL = "codex_dashboard_events"
LISTENER_RECONNECT_SECONDS = 2
LISTENER_READY_TIMEOUT_SECONDS = 2


@dataclass(frozen=True)
class DashboardChange:
    """A data-free invalidation scoped to a dashboard audience."""

    environment: str | None
    username: str | None = None
    source_available: bool = True


class DashboardEventSubscription:
    """One coalescing queue owned by a connected WebSocket."""

    def __init__(self, *, environment: str, username: str):
        self.environment = environment
        self.username = username
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[DashboardChange] = asyncio.Queue(maxsize=1)

    async def get(self) -> DashboardChange:
        return await self._queue.get()

    def empty(self) -> bool:
        return self._queue.empty()

    def offer_threadsafe(self, change: DashboardChange) -> None:
        try:
            self._loop.call_soon_threadsafe(self._offer, change)
        except RuntimeError:
            # The subscriber's event loop can close between publish and unsubscribe.
            return

    def _offer(self, change: DashboardChange) -> None:
        if self._queue.full():
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        self._queue.put_nowait(change)


class DashboardEventBroker:
    """Fan out one Postgres notification stream to local WebSocket clients."""

    def __init__(self, *, postgres_dsn: str | None = None):
        self.postgres_dsn = postgres_dsn
        self._subscriptions: set[DashboardEventSubscription] = set()
        self._subscription_lock = RLock()
        self._listener_ready = asyncio.Event()
        self._listener_task: asyncio.Task[None] | None = None

    @property
    def source_ready(self) -> bool:
        return self.postgres_dsn is not None and self._listener_ready.is_set()

    async def start(self) -> None:
        """Start the single Postgres listener used by this backend task."""

        if self.postgres_dsn is None or self._listener_task is not None:
            return
        self._listener_task = asyncio.create_task(self._listen(), name="dashboard-event-listener")
        await self.wait_until_ready(timeout=LISTENER_READY_TIMEOUT_SECONDS)

    async def stop(self) -> None:
        task = self._listener_task
        self._listener_task = None
        self._listener_ready.clear()
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def wait_until_ready(self, *, timeout: float) -> bool:
        if self.postgres_dsn is None:
            return False
        if self._listener_ready.is_set():
            return True
        try:
            await asyncio.wait_for(self._listener_ready.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    @asynccontextmanager
    async def subscribe(
        self,
        *,
        environment: str,
        username: str,
    ) -> AsyncIterator[DashboardEventSubscription]:
        subscription = DashboardEventSubscription(
            environment=environment,
            username=username,
        )
        with self._subscription_lock:
            self._subscriptions.add(subscription)
        try:
            yield subscription
        finally:
            with self._subscription_lock:
                self._subscriptions.discard(subscription)

    def publish(self, change: DashboardChange) -> None:
        """Publish without blocking a database listener or request thread."""

        with self._subscription_lock:
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            if _change_matches(change, subscription):
                subscription.offer_threadsafe(change)

    async def _listen(self) -> None:
        assert self.postgres_dsn is not None
        while True:
            try:
                connection = await psycopg.AsyncConnection.connect(
                    self.postgres_dsn,
                    autocommit=True,
                )
                async with connection:
                    await connection.execute(
                        sql.SQL("LISTEN {}").format(sql.Identifier(DASHBOARD_EVENT_CHANNEL))
                    )
                    self._listener_ready.set()
                    LOGGER.info("dashboard Postgres event listener connected")
                    while True:
                        async for notification in connection.notifies(timeout=30):
                            change = dashboard_change_from_payload(notification.payload)
                            if change is not None:
                                self.publish(change)
            except asyncio.CancelledError:
                raise
            except Exception:
                was_ready = self._listener_ready.is_set()
                self._listener_ready.clear()
                if was_ready:
                    self.publish(
                        DashboardChange(environment=None, source_available=False)
                    )
                LOGGER.exception("dashboard Postgres event listener disconnected")
                await asyncio.sleep(LISTENER_RECONNECT_SECONDS)


def dashboard_change_from_payload(payload: str) -> DashboardChange | None:
    """Parse a notification without trusting database payload shape."""

    try:
        value = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        LOGGER.warning("ignored invalid dashboard event payload")
        return None
    if not isinstance(value, dict):
        return None
    environment = str(value.get("environment") or "").strip()
    if not environment:
        return None
    username_value = value.get("username")
    username = str(username_value).strip() if username_value else None
    return DashboardChange(environment=environment, username=username or None)


def postgres_dashboard_event_dsn(state: object) -> str | None:
    """Return a psycopg-compatible DSN for a persistent repository state."""

    if not isinstance(state, PersistentDatabaseState):
        return None
    engine = state.session_factory.kw.get("bind")
    if engine is None:
        return None
    return engine.url.set(drivername="postgresql").render_as_string(hide_password=False)


def _change_matches(
    change: DashboardChange,
    subscription: DashboardEventSubscription,
) -> bool:
    if not change.source_available:
        return True
    if change.environment != subscription.environment:
        return False
    return change.username is None or change.username == subscription.username
