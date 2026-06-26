"""Provider-side AI usage import helpers.

REQ: REQ-LLM-002, REQ-UI-010, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Mapping, Protocol

import httpx

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.domain import Environment, ModelProvider


class AiUsageImportUnavailableError(RuntimeError):
    """Expected provider usage import failure."""


class AiUsageImportUnsupportedError(AiUsageImportUnavailableError):
    """Raised when a provider does not expose usage rows for this account."""


@dataclass(frozen=True)
class ProviderUsageRow:
    """Normalized usage row from a provider API, export, or billing feed."""

    provider: ModelProvider
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    observed_at: datetime
    response_id: str | None = None
    pipeline_run_id: str | None = None
    pipeline_step: str | None = None
    candidate_id: str | None = None
    cost_source: str = "provider usage import"
    raw_payload: dict[str, Any] = field(default_factory=dict)


class AiUsageImportSource(Protocol):
    """Provider/export boundary for usage backfills."""

    source_name: str

    def fetch_usage(
        self,
        *,
        provider: ModelProvider,
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[ProviderUsageRow, ...]:
        """Return normalized usage rows for one provider and period."""


@dataclass(frozen=True)
class StaticAiUsageImportSource:
    """Test and export-backed source for provider usage rows."""

    rows: tuple[ProviderUsageRow, ...]
    source_name: str = "static provider usage export"

    def fetch_usage(
        self,
        *,
        provider: ModelProvider,
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[ProviderUsageRow, ...]:
        return tuple(
            row
            for row in self.rows
            if row.provider == provider
            and period_start <= row.observed_at <= period_end
        )


class UnsupportedAiUsageImportSource:
    """Default source used when no provider-side usage API/export is attached."""

    source_name = "provider usage import not configured"

    def fetch_usage(
        self,
        *,
        provider: ModelProvider,
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[ProviderUsageRow, ...]:
        raise AiUsageImportUnsupportedError(
            f"{provider.value} provider-side usage import is not configured"
        )


class ProviderBackedAiUsageImportSource:
    """Fetch organization-level provider usage when admin keys are configured."""

    source_name = "provider admin usage api"

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.environ = environ or {}
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    def fetch_usage(
        self,
        *,
        provider: ModelProvider,
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[ProviderUsageRow, ...]:
        if provider == ModelProvider.OPENAI:
            return self._openai_usage(period_start=period_start, period_end=period_end)
        if provider == ModelProvider.CLAUDE:
            return self._anthropic_usage(period_start=period_start, period_end=period_end)
        raise AiUsageImportUnsupportedError(f"{provider.value} usage import is not supported")

    def _openai_usage(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[ProviderUsageRow, ...]:
        admin_key = self.environ.get("OPENAI_ADMIN_API_KEY") or self.environ.get("OPENAI_USAGE_API_KEY")
        if not admin_key:
            raise AiUsageImportUnsupportedError("OPENAI_ADMIN_API_KEY is required for OpenAI usage import")
        headers = {"Authorization": f"Bearer {admin_key}"}
        organization = self.environ.get("OPENAI_ORGANIZATION_ID")
        project = self.environ.get("OPENAI_PROJECT_ID")
        if organization:
            headers["OpenAI-Organization"] = organization
        if project:
            headers["OpenAI-Project"] = project
        rows: list[ProviderUsageRow] = []
        with self._client() as client:
            usage_payloads = self._paged_get(
                client,
                "https://api.openai.com/v1/organization/usage/completions",
                headers=headers,
                params=[
                    ("start_time", str(int(period_start.timestamp()))),
                    ("end_time", str(int(period_end.timestamp()))),
                    ("bucket_width", "1d"),
                    ("group_by", "model"),
                    ("limit", "31"),
                ],
            )
            for payload in usage_payloads:
                rows.extend(_openai_usage_rows(payload))
            cost_payloads = self._paged_get(
                client,
                "https://api.openai.com/v1/organization/costs",
                headers=headers,
                params=[
                    ("start_time", str(int(period_start.timestamp()))),
                    ("end_time", str(int(period_end.timestamp()))),
                    ("bucket_width", "1d"),
                    ("limit", "31"),
                ],
            )
            for payload in cost_payloads:
                rows.extend(_openai_cost_rows(payload))
        return tuple(rows)

    def _anthropic_usage(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[ProviderUsageRow, ...]:
        admin_key = self.environ.get("ANTHROPIC_ADMIN_API_KEY") or self.environ.get("ANTHROPIC_USAGE_API_KEY")
        if not admin_key:
            raise AiUsageImportUnsupportedError("ANTHROPIC_ADMIN_API_KEY is required for Claude usage import")
        headers = {
            "anthropic-version": "2023-06-01",
            "x-api-key": admin_key,
        }
        with self._client() as client:
            usage_payload = self._get_json(
                client,
                "https://api.anthropic.com/v1/organizations/usage_report/messages",
                headers=headers,
                params={
                    "starting_at": period_start.isoformat(),
                    "ending_at": period_end.isoformat(),
                    "group_by": "model",
                },
            )
            cost_payload = self._get_json(
                client,
                "https://api.anthropic.com/v1/organizations/cost_report",
                headers=headers,
                params={
                    "starting_at": period_start.isoformat(),
                    "ending_at": period_end.isoformat(),
                    "group_by": "model",
                },
            )
        return tuple(_anthropic_usage_rows(usage_payload) + _anthropic_cost_rows(cost_payload))

    def _paged_get(
        self,
        client: httpx.Client,
        url: str,
        *,
        headers: dict[str, str],
        params: list[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        page_cursor: str | None = None
        for _ in range(20):
            page_params = list(params)
            if page_cursor:
                page_params.append(("page", page_cursor))
            payload = self._get_json(client, url, headers=headers, params=page_params)
            payloads.append(payload)
            page_cursor = _next_page_cursor(payload)
            if not page_cursor:
                break
        return payloads

    def _get_json(
        self,
        client: httpx.Client,
        url: str,
        *,
        headers: dict[str, str],
        params: Any,
    ) -> dict[str, Any]:
        try:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise AiUsageImportUnavailableError(
                f"provider usage import failed with HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AiUsageImportUnavailableError(f"provider usage import failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise AiUsageImportUnavailableError("provider usage import returned an unexpected payload")
        return payload

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_seconds, transport=self.transport)


@dataclass(frozen=True)
class AiUsageImportResult:
    """Dashboard-safe provider usage import result."""

    payload: dict[str, Any]


class AiUsageImportService:
    """Import provider-side AI token usage into dashboard economics."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        source: AiUsageImportSource | None = None,
    ) -> None:
        self.registry = registry
        self.source = source or UnsupportedAiUsageImportSource()

    def import_provider_usage(
        self,
        *,
        environment: Environment,
        provider: ModelProvider,
        period_start: datetime,
        period_end: datetime,
        triggered_by: str = "system",
    ) -> AiUsageImportResult:
        started_at = datetime.now(UTC)
        imported_rows: tuple[ProviderUsageRow, ...] = ()
        status = "completed"
        error_code = None
        try:
            imported_rows = self.source.fetch_usage(
                provider=provider,
                period_start=period_start,
                period_end=period_end,
            )
            for row in imported_rows:
                self.registry.shared().record_ai_usage_event(
                    environment=environment,
                    provider=provider,
                    model=row.model,
                    pipeline_run_id=row.pipeline_run_id,
                    pipeline_step=row.pipeline_step,
                    candidate_id=row.candidate_id,
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    cost_usd=row.cost_usd,
                    usage_source="provider_backfill",
                    cost_source=row.cost_source,
                    response_id=row.response_id,
                    raw_payload=row.raw_payload,
                    imported_at=started_at,
                    created_at=row.observed_at,
                )
            message = (
                f"Imported {len(imported_rows)} {provider.value} usage row"
                f"{'' if len(imported_rows) == 1 else 's'}."
            )
        except AiUsageImportUnsupportedError as exc:
            status = "unsupported"
            error_code = "provider_usage_import_unsupported"
            message = str(exc)
        except (AiUsageImportUnavailableError, PersistenceUnavailableError, ValueError) as exc:
            status = "failed"
            error_code = "provider_usage_import_failed"
            message = str(exc)

        completed_at = datetime.now(UTC)
        run = self.registry.shared().record_ai_usage_import_run(
            environment=environment,
            provider=provider,
            status=status,
            source=self.source.source_name,
            period_start=period_start,
            period_end=period_end,
            imported_count=len(imported_rows),
            error_code=error_code,
            message=message,
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "triggered_by": triggered_by,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        return AiUsageImportResult(
            payload={
                "id": run["id"],
                "environment": environment.value,
                "provider": provider.value,
                "status": status,
                "source": self.source.source_name,
                "importedCount": len(imported_rows),
                "errorCode": error_code,
                "message": message,
                "periodStart": period_start.isoformat(),
                "periodEnd": period_end.isoformat(),
                "startedAt": started_at.isoformat(),
                "completedAt": completed_at.isoformat(),
            }
        )


def _openai_usage_rows(payload: dict[str, Any]) -> list[ProviderUsageRow]:
    rows: list[ProviderUsageRow] = []
    for bucket in _payload_items(payload):
        observed_at = _bucket_observed_at(bucket)
        for result in _payload_items(bucket, key="results"):
            prompt_tokens = _int_value(result.get("input_tokens")) + _int_value(result.get("input_cached_tokens"))
            completion_tokens = _int_value(result.get("output_tokens"))
            if prompt_tokens == 0 and completion_tokens == 0:
                continue
            rows.append(
                ProviderUsageRow(
                    provider=ModelProvider.OPENAI,
                    model=str(result.get("model") or "openai-completions"),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=Decimal("0"),
                    observed_at=observed_at,
                    cost_source="openai organization usage endpoint",
                    raw_payload={"bucket": bucket, "result": result},
                )
            )
    return rows


def _openai_cost_rows(payload: dict[str, Any]) -> list[ProviderUsageRow]:
    rows: list[ProviderUsageRow] = []
    for bucket in _payload_items(payload):
        observed_at = _bucket_observed_at(bucket)
        for result in _payload_items(bucket, key="results"):
            amount = _amount_value(result)
            if amount == Decimal("0"):
                continue
            rows.append(
                ProviderUsageRow(
                    provider=ModelProvider.OPENAI,
                    model=str(result.get("line_item") or result.get("model") or "openai-organization-cost"),
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost_usd=amount,
                    observed_at=observed_at,
                    cost_source="openai organization costs endpoint",
                    raw_payload={"bucket": bucket, "result": result},
                )
            )
    return rows


def _anthropic_usage_rows(payload: dict[str, Any]) -> list[ProviderUsageRow]:
    rows: list[ProviderUsageRow] = []
    for item in _payload_items(payload):
        prompt_tokens = (
            _int_value(item.get("input_tokens"))
            + _int_value(item.get("cache_creation_input_tokens"))
            + _int_value(item.get("cache_read_input_tokens"))
        )
        completion_tokens = _int_value(item.get("output_tokens"))
        if prompt_tokens == 0 and completion_tokens == 0:
            continue
        rows.append(
            ProviderUsageRow(
                provider=ModelProvider.CLAUDE,
                model=str(item.get("model") or item.get("model_name") or "claude-messages"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=Decimal("0"),
                observed_at=_observed_at(item),
                cost_source="anthropic usage report endpoint",
                raw_payload=item,
            )
        )
    return rows


def _anthropic_cost_rows(payload: dict[str, Any]) -> list[ProviderUsageRow]:
    rows: list[ProviderUsageRow] = []
    for item in _payload_items(payload):
        amount = _amount_value(item)
        if amount == Decimal("0"):
            continue
        rows.append(
            ProviderUsageRow(
                provider=ModelProvider.CLAUDE,
                model=str(item.get("model") or item.get("model_name") or "claude-cost"),
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=amount,
                observed_at=_observed_at(item),
                cost_source="anthropic cost report endpoint",
                raw_payload=item,
            )
        )
    return rows


def _payload_items(payload: dict[str, Any], *, key: str | None = None) -> list[dict[str, Any]]:
    value = payload.get(key) if key else payload.get("data", payload.get("items", payload.get("results", [])))
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _next_page_cursor(payload: dict[str, Any]) -> str | None:
    for key in ("next_page", "next_page_cursor", "next_cursor"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _bucket_observed_at(bucket: dict[str, Any]) -> datetime:
    value = bucket.get("start_time") or bucket.get("startTime") or bucket.get("starting_at")
    return _timestamp_value(value)


def _observed_at(item: dict[str, Any]) -> datetime:
    for key in ("date", "timestamp", "start_time", "starting_at", "created_at"):
        value = item.get(key)
        if value is not None:
            return _timestamp_value(value)
    return datetime.now(UTC)


def _timestamp_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.now(UTC)
            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return datetime.fromtimestamp(numeric, tz=UTC)
    return datetime.now(UTC)


def _amount_value(item: dict[str, Any]) -> Decimal:
    amount = item.get("amount") or item.get("cost") or item.get("cost_usd") or item.get("amount_usd")
    if isinstance(amount, dict):
        amount = amount.get("value") or amount.get("amount")
    try:
        return Decimal(str(amount or "0"))
    except Exception:
        return Decimal("0")


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
