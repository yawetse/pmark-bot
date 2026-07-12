"""AWS billing adapter helpers.

REQ: REQ-UI-010, REQ-OBS-005, REQ-DEP-002
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain import Environment

try:  # pragma: no cover - import availability is environment-specific
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    boto3 = Config = None
    BotoCoreError = ClientError = Exception


DEFAULT_COST_EXPLORER_TIMEOUT_SECONDS = 3.0
DEFAULT_COST_EXPLORER_CACHE_TTL_SECONDS = 300
DEFAULT_COST_EXPLORER_MAX_ATTEMPTS = 1


class BillingUnavailableError(RuntimeError):
    """Expected billing import failure that should not break the dashboard."""


@dataclass(frozen=True)
class AwsBillingCost:
    """Cost Explorer result rendered by the dashboard.

    REQ: REQ-UI-010
    """

    daily_cost_usd: Decimal
    month_to_date_cost_usd: Decimal
    daily_start: date
    daily_end: date
    month_start: date
    month_end: date
    estimated: bool
    source: str
    scope: str
    message: str


class CostExplorerBillingAdapter:
    """Read dashboard AWS cost data from Cost Explorer.

    REQ: REQ-UI-010, REQ-OBS-005
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        region_name: str = "us-east-1",
        project_tag_key: str = "Project",
        project_tag_value: str = "codex-poly-bot",
        environment_tag_key: str = "Environment",
        fallback_to_account: bool = True,
        timeout_seconds: float = DEFAULT_COST_EXPLORER_TIMEOUT_SECONDS,
        cache_ttl_seconds: int = DEFAULT_COST_EXPLORER_CACHE_TTL_SECONDS,
        max_attempts: int = DEFAULT_COST_EXPLORER_MAX_ATTEMPTS,
    ) -> None:
        if client is None and boto3 is None:
            raise BillingUnavailableError("boto3 is not installed")
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self.cache_ttl_seconds = max(0, int(cache_ttl_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.client = client or boto3.client(
            "ce",
            region_name=region_name,
            config=Config(
                connect_timeout=self.timeout_seconds,
                read_timeout=self.timeout_seconds,
                retries={"max_attempts": self.max_attempts, "mode": "standard"},
            ),
        )
        self.project_tag_key = project_tag_key
        self.project_tag_value = project_tag_value
        self.environment_tag_key = environment_tag_key
        self.fallback_to_account = fallback_to_account
        self._cache: dict[tuple[str, date], tuple[datetime, AwsBillingCost]] = {}

    def dashboard_costs(
        self,
        *,
        environment: Environment,
        now: datetime | None = None,
    ) -> AwsBillingCost:
        """Return current-day and month-to-date Cost Explorer totals.

        REQ: REQ-UI-010
        """

        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        current = current_time.date()
        cached = self._cached_cost(environment=environment, current=current, now=current_time)
        if cached is not None:
            return cached
        next_day = current + timedelta(days=1)
        month_start = current.replace(day=1)
        tag_filter = self._tag_filter(environment)

        try:
            daily, daily_estimated = self._cost_for_period(current, next_day, tag_filter)
            month, month_estimated = self._cost_for_period(month_start, next_day, tag_filter)
        except BillingUnavailableError:
            if not self.fallback_to_account:
                raise
        else:
            if daily > 0 or month > 0 or not self.fallback_to_account:
                return self._cache_cost(
                    environment=environment,
                    current=current,
                    now=current_time,
                    cost=AwsBillingCost(
                        daily_cost_usd=daily,
                        month_to_date_cost_usd=month,
                        daily_start=current,
                        daily_end=next_day,
                        month_start=month_start,
                        month_end=next_day,
                        estimated=daily_estimated or month_estimated,
                        source="aws cost explorer",
                        scope="tagged",
                        message=(
                            "Cost Explorer returned AWS cost for "
                            f"{self.project_tag_key}={self.project_tag_value} and "
                            f"{self.environment_tag_key}={environment.value}."
                        ),
                    ),
                )

        daily, daily_estimated = self._cost_for_period(current, next_day, None)
        month, month_estimated = self._cost_for_period(month_start, next_day, None)
        return self._cache_cost(
            environment=environment,
            current=current,
            now=current_time,
            cost=AwsBillingCost(
                daily_cost_usd=daily,
                month_to_date_cost_usd=month,
                daily_start=current,
                daily_end=next_day,
                month_start=month_start,
                month_end=next_day,
                estimated=daily_estimated or month_estimated,
                source="aws cost explorer",
                scope="account",
                message=(
                    "Cost Explorer returned account-level AWS cost. Project tags are used "
                    "when cost allocation data is available."
                ),
            ),
        )

    def _cached_cost(
        self,
        *,
        environment: Environment,
        current: date,
        now: datetime,
    ) -> AwsBillingCost | None:
        if self.cache_ttl_seconds <= 0:
            return None
        cached = self._cache.get((environment.value, current))
        if cached is None:
            return None
        cached_at, cost = cached
        if now - cached_at <= timedelta(seconds=self.cache_ttl_seconds):
            return cost
        self._cache.pop((environment.value, current), None)
        return None

    def _cache_cost(
        self,
        *,
        environment: Environment,
        current: date,
        now: datetime,
        cost: AwsBillingCost,
    ) -> AwsBillingCost:
        if self.cache_ttl_seconds > 0:
            self._cache[(environment.value, current)] = (now, cost)
        return cost

    def _tag_filter(self, environment: Environment) -> dict[str, Any]:
        return {
            "And": [
                {
                    "Tags": {
                        "Key": self.project_tag_key,
                        "Values": [self.project_tag_value],
                        "MatchOptions": ["EQUALS"],
                    }
                },
                {
                    "Tags": {
                        "Key": self.environment_tag_key,
                        "Values": [environment.value],
                        "MatchOptions": ["EQUALS"],
                    }
                },
            ]
        }

    def _cost_for_period(
        self,
        start: date,
        end: date,
        filter_expression: dict[str, Any] | None,
    ) -> tuple[Decimal, bool]:
        request: dict[str, Any] = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
        }
        if filter_expression is not None:
            request["Filter"] = filter_expression
        try:
            response = self.client.get_cost_and_usage(**request)
        except (BotoCoreError, ClientError, ValueError) as exc:
            raise BillingUnavailableError(str(exc)) from exc

        amount = Decimal("0")
        estimated = False
        for item in response.get("ResultsByTime", ()):
            estimated = estimated or bool(item.get("Estimated"))
            metric = item.get("Total", {}).get("UnblendedCost", {})
            amount += _decimal(metric.get("Amount", "0"))
        return amount, estimated


def billing_adapter_from_env(
    runtime_env: dict[str, str],
) -> CostExplorerBillingAdapter | None:
    """Build the deployed Cost Explorer adapter when enabled.

    REQ: REQ-UI-010, REQ-DEP-002
    """

    if not _bool_env(runtime_env.get("AWS_COST_EXPLORER_ENABLED"), default=False):
        return None
    return CostExplorerBillingAdapter(
        region_name=runtime_env.get("AWS_COST_EXPLORER_REGION", "us-east-1"),
        project_tag_key=runtime_env.get("AWS_COST_EXPLORER_PROJECT_TAG", "Project"),
        project_tag_value=runtime_env.get("AWS_COST_EXPLORER_PROJECT_VALUE", "codex-poly-bot"),
        environment_tag_key=runtime_env.get("AWS_COST_EXPLORER_ENVIRONMENT_TAG", "Environment"),
        fallback_to_account=_bool_env(
            runtime_env.get("AWS_COST_EXPLORER_ACCOUNT_FALLBACK"),
            default=True,
        ),
        timeout_seconds=_float_env(
            runtime_env.get("AWS_COST_EXPLORER_TIMEOUT_SECONDS"),
            DEFAULT_COST_EXPLORER_TIMEOUT_SECONDS,
        ),
        cache_ttl_seconds=_int_env(
            runtime_env.get("AWS_COST_EXPLORER_CACHE_TTL_SECONDS"),
            DEFAULT_COST_EXPLORER_CACHE_TTL_SECONDS,
        ),
        max_attempts=_int_env(
            runtime_env.get("AWS_COST_EXPLORER_MAX_ATTEMPTS"),
            DEFAULT_COST_EXPLORER_MAX_ATTEMPTS,
        ),
    )


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BillingUnavailableError("Cost Explorer amount must be decimal") from exc
    if not parsed.is_finite():
        raise BillingUnavailableError("Cost Explorer amount must be finite")
    return parsed


def _bool_env(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _int_env(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
