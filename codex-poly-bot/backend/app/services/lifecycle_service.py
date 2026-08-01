"""Pipeline execution and exit orchestration.

REQ: REQ-EXE-004, REQ-EXE-005, REQ-EXE-006, REQ-EXE-009,
REQ-EXE-010, REQ-EXE-013, REQ-EXE-014, REQ-EXE-016,
REQ-EXT-001, REQ-EXT-002, REQ-EXT-003, REQ-EXT-004,
REQ-EXT-005, REQ-EXT-006, REQ-ALP-005, REQ-ALP-006,
REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from hashlib import sha256
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.domain import (
    Environment,
    ExitTrigger,
    ExitTriggerType,
    Instrument,
    InstrumentType,
    ModelProvider,
    OrderEvent,
    OrderEventType,
    OrderSide,
    OrderType,
    PositionSnapshot,
    PositionState,
    Venue,
)
from app.services.execution_service import (
    AlpacaExecutionRequest,
    AlpacaVenueSubmitter,
    PolymarketPositionCloser,
    PolymarketExecutionRequest,
    PolymarketVenueSubmitter,
    execute_alpaca_order,
    execute_polymarket_order,
)
from app.services.exit_service import (
    ExitExecutionRequest,
    ExitExecutionResult,
    evaluate_profit_target_exit,
    evaluate_stale_thesis_exit,
    evaluate_volume_spike_exit,
    execute_exit_order,
)
from app.services.risk_engine import (
    AlpacaRiskInput,
    LiveOrderGateInput,
    PolymarketRiskInput,
    RiskLimitResult,
    default_alpaca_risk_config,
    default_polymarket_risk_config,
    evaluate_alpaca_risk_limits,
    evaluate_live_order_gates,
    evaluate_polymarket_risk_limits,
)
from app.services.notification_service import (
    NotificationDeliveryLedger,
    NotificationSettings,
    TradePlacedAlert,
    send_trade_placed_alert,
)
from app.venues.polymarket import PolymarketLiveOrderRequest, VenueCallResult


DEFAULT_EXECUTION_CONFIG: dict[str, Any] = {
    "market_data_freshness_seconds": 300,
    "order_type": OrderType.MARKET.value,
    "alpaca": {
        "model_capital_usd": "1000.00",
    },
}

DEFAULT_EXIT_CONFIG: dict[str, Any] = {
    "polymarket": {
        "profit_target_usd": "5.00",
        "profit_target_pct": "0.25",
        "volume_spike_multiplier": "3.00",
        "max_thesis_age_hours": "72",
        "min_stale_price_move_pct": "0.10",
    },
    "alpaca": {
        "profit_target_pct": "0.02",
        "stop_loss_pct": "0.01",
        "trailing_stop_pct": "0.01",
        "max_position_age_hours": "6",
        "min_stale_price_move_pct": "0.005",
        "market_hours_only": True,
        "close_before_market_close_minutes": 15,
    },
}

TERMINAL_ORDER_STATUSES = {"refused", "simulated", "filled", "canceled", "failed"}


@dataclass(frozen=True)
class LifecycleRunResult:
    """Dashboard-ready lifecycle run result."""

    payload: dict[str, Any]


class PipelineLifecycleService:
    """Convert consensus outputs into order intents and monitor exits."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        alpaca_submitter: AlpacaVenueSubmitter | None = None,
        alpaca_submitters: Mapping[ModelProvider, AlpacaVenueSubmitter] | None = None,
        polymarket_submitter: PolymarketVenueSubmitter | None = None,
        polymarket_submitters: Mapping[ModelProvider, PolymarketVenueSubmitter] | None = None,
        alpaca_exit_submitter: AlpacaVenueSubmitter | None = None,
        polymarket_position_closer: PolymarketPositionCloser | None = None,
        notification_adapter: Any | None = None,
        notification_ledger: NotificationDeliveryLedger | None = None,
    ) -> None:
        self.registry = registry
        self.alpaca_submitter = alpaca_submitter
        self.polymarket_submitter = polymarket_submitter
        self.alpaca_exit_submitter = alpaca_exit_submitter or alpaca_submitter
        self.polymarket_position_closer = polymarket_position_closer
        self._alpaca_submitter_map_configured = alpaca_submitters is not None
        self._polymarket_submitter_map_configured = polymarket_submitters is not None
        self.alpaca_submitters = dict(alpaca_submitters or {})
        self.polymarket_submitters = dict(polymarket_submitters or {})
        if alpaca_submitter is not None and not self._alpaca_submitter_map_configured:
            for provider in ModelProvider:
                self.alpaca_submitters.setdefault(provider, alpaca_submitter)
        if polymarket_submitter is not None and not self._polymarket_submitter_map_configured:
            for provider in ModelProvider:
                self.polymarket_submitters.setdefault(provider, polymarket_submitter)
        self.notification_adapter = notification_adapter
        self.notification_ledger = notification_ledger or NotificationDeliveryLedger()

    def run_execution(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        trigger: str,
        strategy_run: dict[str, Any],
        market_data_pulls: list[dict[str, Any]],
        config_payload: dict[str, Any],
        credential_status: dict[str, bool] | None = None,
        kill_switch_active: bool = False,
        started_at: datetime,
        completed_at: datetime,
    ) -> LifecycleRunResult:
        """Persist order intents and route approved orders through execution helpers."""

        config = execution_config_from_payload(config_payload)
        run_row = self.registry.shared().record_execution_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            strategy_consensus_run_id=strategy_run.get("id"),
            trigger=trigger,
            status="running",
            config=config,
            intent_count=0,
            submitted_count=0,
            simulated_count=0,
            refused_count=0,
            reconciliation_count=0,
            started_at=started_at,
            completed_at=completed_at,
        )
        approved_outputs = self._approved_strategy_outputs(environment, strategy_run)
        market_candidates = _market_candidates_by_key(market_data_pulls)
        credentials = credential_status or {}
        intents: list[dict[str, Any]] = []

        for output in approved_outputs:
            intent = self._record_order_intent(
                environment=environment,
                pipeline_run_id=pipeline_run_id,
                execution_run_id=run_row["id"],
                output=output,
                market_candidates=market_candidates,
                market_data_pulls=market_data_pulls,
                config_payload=config_payload,
                config=config,
                credentials=credentials,
                kill_switch_active=kill_switch_active,
                created_at=completed_at,
            )
            intents.append(intent)

        submitted_count = sum(1 for intent in intents if intent["status"] == "submitted")
        simulated_count = sum(1 for intent in intents if intent["status"] == "simulated")
        refused_count = sum(1 for intent in intents if intent["status"] == "refused")
        reconciliation_count = sum(1 for intent in intents if intent["status"] == "reconcile_first")
        run_row = self.registry.shared().update_execution_run_result(
            execution_run_id=run_row["id"],
            status=_lifecycle_run_status(
                source_count=len(approved_outputs),
                action_count=len(intents),
                submitted_count=submitted_count,
                simulated_count=simulated_count,
                refused_count=refused_count,
            ),
            intent_count=len(intents),
            submitted_count=submitted_count,
            simulated_count=simulated_count,
            refused_count=refused_count,
            reconciliation_count=reconciliation_count,
            completed_at=completed_at,
        )
        return LifecycleRunResult(payload=execution_run_payload(run_row, intents))

    def run_exit(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        trigger: str,
        market_data_pulls: list[dict[str, Any]],
        config_payload: dict[str, Any],
        kill_switch_active: bool = False,
        started_at: datetime,
        completed_at: datetime,
    ) -> LifecycleRunResult:
        """Evaluate open positions and persist exit intents."""

        config = exit_config_from_payload(config_payload)
        run_row = self.registry.shared().record_exit_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            trigger=trigger,
            status="running",
            config=config,
            open_position_count=0,
            triggered_count=0,
            simulated_count=0,
            submitted_count=0,
            refused_count=0,
            started_at=started_at,
            completed_at=completed_at,
        )
        market_candidates = _market_candidates_by_key(market_data_pulls)
        positions = self._open_positions(environment, config_payload=config_payload)
        intents: list[dict[str, Any]] = []
        for position in positions:
            triggers = self._exit_triggers_for_position(
                position=position,
                market_candidates=market_candidates,
                config=config,
                now=completed_at,
            )
            exit_trigger = _primary_exit_trigger(triggers)
            if exit_trigger is not None:
                intents.append(
                    self._record_exit_intent(
                        environment=environment,
                        pipeline_run_id=pipeline_run_id,
                        exit_run_id=run_row["id"],
                        position=position,
                        exit_trigger=exit_trigger,
                        config_payload=config_payload,
                        kill_switch_active=kill_switch_active,
                        created_at=completed_at,
                    )
                )

        submitted_count = sum(1 for intent in intents if intent["status"] == "submitted")
        simulated_count = sum(1 for intent in intents if intent["status"] == "simulated")
        refused_count = sum(1 for intent in intents if intent["status"] == "refused")
        run_row = self.registry.shared().update_exit_run_result(
            exit_run_id=run_row["id"],
            status=_exit_run_status(
                open_position_count=len(positions),
                triggered_count=len(intents),
                submitted_count=submitted_count,
                simulated_count=simulated_count,
                refused_count=refused_count,
            ),
            open_position_count=len(positions),
            triggered_count=len(intents),
            simulated_count=simulated_count,
            submitted_count=submitted_count,
            refused_count=refused_count,
            completed_at=completed_at,
        )
        return LifecycleRunResult(payload=exit_run_payload(run_row, intents))

    def _approved_strategy_outputs(
        self,
        environment: Environment,
        strategy_run: dict[str, Any],
    ) -> list[dict[str, Any]]:
        run_id = strategy_run.get("id")
        if run_id:
            try:
                rows = self.registry.shared().strategy_consensus_outputs(
                    environment=environment,
                    consensus_run_id=str(run_id),
                    status="approved",
                )
                if rows:
                    return rows
            except PersistenceUnavailableError:
                pass
        return [
            output
            for output in strategy_run.get("outputs", [])
            if output.get("status") == "approved"
        ]

    def _record_order_intent(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        execution_run_id: str,
        output: dict[str, Any],
        market_candidates: dict[str, dict[str, Any]],
        market_data_pulls: list[dict[str, Any]],
        config_payload: dict[str, Any],
        config: dict[str, Any],
        credentials: dict[str, bool],
        kill_switch_active: bool,
        created_at: datetime,
    ) -> dict[str, Any]:
        venue = str(output.get("venue") or "")
        side = str(output.get("side") or OrderSide.BUY.value)
        model_provider = _model_provider(output)
        instrument_id = str(output.get("instrument_id") or output.get("instrumentId") or "")
        candidate = _candidate_for_instrument(output, market_candidates)
        notional = self._order_notional(output=output, venue=venue, config_payload=config_payload)
        size_multiplier = _decimal_or_zero(output.get("size_multiplier") or output.get("sizeMultiplier"))
        order_type = str(config["order_type"])
        position_intent = _alpaca_entry_position_intent(venue=venue, side=side)
        account_mode = str(config_payload.get("alpaca", {}).get("account_mode", "paper"))
        expected_account_id = None
        account_ref = "unresolved"
        if venue == Venue.ALPACA.value:
            expected_account_id = self._alpaca_account_id(
                environment=environment,
                account_mode=account_mode,
                model_provider=model_provider,
            )
            if expected_account_id:
                account_ref = _sanitized_alpaca_account_ref(expected_account_id)
        idempotency_key = _idempotency_key(
            "entry",
            environment.value,
            pipeline_run_id,
            str(output.get("id") or instrument_id),
            side,
            position_intent,
            account_mode if venue == Venue.ALPACA.value else "none",
            account_ref if venue == Venue.ALPACA.value else "none",
        )
        existing_intent = self._existing_order_intent(idempotency_key)
        if existing_intent and existing_intent.get("status") not in TERMINAL_ORDER_STATUSES:
            intent = self.registry.shared().record_order_intent(
                environment=environment,
                execution_run_id=execution_run_id,
                pipeline_run_id=pipeline_run_id,
                strategy_consensus_output_id=output.get("id"),
                venue=venue,
                instrument_id=instrument_id,
                model_provider=model_provider,
                side=side,
                order_type=order_type,
                status="reconcile_first",
                notional_usd=notional,
                size_multiplier=size_multiplier,
                idempotency_key=idempotency_key,
                refusal_reason="RECONCILE_EXISTING_ORDER_STATE",
                risk_payload={"existing_status": existing_intent.get("status")},
                source_payload={"existingIntentId": existing_intent.get("id")},
                created_at=created_at,
                updated_at=created_at,
            )
            self._record_order_event(
                environment=environment,
                order_id=intent["idempotency_key"],
                venue=venue,
                model_provider=model_provider,
                status="refused",
                message="order retry blocked until existing intent is reconciled",
            )
            return intent
        risk_result = self._entry_risk_result(
            environment=environment,
            output=output,
            venue=venue,
            side=side,
            notional=notional,
            candidate=candidate,
            market_data_pulls=market_data_pulls,
            config_payload=config_payload,
            config=config,
            credentials=credentials,
            kill_switch_active=kill_switch_active,
            created_at=created_at,
        )
        status = "pending"
        refusal_reason = _refusal_text(risk_result)
        venue_order_id = None
        execution_payload: dict[str, Any] = {}
        if risk_result.approved:
            execution_result = self._execute_entry_order(
                environment=environment,
                venue=venue,
                model_provider=model_provider,
                side=side,
                order_type=order_type,
                instrument_id=instrument_id,
                notional=notional,
                idempotency_key=idempotency_key,
                output=output,
                candidate=candidate,
                config_payload=config_payload,
                position_intent=position_intent,
                expected_account_id=expected_account_id,
            )
            status = execution_result["status"]
            refusal_reason = execution_result.get("refusal_reason")
            venue_order_id = execution_result.get("venue_order_id")
            execution_payload = execution_result.get("payload") or {}
        else:
            status = "refused"

        intent = self.registry.shared().record_order_intent(
            environment=environment,
            execution_run_id=execution_run_id,
            pipeline_run_id=pipeline_run_id,
            strategy_consensus_output_id=output.get("id"),
            venue=venue,
            instrument_id=instrument_id,
            model_provider=model_provider,
            side=side,
            order_type=order_type,
            status=status,
            notional_usd=notional,
            size_multiplier=size_multiplier,
            idempotency_key=idempotency_key,
            refusal_reason=refusal_reason,
            venue_order_id=venue_order_id,
            risk_payload=risk_result.payload,
            source_payload={
                "consensusOutput": _json_ready(output),
                "marketCandidate": _json_ready(candidate or {}),
                "executionResult": _json_ready(execution_payload),
                "positionIntent": position_intent,
                "accountMode": account_mode if venue == Venue.ALPACA.value else None,
                "accountRef": account_ref if venue == Venue.ALPACA.value else None,
            },
            created_at=created_at,
            updated_at=created_at,
        )
        self._record_order_event(
            environment=environment,
            order_id=intent["idempotency_key"],
            venue=venue,
            model_provider=model_provider,
            status=status,
            message=_order_event_message(status, refusal_reason),
        )
        if status == "submitted":
            self._send_trade_placed_notification(
                config_payload=config_payload,
                trade=TradePlacedAlert(
                    venue=venue,
                    side=side,
                    instrument_id=instrument_id,
                    order_type=order_type,
                    notional_usd=notional,
                    venue_order_id=venue_order_id,
                    idempotency_key=idempotency_key,
                    reason="entry order submitted",
                ),
                now=created_at,
            )
        return intent

    def _existing_order_intent(self, idempotency_key: str) -> dict[str, Any] | None:
        try:
            rows = self.registry.state.rows("shared.order_intents")
        except PersistenceUnavailableError:
            return None
        for row in rows:
            if row.get("idempotency_key") == idempotency_key:
                return row
        return None

    def _entry_risk_result(
        self,
        *,
        environment: Environment,
        output: dict[str, Any],
        venue: str,
        side: str,
        notional: Decimal,
        candidate: dict[str, Any] | None,
        market_data_pulls: list[dict[str, Any]],
        config_payload: dict[str, Any],
        config: dict[str, Any],
        credentials: dict[str, bool],
        kill_switch_active: bool,
        created_at: datetime,
    ) -> RiskLimitResult:
        if venue == Venue.ALPACA.value:
            venue_risk = evaluate_alpaca_risk_limits(
                AlpacaRiskInput(
                    proposed_notional=notional,
                    projected_symbol_exposure=notional,
                    daily_loss=self._daily_loss(
                        environment,
                        Venue.ALPACA.value,
                        created_at,
                        config_payload=config_payload,
                    ),
                    open_positions=self._open_position_count(
                        environment,
                        Venue.ALPACA.value,
                        config_payload=config_payload,
                    ),
                    creates_new_position=True,
                    model_capital=str(config["alpaca"]["model_capital_usd"]),
                ),
                config=default_alpaca_risk_config(config_payload),
            )
        else:
            venue_risk = evaluate_polymarket_risk_limits(
                PolymarketRiskInput(
                    proposed_notional=notional,
                    daily_loss=self._daily_loss(
                        environment,
                        venue,
                        created_at,
                        config_payload=config_payload,
                    ),
                    open_positions=self._open_position_count(
                        environment,
                        venue,
                        config_payload=config_payload,
                    ),
                    creates_new_position=True,
                ),
                config=default_polymarket_risk_config(config_payload),
            )
        reasons = list(venue_risk.refusal_reasons)
        if venue == Venue.ALPACA.value and side != OrderSide.BUY.value:
            if side != OrderSide.SELL.value:
                reasons.append("ALPACA_ENTRY_SIDE_UNSUPPORTED")
            elif not bool(config_payload.get("alpaca", {}).get("allow_shorting", False)):
                reasons.append("ALPACA_SHORTING_DISABLED")
        if venue == Venue.ALPACA.value:
            symbol = _symbol_from_instrument(str(output.get("instrument_id") or ""), candidate)
            account_mode = str(config_payload.get("alpaca", {}).get("account_mode", "paper"))
            try:
                account_quarantined = (
                    self.registry.shared().alpaca_provider_has_quarantined_account(
                        environment=environment,
                        account_mode=account_mode,
                        model_provider=_model_provider(output),
                    )
                )
            except PersistenceUnavailableError:
                account_quarantined = True
            if account_quarantined:
                reasons.append("ALPACA_ACCOUNT_QUARANTINED")
            if self._alpaca_entry_state_exists(
                environment=environment,
                symbol=symbol,
                account_mode=account_mode,
            ):
                reasons.append("ALPACA_ENTRY_POSITION_EXISTS")
            if side == OrderSide.SELL.value and bool(
                config_payload.get("alpaca", {}).get("allow_shorting", False)
            ):
                reconciliation_refusal = self._alpaca_reconciliation_refusal(
                    environment=environment,
                    account_mode=account_mode,
                    model_provider=_model_provider(output),
                    now=created_at,
                    max_freshness_seconds=max(
                        1,
                        int(config.get("market_data_freshness_seconds", 300)),
                    ),
                )
                if reconciliation_refusal:
                    reasons.append(reconciliation_refusal)
        if venue == Venue.ALPACA.value and side != OrderSide.SELL.value:
            reasons.extend(_alpaca_entry_time_refusals(created_at, config_payload))
        if kill_switch_active:
            reasons.append("KILL_SWITCH_ACTIVE")
        if not _market_data_is_fresh(candidate, market_data_pulls, config, created_at):
            reasons.append("STALE_MARKET_DATA")
        if not _slippage_ok(venue=venue, candidate=candidate, config_payload=config_payload):
            reasons.append("SLIPPAGE_LIMIT")
        execution_mode = _execution_mode(config_payload)
        if execution_mode == "live":
            credentials_present = _credentials_present(
                credentials,
                venue=venue,
                model_provider=_model_provider(output),
            )
            live_gates = evaluate_live_order_gates(
                LiveOrderGateInput(
                    live_enabled=bool(config_payload.get("live_enabled", False)),
                    venue_enabled=bool(
                        config_payload.get("venues", {}).get(venue, {}).get("enabled", False)
                    ),
                    credentials_present=credentials_present,
                    venue_config_supported=True,
                    market_data_fresh="STALE_MARKET_DATA" not in reasons,
                    scoring_succeeded=True,
                    risk_approved=venue_risk.approved,
                    account_mode_valid=_account_mode_valid(venue, config_payload),
                    kill_switch_active=kill_switch_active,
                    risk_refusal_reason=venue_risk.refusal_reason,
                )
            )
            reasons.extend(live_gates.refusal_reasons)
        return RiskLimitResult(
            approved=not reasons,
            refusal_reasons=tuple(dict.fromkeys(reasons)),
            payload={
                **venue_risk.payload,
                "execution_mode": execution_mode,
                "side": side,
                "notional_usd": str(notional),
                "market_data_fresh": "STALE_MARKET_DATA" not in reasons,
                "slippage_ok": "SLIPPAGE_LIMIT" not in reasons,
                "kill_switch_active": kill_switch_active,
            },
        )

    def _execute_entry_order(
        self,
        *,
        environment: Environment,
        venue: str,
        model_provider: ModelProvider,
        side: str,
        order_type: str,
        instrument_id: str,
        notional: Decimal,
        idempotency_key: str,
        output: dict[str, Any],
        candidate: dict[str, Any] | None,
        config_payload: dict[str, Any],
        position_intent: str,
        expected_account_id: str | None,
    ) -> dict[str, Any]:
        execution_mode = _execution_mode(config_payload)
        if venue == Venue.ALPACA.value:
            alpaca_submitter = self._alpaca_submitter_for(model_provider)
            if execution_mode == "live" and alpaca_submitter is None:
                return {
                    "status": "refused",
                    "refusal_reason": "LIVE_SUBMITTER_NOT_CONFIGURED",
                }
            account_mode = str(config_payload.get("alpaca", {}).get("account_mode", "paper"))
            if execution_mode == "live":
                try:
                    account_quarantined = (
                        self.registry.shared().alpaca_provider_has_quarantined_account(
                            environment=environment,
                            account_mode=account_mode,
                            model_provider=model_provider,
                        )
                    )
                except PersistenceUnavailableError:
                    account_quarantined = True
                if account_quarantined:
                    return {
                        "status": "refused",
                        "refusal_reason": "ALPACA_ACCOUNT_QUARANTINED",
                    }
            candidate_price = _candidate_price(candidate)
            is_short_entry = position_intent == "sell_to_open"
            quantity = None
            execution_notional: Decimal | None = notional
            if is_short_entry:
                if not expected_account_id:
                    return {
                        "status": "refused",
                        "refusal_reason": "ALPACA_SHORT_ACCOUNT_UNRESOLVED",
                    }
                candidate_price = _candidate_short_reference_price(candidate)
                if candidate_price is None or candidate_price <= 0:
                    return {
                        "status": "refused",
                        "refusal_reason": "ALPACA_SHORT_PRICE_UNAVAILABLE",
                    }
                quantity = (notional / candidate_price).to_integral_value(rounding=ROUND_FLOOR)
                if quantity < 1:
                    return {
                        "status": "refused",
                        "refusal_reason": "ALPACA_SHORT_SIZE_BELOW_ONE_SHARE",
                    }
                execution_notional = None
            result = execute_alpaca_order(
                AlpacaExecutionRequest(
                    global_execution_mode=execution_mode,
                    account_mode=account_mode,
                    risk_approved=True,
                    symbol=_symbol_from_instrument(instrument_id, candidate),
                    notional=execution_notional,
                    quantity=quantity,
                    side=side,
                    position_intent=position_intent if is_short_entry else None,
                    estimated_unit_price=candidate_price if is_short_entry else None,
                    expected_account_id=expected_account_id if is_short_entry else None,
                    entry_cutoff_minutes=(
                        int(
                            config_payload.get("exit", {})
                            .get("alpaca", {})
                            .get("close_before_market_close_minutes", 15)
                        )
                        if is_short_entry
                        else None
                    ),
                    max_quote_age_seconds=(
                        int(
                            config_payload.get("execution", {}).get(
                                "market_data_freshness_seconds",
                                300,
                            )
                        )
                        if is_short_entry
                        else None
                    ),
                    client_order_id=idempotency_key,
                ),
                submitter=alpaca_submitter or _NoopAlpacaSubmitter(),
            )
            return {
                "status": result.status,
                "refusal_reason": result.refusal_reason,
                "venue_order_id": result.payload.get("venue_order_id"),
                "payload": result.payload,
            }
        polymarket_submitter = self._polymarket_submitter_for(model_provider)
        if execution_mode == "live" and polymarket_submitter is None:
            return {
                "status": "refused",
                "refusal_reason": "LIVE_SUBMITTER_NOT_CONFIGURED",
            }
        request = _polymarket_order_request(
            side=side,
            order_type=order_type,
            instrument_id=instrument_id,
            notional=notional,
            output=output,
            candidate=candidate,
        )
        result = execute_polymarket_order(
            PolymarketExecutionRequest(
                global_execution_mode=execution_mode,
                risk_approved=True,
                order=request,
            ),
            submitter=polymarket_submitter or _NoopPolymarketSubmitter(),
        )
        return {
            "status": result.status,
            "refusal_reason": result.refusal_reason,
            "venue_order_id": result.payload.get("venue_order_id"),
            "payload": result.payload,
        }

    def _alpaca_entry_state_exists(
        self,
        *,
        environment: Environment,
        symbol: str,
        account_mode: str | None = None,
    ) -> bool:
        if not symbol:
            return True
        if any(
            position.get("symbol") == symbol
            for position in self._open_alpaca_positions(environment, account_mode=account_mode)
        ):
            return True
        try:
            rows = self.registry.state.rows("shared.order_intents")
        except PersistenceUnavailableError:
            return True
        instrument_ids = {symbol.upper(), f"ALPACA:{symbol.upper()}"}
        for row in rows:
            source_payload = (
                row.get("source_payload")
                if isinstance(row.get("source_payload"), Mapping)
                else {}
            )
            if (
                row.get("environment") == environment.value
                and row.get("venue") == Venue.ALPACA.value
                and str(row.get("instrument_id") or "").upper() in instrument_ids
                and (
                    account_mode is None
                    or str(source_payload.get("accountMode") or account_mode) == account_mode
                )
                and str(row.get("status") or "") not in TERMINAL_ORDER_STATUSES
            ):
                return True
        return False

    def _alpaca_account_id(
        self,
        *,
        environment: Environment,
        account_mode: str,
        model_provider: ModelProvider,
    ) -> str:
        try:
            rows = self.registry.shared().alpaca_account_registrations(
                environment=environment,
                account_mode=account_mode,
                model_provider=model_provider,
            )
        except PersistenceUnavailableError:
            return ""
        if not rows:
            return ""
        latest = max(rows, key=lambda row: _datetime_or_min(row.get("created_at")))
        if latest.get("live_trading_allowed") is not True:
            return ""
        return str(latest.get("account_id") or "").strip()

    def _alpaca_reconciliation_refusal(
        self,
        *,
        environment: Environment,
        account_mode: str,
        model_provider: ModelProvider,
        now: datetime,
        max_freshness_seconds: int,
    ) -> str | None:
        account_id = self._alpaca_account_id(
            environment=environment,
            account_mode=account_mode,
            model_provider=model_provider,
        )
        if not account_id:
            return "ALPACA_RECONCILIATION_REQUIRED"
        try:
            rows = [
                row
                for row in self.registry.state.rows(
                    f"{model_provider.value}.alpaca_account_snapshots"
                )
                if row.get("environment") == environment.value
                and row.get("account_mode") == account_mode
                and row.get("account_id") == account_id
            ]
        except PersistenceUnavailableError:
            return "ALPACA_RECONCILIATION_REQUIRED"
        if not rows:
            return "ALPACA_RECONCILIATION_REQUIRED"
        latest = max(rows, key=lambda row: _datetime_or_min(row.get("observed_at")))
        observed_at = _parse_datetime(latest.get("observed_at"))
        if observed_at is None:
            return "ALPACA_RECONCILIATION_STALE"
        age_seconds = max(0, int((now - observed_at).total_seconds()))
        if age_seconds > max_freshness_seconds:
            return "ALPACA_RECONCILIATION_STALE"
        if latest.get("is_live_safe") is not True:
            return "ALPACA_RECONCILIATION_BLOCKED"
        return None

    def _open_positions(
        self,
        environment: Environment,
        *,
        config_payload: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        positions.extend(self._open_polymarket_positions(environment))
        account_mode = None
        if config_payload is not None:
            alpaca_config = config_payload.get("alpaca", {})
            if isinstance(alpaca_config, Mapping):
                account_mode = str(alpaca_config.get("account_mode") or "paper")
        positions.extend(self._open_alpaca_positions(environment, account_mode=account_mode))
        return positions

    def _alpaca_submitter_for(self, provider: ModelProvider) -> AlpacaVenueSubmitter | None:
        if self._alpaca_submitter_map_configured:
            return self.alpaca_submitters.get(provider)
        return self.alpaca_submitters.get(provider) or self.alpaca_submitter

    def _polymarket_submitter_for(self, provider: ModelProvider) -> PolymarketVenueSubmitter | None:
        if self._polymarket_submitter_map_configured:
            return self.polymarket_submitters.get(provider)
        return self.polymarket_submitters.get(provider) or self.polymarket_submitter

    def _open_polymarket_positions(self, environment: Environment) -> list[dict[str, Any]]:
        try:
            rows = [
                row
                for row in self.registry.state.rows("shared.polymarket_wallet_positions")
                if row["environment"] == environment.value and row["state"] == PositionState.OPEN.value
            ]
        except PersistenceUnavailableError:
            return []
        positions = []
        for row in rows:
            instrument_id = f"{row['market_id']}:{row['asset_id']}"
            positions.append(
                {
                    "position_id": row["id"],
                    "venue": Venue.POLYMARKET_US.value,
                    "instrument_id": instrument_id,
                    "market_id": row["market_id"],
                    "outcome_id": row["asset_id"],
                    "quantity": _decimal_or_zero(row.get("size")),
                    "entry_price": _decimal_or_none(row.get("entry_price")),
                    "current_price": None,
                    "unrealized_pnl": Decimal("0"),
                    "opened_at": row.get("opened_at"),
                    "source": row,
                }
            )
        return positions

    def _open_alpaca_positions(
        self,
        environment: Environment,
        *,
        account_mode: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            rows = self.registry.shared().alpaca_historical_positions(environment=environment)
        except PersistenceUnavailableError:
            return []
        if account_mode:
            rows = [row for row in rows if str(row.get("account_mode") or "") == account_mode]
        try:
            registrations = self.registry.shared().alpaca_account_registrations(
                environment=environment,
                account_mode=account_mode,
            )
        except PersistenceUnavailableError:
            registrations = []
        latest_by_symbol: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            symbol = str(row["symbol"]).upper()
            key = (str(row.get("account_id") or ""), symbol)
            current = latest_by_symbol.get(key)
            if current is None or _datetime_or_min(row.get("observed_at")) > _datetime_or_min(
                current.get("observed_at")
            ):
                latest_by_symbol[key] = row
        positions = []
        for row in latest_by_symbol.values():
            raw_quantity = _decimal_or_zero(row.get("quantity"))
            raw_payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), Mapping) else {}
            raw_side = str(raw_payload.get("side") or "").lower()
            direction_consistent = (
                (raw_side == "short" and raw_quantity <= 0)
                or (raw_side == "long" and raw_quantity >= 0)
            )
            if raw_side == "short":
                signed_quantity = -abs(raw_quantity)
            elif raw_side == "long":
                signed_quantity = abs(raw_quantity)
            else:
                signed_quantity = raw_quantity
            if signed_quantity == 0:
                continue
            symbol = str(row["symbol"]).upper()
            position_side = (
                "short"
                if direction_consistent and signed_quantity < 0
                else "long"
                if direction_consistent and signed_quantity > 0
                else "unknown"
            )
            account_registrations = [
                item
                for item in registrations
                if str(item.get("account_id") or "") == str(row.get("account_id") or "")
                and str(item.get("account_mode") or "") == str(row.get("account_mode") or "")
            ]
            account_quarantined = any(
                item.get("live_trading_allowed") is not True
                for item in account_registrations
            )
            routing = next(
                (
                    item
                    for item in account_registrations
                    if item.get("live_trading_allowed") is True
                ),
                None,
            )
            model_provider = ModelProvider(
                str((routing or {}).get("model_provider") or ModelProvider.OPENAI.value)
            )
            opened_at = self._stock_opened_at(
                environment,
                symbol,
                account_mode=str(row.get("account_mode") or ""),
                account_id=str(row.get("account_id") or ""),
            )
            positions.append(
                {
                    "position_id": row["id"],
                    "venue": Venue.ALPACA.value,
                    "instrument_id": f"alpaca:{symbol}",
                    "symbol": symbol,
                    "quantity": abs(signed_quantity),
                    "signed_quantity": signed_quantity,
                    "position_side": position_side,
                    "model_provider": model_provider,
                    "routing_resolved": (
                        not account_quarantined
                        and (routing is not None or not self._alpaca_submitter_map_configured)
                    ),
                    "account_mode": str(row.get("account_mode") or ""),
                    "account_ref": str(row.get("account_id") or ""),
                    "safe_account_ref": _sanitized_alpaca_account_ref(
                        str(row.get("account_id") or "")
                    ),
                    "entry_price": _decimal_or_none(row.get("average_entry_price")),
                    "current_price": _decimal_or_none(row.get("current_price")),
                    "unrealized_pnl": _decimal_or_zero(row.get("unrealized_pnl_usd")),
                    "opened_at": opened_at,
                    "high_watermark_price": _stock_position_high_watermark(
                        rows,
                        symbol=symbol,
                        account_mode=str(row.get("account_mode") or ""),
                        account_id=str(row.get("account_id") or ""),
                        opened_at=opened_at,
                        position_side=position_side,
                    ),
                    "source": row,
                }
            )
        return positions

    def _stock_opened_at(
        self,
        environment: Environment,
        symbol: str,
        *,
        account_mode: str = "",
        account_id: str = "",
    ) -> datetime | None:
        try:
            fills = [
                row
                for row in self.registry.shared().alpaca_historical_fills(environment=environment)
                if row["symbol"] == symbol.upper()
                and (not account_mode or str(row.get("account_mode") or "") == account_mode)
                and (not account_id or str(row.get("account_id") or "") == account_id)
            ]
        except PersistenceUnavailableError:
            return None
        if not fills:
            return None
        return _current_stock_position_opened_at(fills)

    def _exit_triggers_for_position(
        self,
        *,
        position: dict[str, Any],
        market_candidates: dict[str, dict[str, Any]],
        config: dict[str, Any],
        now: datetime,
    ) -> list[ExitTrigger]:
        if position["venue"] == Venue.ALPACA.value:
            return _stock_exit_triggers(position=position, config=config["alpaca"], now=now)
        candidate = market_candidates.get(position["instrument_id"])
        return _polymarket_exit_triggers(
            position=position,
            candidate=candidate,
            config=config["polymarket"],
            now=now,
            wallet_benchmark=self._target_wallet_exit_benchmark(),
        )

    def _record_exit_intent(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        exit_run_id: str,
        position: dict[str, Any],
        exit_trigger: ExitTrigger,
        config_payload: dict[str, Any],
        kill_switch_active: bool,
        created_at: datetime,
    ) -> dict[str, Any]:
        venue = position["venue"]
        exit_side = _alpaca_exit_side(position) if venue == Venue.ALPACA.value else OrderSide.SELL.value
        model_provider = _position_model_provider(position)
        idempotency_key = _idempotency_key(
            "exit",
            environment.value,
            _exit_position_identity(position),
        )
        existing_submission = next(
            (
                intent
                for intent in self.registry.shared().exit_intents(
                    environment=environment,
                    status="submitted",
                )
                if intent.get("idempotency_key") == idempotency_key
            ),
            None,
        )
        if existing_submission is not None:
            return self.registry.shared().record_exit_intent(
                environment=environment,
                exit_run_id=exit_run_id,
                pipeline_run_id=pipeline_run_id,
                venue=venue,
                instrument_id=position["instrument_id"],
                position_id=position["position_id"],
                trigger_type=exit_trigger.trigger_type.value,
                status="submitted",
                side=exit_side,
                quantity=position.get("quantity"),
                notional_usd=_position_notional(position),
                threshold=exit_trigger.threshold,
                observed_value=exit_trigger.observed_value,
                idempotency_key=idempotency_key,
                refusal_reason=None,
                venue_order_id=existing_submission.get("venue_order_id"),
                source_payload={
                    "position": _exit_source_payload(position),
                    "triggerReason": exit_trigger.reason,
                    "executionMode": _execution_mode(config_payload),
                    "reusedSubmittedExit": True,
                },
                created_at=existing_submission.get("created_at") or created_at,
                updated_at=created_at,
            )
        execution_mode = _execution_mode(config_payload)
        risk_approved = not kill_switch_active
        refusal_reason = "KILL_SWITCH_ACTIVE" if kill_switch_active else None
        if venue == Venue.ALPACA.value and config_payload.get("exit", {}).get("alpaca", {}).get(
            "market_hours_only",
            DEFAULT_EXIT_CONFIG["alpaca"]["market_hours_only"],
        ):
            if not _is_market_hours(created_at):
                risk_approved = False
                refusal_reason = "OUTSIDE_MARKET_HOURS"
        if venue == Venue.ALPACA.value and not bool(
            config_payload.get("venues", {}).get("alpaca", {}).get("enabled", False)
        ):
            risk_approved = False
            refusal_reason = "ALPACA_VENUE_DISABLED"
        result = self._execute_exit_order(
            position=position,
            venue=venue,
            execution_mode=execution_mode,
            risk_approved=risk_approved,
            refusal_reason=refusal_reason,
            config_payload=config_payload,
            idempotency_key=idempotency_key,
        )
        status = result.status
        notional = _position_notional(position)
        intent = self.registry.shared().record_exit_intent(
            environment=environment,
            exit_run_id=exit_run_id,
            pipeline_run_id=pipeline_run_id,
            venue=venue,
            instrument_id=position["instrument_id"],
            position_id=position["position_id"],
            trigger_type=exit_trigger.trigger_type.value,
            status=status,
            side=exit_side,
            quantity=position.get("quantity"),
            notional_usd=notional,
            threshold=exit_trigger.threshold,
            observed_value=exit_trigger.observed_value,
            idempotency_key=idempotency_key,
            refusal_reason=result.refusal_reason,
            venue_order_id=result.payload.get("venue_order_id"),
            source_payload={
                "position": _exit_source_payload(position),
                "triggerReason": exit_trigger.reason,
                "executionMode": execution_mode,
                "positionSide": position.get("position_side"),
                "modelProvider": model_provider.value,
                "accountMode": position.get("account_mode"),
                "accountRef": position.get("safe_account_ref"),
            },
            created_at=created_at,
            updated_at=created_at,
        )
        self._record_order_event(
            environment=environment,
            order_id=idempotency_key,
            venue=venue,
            model_provider=model_provider,
            status=status,
            message=_exit_event_message(status, exit_trigger, result.refusal_reason),
        )
        if status == "submitted":
            self._send_trade_placed_notification(
                config_payload=config_payload,
                trade=TradePlacedAlert(
                    venue=venue,
                    side=exit_side,
                    instrument_id=position["instrument_id"],
                    order_type=OrderType.MARKET.value,
                    notional_usd=notional,
                    quantity=position.get("quantity"),
                    venue_order_id=result.payload.get("venue_order_id"),
                    idempotency_key=idempotency_key,
                    reason=f"exit submitted after {exit_trigger.trigger_type.value}",
                ),
                now=created_at,
            )
        return intent

    def _execute_exit_order(
        self,
        *,
        position: dict[str, Any],
        venue: str,
        execution_mode: str,
        risk_approved: bool,
        refusal_reason: str | None,
        config_payload: dict[str, Any],
        idempotency_key: str,
    ) -> ExitExecutionResult:
        if execution_mode != "live" or not risk_approved:
            return execute_exit_order(
                ExitExecutionRequest(
                    position_id=position["position_id"],
                    venue=Venue(venue),
                    global_execution_mode=execution_mode,
                    risk_approved=risk_approved,
                    risk_refusal_reason=refusal_reason,
                ),
                submitter=_NoopExitSubmitter(),
            )
        if venue == Venue.ALPACA.value:
            if not bool(position.get("routing_resolved", True)):
                return ExitExecutionResult(
                    status="refused",
                    exit_recorded=False,
                    venue_submitted=False,
                    refusal_reason="ALPACA_EXIT_ACCOUNT_UNRESOLVED",
                    payload={"operator_action_required": True},
                )
            position_side = str(position.get("position_side") or "").lower()
            if position_side not in {"long", "short"}:
                return ExitExecutionResult(
                    status="refused",
                    exit_recorded=False,
                    venue_submitted=False,
                    refusal_reason="ALPACA_POSITION_DIRECTION_UNRESOLVED",
                    payload={"operator_action_required": True},
                )
            model_provider = _position_model_provider(position)
            alpaca_exit_submitter = (
                self._alpaca_submitter_for(model_provider)
                if self._alpaca_submitter_map_configured
                else self.alpaca_exit_submitter or self._alpaca_submitter_for(model_provider)
            )
            if alpaca_exit_submitter is None:
                return ExitExecutionResult(
                    status="refused",
                    exit_recorded=False,
                    venue_submitted=False,
                    refusal_reason="LIVE_EXIT_SUBMITTER_NOT_CONFIGURED",
                )
            try:
                submit_kwargs: dict[str, Any] = {
                    "account_mode": str(
                        position.get("account_mode")
                        or config_payload.get("alpaca", {}).get("account_mode", "paper")
                    ),
                    "symbol": str(
                        position.get("symbol")
                        or _symbol_from_instrument(position["instrument_id"], None)
                    ),
                    "quantity": abs(_decimal_or_zero(position.get("quantity"))),
                    "side": "buy" if position_side == "short" else "sell",
                    "client_order_id": idempotency_key,
                }
                if position_side == "short":
                    submit_kwargs["position_intent"] = "buy_to_close"
                if position.get("account_ref"):
                    submit_kwargs["expected_account_id"] = str(position["account_ref"])
                venue_order_id = alpaca_exit_submitter.submit_order(**submit_kwargs)
            except Exception as exc:
                if str(position.get("position_side") or "long") == "short":
                    return ExitExecutionResult(
                        status="refused",
                        exit_recorded=False,
                        venue_submitted=False,
                        refusal_reason="ALPACA_EXACT_COVER_UNAVAILABLE",
                        payload={
                            "operator_action_required": True,
                            **_submit_exception_payload(exc),
                        },
                    )
                return ExitExecutionResult(
                    status="refused",
                    exit_recorded=False,
                    venue_submitted=False,
                    refusal_reason=_submit_exception_reason(exc),
                    payload=_submit_exception_payload(exc),
                )
            return ExitExecutionResult(
                status="submitted",
                exit_recorded=True,
                venue_submitted=True,
                payload={
                    "position_id": position["position_id"],
                    "venue": venue,
                    "venue_order_id": venue_order_id,
                },
            )
        if venue == Venue.POLYMARKET_US.value:
            if self.polymarket_position_closer is None:
                return ExitExecutionResult(
                    status="refused",
                    exit_recorded=False,
                    venue_submitted=False,
                    refusal_reason="LIVE_EXIT_SUBMITTER_NOT_CONFIGURED",
                )
            result = self.polymarket_position_closer.close_position(
                market_slug=_polymarket_position_slug(position),
                current_price=position.get("current_price"),
                slippage_tolerance_bips=_polymarket_exit_slippage_bips(config_payload),
            )
            if not result.ok:
                return ExitExecutionResult(
                    status="refused",
                    exit_recorded=False,
                    venue_submitted=False,
                    refusal_reason=result.refusal_reason,
                    payload=result.payload,
                )
            return ExitExecutionResult(
                status="submitted",
                exit_recorded=True,
                venue_submitted=True,
                payload={
                    "position_id": position["position_id"],
                    "venue": venue,
                    "venue_order_id": result.payload.get("venue_order_id"),
                },
            )
        return ExitExecutionResult(
            status="refused",
            exit_recorded=False,
            venue_submitted=False,
            refusal_reason="UNSUPPORTED_EXIT_VENUE",
        )

    def _order_notional(
        self,
        *,
        output: dict[str, Any],
        venue: str,
        config_payload: dict[str, Any],
    ) -> Decimal:
        risk_key = "alpaca" if venue == Venue.ALPACA.value else "polymarket"
        max_position = _decimal_or_zero(
            config_payload.get("risk", {}).get(risk_key, {}).get("max_position_usd")
        )
        multiplier = _decimal_or_zero(output.get("size_multiplier") or output.get("sizeMultiplier"))
        if max_position <= 0:
            max_position = Decimal("1")
        if multiplier <= 0:
            multiplier = Decimal("0.5")
        return (max_position * multiplier).quantize(Decimal("0.00000001"))

    def _daily_loss(
        self,
        environment: Environment,
        venue: str,
        now: datetime,
        *,
        config_payload: Mapping[str, Any] | None = None,
    ) -> Decimal:
        if venue == Venue.ALPACA.value:
            try:
                fills = self.registry.shared().alpaca_historical_fills(environment=environment)
            except PersistenceUnavailableError:
                return Decimal("0")
            account_mode = ""
            if config_payload is not None:
                alpaca_config = config_payload.get("alpaca", {})
                if isinstance(alpaca_config, Mapping):
                    account_mode = str(alpaca_config.get("account_mode") or "")
            if account_mode:
                fills = [
                    fill
                    for fill in fills
                    if str(fill.get("account_mode") or "") == account_mode
                ]
            return _alpaca_realized_loss_for_day(fills, now)
        try:
            fills = self.registry.state.rows(
                "shared.venue_confirmed_fills",
                filters={"environment": environment.value, "venue": venue},
            )
        except PersistenceUnavailableError:
            return Decimal("0")
        local_day = _market_local_datetime(now).date()
        return sum(
            (
                abs(realized)
                for row in fills
                if _same_market_day(row.get("executed_at"), local_day)
                if (realized := _decimal_or_zero(row.get("realized_pnl_usd"))) < 0
            ),
            Decimal("0"),
        )

    def _open_position_count(
        self,
        environment: Environment,
        venue: str,
        *,
        config_payload: Mapping[str, Any] | None = None,
    ) -> int:
        return sum(
            1
            for position in self._open_positions(environment, config_payload=config_payload)
            if position["venue"] == venue
        )

    def _target_wallet_exit_benchmark(self) -> dict[str, Any]:
        try:
            rows = self.registry.state.rows("shared.polymarket_wallet_positions")
        except PersistenceUnavailableError:
            return {"available": False}
        closed = [row for row in rows if row.get("state") == PositionState.CLOSED.value]
        if not closed:
            return {"available": False}
        early_exits = [
            row
            for row in closed
            if row.get("closed_at") is not None and row.get("exit_price") is not None
        ]
        return {
            "available": True,
            "closedPositions": len(closed),
            "earlyExitRate": str(Decimal(len(early_exits)) / Decimal(len(closed))),
        }

    def _record_order_event(
        self,
        *,
        environment: Environment,
        order_id: str,
        venue: str,
        model_provider: ModelProvider,
        status: str,
        message: str,
    ) -> None:
        event_type = {
            "refused": OrderEventType.REFUSED,
            "failed": OrderEventType.FAILED,
        }.get(status, OrderEventType.SUBMITTED)
        try:
            self.registry.record_order_event_with_audit(
                OrderEvent(
                    order_id=order_id,
                    event_type=event_type,
                    venue=Venue(venue),
                    model_provider=model_provider,
                    message=message,
                ),
                environment=environment,
            )
        except PersistenceUnavailableError:
            return

    def _send_trade_placed_notification(
        self,
        *,
        config_payload: dict[str, Any],
        trade: TradePlacedAlert,
        now: datetime,
    ) -> None:
        if self.notification_adapter is None:
            return
        settings = NotificationSettings.from_config(config_payload.get("notifications", {}))
        try:
            send_trade_placed_alert(
                settings=settings,
                trade=trade,
                now=now,
                ses_adapter=self.notification_adapter,
                delivery_ledger=self.notification_ledger,
            )
        except Exception:
            return


def execution_config_from_payload(config_payload: dict[str, Any]) -> dict[str, Any]:
    configured = config_payload.get("execution") if isinstance(config_payload.get("execution"), dict) else {}
    alpaca = configured.get("alpaca") if isinstance(configured.get("alpaca"), dict) else {}
    return {
        **DEFAULT_EXECUTION_CONFIG,
        **{key: value for key, value in configured.items() if key != "alpaca"},
        "alpaca": {
            **DEFAULT_EXECUTION_CONFIG["alpaca"],
            **alpaca,
        },
    }


def exit_config_from_payload(config_payload: dict[str, Any]) -> dict[str, Any]:
    configured = config_payload.get("exit") if isinstance(config_payload.get("exit"), dict) else {}
    polymarket = configured.get("polymarket") if isinstance(configured.get("polymarket"), dict) else {}
    alpaca = configured.get("alpaca") if isinstance(configured.get("alpaca"), dict) else {}
    return {
        "polymarket": {
            **DEFAULT_EXIT_CONFIG["polymarket"],
            **polymarket,
        },
        "alpaca": {
            **DEFAULT_EXIT_CONFIG["alpaca"],
            **alpaca,
        },
    }


def execution_run_payload(run_row: dict[str, Any], intents: list[dict[str, Any]]) -> dict[str, Any]:
    clean_intents = [_order_intent_view(intent) for intent in intents]
    return {
        "id": run_row.get("id"),
        "environment": run_row.get("environment"),
        "pipelineRunId": run_row.get("pipeline_run_id"),
        "strategyConsensusRunId": run_row.get("strategy_consensus_run_id"),
        "trigger": run_row.get("trigger"),
        "status": run_row.get("status"),
        "intentCount": int(run_row.get("intent_count", len(clean_intents))),
        "submittedCount": int(run_row.get("submitted_count", 0)),
        "simulatedCount": int(run_row.get("simulated_count", 0)),
        "refusedCount": int(run_row.get("refused_count", 0)),
        "reconciliationCount": int(run_row.get("reconciliation_count", 0)),
        "startedAt": _isoformat_or_none(run_row.get("started_at")),
        "completedAt": _isoformat_or_none(run_row.get("completed_at")),
        "intents": clean_intents,
    }


def exit_run_payload(run_row: dict[str, Any], intents: list[dict[str, Any]]) -> dict[str, Any]:
    clean_intents = [_exit_intent_view(intent) for intent in intents]
    return {
        "id": run_row.get("id"),
        "environment": run_row.get("environment"),
        "pipelineRunId": run_row.get("pipeline_run_id"),
        "trigger": run_row.get("trigger"),
        "status": run_row.get("status"),
        "openPositionCount": int(run_row.get("open_position_count", 0)),
        "triggeredCount": int(run_row.get("triggered_count", len(clean_intents))),
        "simulatedCount": int(run_row.get("simulated_count", 0)),
        "submittedCount": int(run_row.get("submitted_count", 0)),
        "refusedCount": int(run_row.get("refused_count", 0)),
        "startedAt": _isoformat_or_none(run_row.get("started_at")),
        "completedAt": _isoformat_or_none(run_row.get("completed_at")),
        "intents": clean_intents,
    }


def _order_intent_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "executionRunId": row.get("execution_run_id"),
        "pipelineRunId": row.get("pipeline_run_id"),
        "consensusOutputId": row.get("strategy_consensus_output_id"),
        "venue": row.get("venue"),
        "instrumentId": row.get("instrument_id"),
        "modelProvider": row.get("model_provider"),
        "side": row.get("side"),
        "orderType": row.get("order_type"),
        "status": row.get("status"),
        "notionalUsd": _string_or_none(row.get("notional_usd")),
        "sizeMultiplier": _string_or_none(row.get("size_multiplier")),
        "idempotencyKey": row.get("idempotency_key"),
        "refusalReason": row.get("refusal_reason"),
        "venueOrderId": row.get("venue_order_id"),
        "createdAt": _isoformat_or_none(row.get("created_at")),
        "updatedAt": _isoformat_or_none(row.get("updated_at")),
    }


def _exit_intent_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "exitRunId": row.get("exit_run_id"),
        "pipelineRunId": row.get("pipeline_run_id"),
        "venue": row.get("venue"),
        "instrumentId": row.get("instrument_id"),
        "positionId": row.get("position_id"),
        "modelProvider": row.get("model_provider"),
        "triggerType": row.get("trigger_type"),
        "status": row.get("status"),
        "side": row.get("side"),
        "quantity": _string_or_none(row.get("quantity")),
        "notionalUsd": _string_or_none(row.get("notional_usd")),
        "threshold": _string_or_none(row.get("threshold")),
        "observedValue": _string_or_none(row.get("observed_value")),
        "idempotencyKey": row.get("idempotency_key"),
        "refusalReason": row.get("refusal_reason"),
        "venueOrderId": row.get("venue_order_id"),
        "createdAt": _isoformat_or_none(row.get("created_at")),
        "updatedAt": _isoformat_or_none(row.get("updated_at")),
    }


def _polymarket_exit_triggers(
    *,
    position: dict[str, Any],
    candidate: dict[str, Any] | None,
    config: dict[str, Any],
    now: datetime,
    wallet_benchmark: dict[str, Any],
) -> list[ExitTrigger]:
    entry = position.get("entry_price") or Decimal("0")
    current = _candidate_price(candidate) or entry
    quantity = _decimal_or_zero(position.get("quantity"))
    unrealized = (current - entry) * quantity if entry > 0 else Decimal("0")
    instrument = Instrument(
        venue=Venue.POLYMARKET_US,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        display_name=position["instrument_id"],
        market_id=position.get("market_id"),
        outcome_id=position.get("outcome_id"),
    )
    snapshot = PositionSnapshot(
        position_id=position["position_id"],
        instrument=instrument,
        state=PositionState.OPEN,
        unrealized_pnl=unrealized,
    )
    triggers: list[ExitTrigger] = []
    profit_trigger = evaluate_profit_target_exit(
        snapshot,
        profit_target=_decimal_or_zero(config["profit_target_usd"]),
    )
    if profit_trigger:
        triggers.append(profit_trigger)
    if entry > 0:
        profit_pct = (current - entry) / entry
        threshold = _decimal_or_zero(config["profit_target_pct"])
        if profit_pct >= threshold:
            triggers.append(
                ExitTrigger(
                    trigger_type=ExitTriggerType.PROFIT_TARGET,
                    position_id=position["position_id"],
                    threshold=threshold,
                    observed_value=profit_pct,
                    reason="profit target percentage reached",
                )
            )
    volume_trigger = evaluate_volume_spike_exit(
        position_id=position["position_id"],
        observed_volume=_candidate_metric(candidate, "volume10m"),
        baseline_volume=_candidate_metric(candidate, "baselineVolume10m"),
        multiplier_threshold=_decimal_or_zero(config["volume_spike_multiplier"]),
        stale_data=candidate is None,
    )
    if volume_trigger:
        triggers.append(volume_trigger)
    opened_at = position.get("opened_at")
    if isinstance(opened_at, datetime) and entry > 0:
        age_hours = Decimal(str((now - opened_at).total_seconds() / 3600))
        move_pct = abs((current - entry) / entry)
        stale_trigger = evaluate_stale_thesis_exit(
            position_id=position["position_id"],
            thesis_age_hours=age_hours,
            max_age_hours=_decimal_or_zero(config["max_thesis_age_hours"]),
            price_move_pct=move_pct,
            min_price_move_pct=_decimal_or_zero(config["min_stale_price_move_pct"]),
        )
        if stale_trigger:
            triggers.append(stale_trigger)
    if wallet_benchmark.get("available"):
        for trigger in triggers:
            trigger.reason = f"{trigger.reason}; compared with target wallet exit patterns"
    return _dedupe_triggers(triggers)


def _stock_exit_triggers(
    *,
    position: dict[str, Any],
    config: dict[str, Any],
    now: datetime,
) -> list[ExitTrigger]:
    entry = position.get("entry_price") or Decimal("0")
    current = position.get("current_price") or entry
    quantity = _decimal_or_zero(position.get("quantity"))
    if entry <= 0 or quantity <= 0:
        return []
    position_side = str(position.get("position_side") or "long").lower()
    pnl_pct = (
        (entry - current) / entry
        if position_side == "short"
        else (current - entry) / entry
    )
    triggers: list[ExitTrigger] = []
    profit_target = _decimal_or_zero(config["profit_target_pct"])
    if pnl_pct >= profit_target:
        triggers.append(
            ExitTrigger(
                trigger_type=ExitTriggerType.PROFIT_TARGET,
                position_id=position["position_id"],
                threshold=profit_target,
                observed_value=pnl_pct,
                reason="stock profit target reached",
            )
        )
    stop_loss = _decimal_or_zero(config["stop_loss_pct"])
    if pnl_pct <= -stop_loss:
        triggers.append(
            ExitTrigger(
                trigger_type=ExitTriggerType.STOP_LOSS,
                position_id=position["position_id"],
                threshold=stop_loss,
                observed_value=abs(pnl_pct),
                reason="stock stop loss reached",
            )
        )
    high_watermark = _decimal_or_none(position.get("high_watermark_price")) or _decimal_or_none(
        position.get("source", {}).get("raw_payload", {}).get("high_watermark_price")
    )
    trailing_stop = _decimal_or_zero(config["trailing_stop_pct"])
    if high_watermark and (
        (position_side == "short" and high_watermark < entry)
        or (position_side != "short" and high_watermark > entry)
    ):
        trailing_move = (
            (current - high_watermark) / high_watermark
            if position_side == "short"
            else (high_watermark - current) / high_watermark
        )
        if trailing_move >= trailing_stop:
            triggers.append(
                ExitTrigger(
                    trigger_type=ExitTriggerType.TRAILING_STOP,
                    position_id=position["position_id"],
                    threshold=trailing_stop,
                    observed_value=trailing_move,
                    reason="stock trailing stop reached",
                )
            )
    opened_at = position.get("opened_at")
    if isinstance(opened_at, datetime):
        age_hours = Decimal(str((now - opened_at).total_seconds() / 3600))
        max_age = _decimal_or_zero(config["max_position_age_hours"])
        min_move = _decimal_or_zero(config["min_stale_price_move_pct"])
        if age_hours >= max_age and abs(pnl_pct) >= min_move:
            triggers.append(
                ExitTrigger(
                    trigger_type=ExitTriggerType.STALE_POSITION,
                    position_id=position["position_id"],
                    threshold=max_age,
                    observed_value=age_hours,
                    reason="stock stale position threshold reached",
                )
            )
    close_before = max(0, int(config.get("close_before_market_close_minutes", 15)))
    minutes_to_close = _minutes_until_broker_market_close(position, now)
    if (
        config.get("market_hours_only", True)
        and minutes_to_close is not None
        and 0 <= minutes_to_close <= close_before
    ):
        triggers.append(
            ExitTrigger(
                trigger_type=ExitTriggerType.MARKET_HOURS,
                position_id=position["position_id"],
                threshold=Decimal(close_before),
                observed_value=Decimal(minutes_to_close),
                reason="stock market close window reached",
            )
        )
    return _dedupe_triggers(triggers)


def _market_candidates_by_key(market_data_pulls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for pull in market_data_pulls:
        for candidate in pull.get("candidates", []):
            keys = {
                str(candidate.get("id") or ""),
                str(candidate.get("instrument_id") or candidate.get("instrumentId") or ""),
            }
            if candidate.get("marketId") and candidate.get("outcomeId"):
                keys.add(f"{candidate['marketId']}:{candidate['outcomeId']}")
            if candidate.get("market_id") and candidate.get("outcome_id"):
                keys.add(f"{candidate['market_id']}:{candidate['outcome_id']}")
            if candidate.get("symbol"):
                keys.add(f"alpaca:{str(candidate['symbol']).upper()}")
            for key in keys:
                if key:
                    candidates[key] = candidate
    return candidates


def _candidate_for_instrument(
    output: dict[str, Any],
    market_candidates: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    source_candidate = output.get("source_payload", {}).get("candidate")
    instrument_id = str(output.get("instrument_id") or output.get("instrumentId") or "")
    market_candidate = market_candidates.get(instrument_id)
    if isinstance(source_candidate, dict) and source_candidate and market_candidate:
        return {**source_candidate, **market_candidate}
    if market_candidate:
        return market_candidate
    if isinstance(source_candidate, dict) and source_candidate:
        return source_candidate
    return None


def _market_data_is_fresh(
    candidate: dict[str, Any] | None,
    pulls: list[dict[str, Any]],
    config: dict[str, Any],
    now: datetime,
) -> bool:
    freshness_seconds = max(1, int(config["market_data_freshness_seconds"]))
    observed = _parse_datetime((candidate or {}).get("pulledAt") or (candidate or {}).get("pulled_at"))
    if observed is None:
        observed_values = [
            parsed
            for parsed in (
                _parse_datetime(pull.get("createdAt") or pull.get("created_at"))
                for pull in pulls
            )
            if parsed is not None
        ]
        observed = max(observed_values, default=None)
    if observed is None:
        return False
    return (now - observed).total_seconds() <= freshness_seconds


def _slippage_ok(
    *,
    venue: str,
    candidate: dict[str, Any] | None,
    config_payload: dict[str, Any],
) -> bool:
    if candidate is None:
        return False
    risk_key = "alpaca" if venue == Venue.ALPACA.value else "polymarket"
    threshold = _decimal_or_zero(
        config_payload.get("risk", {}).get(risk_key, {}).get("market_order_slippage_threshold")
    )
    raw_spread = candidate.get("spread")
    if raw_spread is None:
        return False
    observed = _decimal_or_zero(raw_spread)
    if venue == Venue.ALPACA.value:
        price = _decimal_or_zero(candidate.get("price"))
        if price <= 0:
            return False
        observed = observed / price
    return observed <= threshold


def _execution_mode(config_payload: dict[str, Any]) -> str:
    return "live" if bool(config_payload.get("live_enabled", False)) else "dry_run"


def _account_mode_valid(venue: str, config_payload: dict[str, Any]) -> bool:
    if venue != Venue.ALPACA.value:
        return True
    return str(config_payload.get("alpaca", {}).get("account_mode", "")).lower() in {"paper", "live"}


def _credentials_present(
    credentials: dict[str, bool],
    *,
    venue: str,
    model_provider: ModelProvider,
) -> bool:
    return credentials.get(f"{venue}:{model_provider.value}", credentials.get(venue, True))


def _model_provider(row: dict[str, Any]) -> ModelProvider:
    raw = str(row.get("model_provider") or row.get("modelProvider") or ModelProvider.OPENAI.value)
    return ModelProvider(raw)


def _position_model_provider(position: Mapping[str, Any]) -> ModelProvider:
    raw = position.get("model_provider", ModelProvider.OPENAI)
    return raw if isinstance(raw, ModelProvider) else ModelProvider(str(raw))


def _sanitized_alpaca_account_ref(account_id: str) -> str:
    normalized = account_id.strip()
    if not normalized:
        return "unresolved"
    return f"alpaca-{sha256(normalized.encode('utf-8')).hexdigest()[:12]}"


def _exit_source_payload(position: Mapping[str, Any]) -> dict[str, Any]:
    source = position.get("source") if isinstance(position.get("source"), Mapping) else {}
    if position.get("venue") != Venue.ALPACA.value:
        return _json_ready(source)
    return {
        "symbol": str(position.get("symbol") or source.get("symbol") or ""),
        "quantity": str(position.get("signed_quantity") or position.get("quantity") or "0"),
        "positionSide": str(position.get("position_side") or "long"),
        "averageEntryPrice": _json_ready(position.get("entry_price")),
        "currentPrice": _json_ready(position.get("current_price")),
        "observedAt": _json_ready(source.get("observed_at")),
        "accountRef": str(position.get("safe_account_ref") or "unresolved"),
    }


def _alpaca_entry_position_intent(*, venue: str, side: str) -> str:
    if venue != Venue.ALPACA.value:
        return "not_applicable"
    if side == OrderSide.BUY.value:
        return "buy_to_open"
    if side == OrderSide.SELL.value:
        return "sell_to_open"
    return "unsupported"


def _alpaca_exit_side(position: Mapping[str, Any]) -> str:
    return (
        OrderSide.BUY.value
        if str(position.get("position_side") or "long").lower() == "short"
        else OrderSide.SELL.value
    )


def _symbol_from_instrument(instrument_id: str, candidate: dict[str, Any] | None) -> str:
    if candidate and candidate.get("symbol"):
        return str(candidate["symbol"]).upper()
    return instrument_id.removeprefix("alpaca:").upper()


def _candidate_short_reference_price(candidate: Mapping[str, Any] | None) -> Decimal | None:
    if not candidate:
        return None
    explicit_ask = _decimal_or_none(candidate.get("ask_price") or candidate.get("askPrice"))
    if explicit_ask is not None and explicit_ask > 0:
        return explicit_ask
    price = _candidate_price(dict(candidate))
    if price is None or price <= 0:
        return None
    spread = max(Decimal("0"), _decimal_or_zero(candidate.get("spread")))
    return price + (spread / Decimal("2"))


def _polymarket_order_request(
    *,
    side: str,
    order_type: str,
    instrument_id: str,
    notional: Decimal,
    output: dict[str, Any],
    candidate: dict[str, Any] | None,
) -> PolymarketLiveOrderRequest:
    price = _candidate_price(candidate) or Decimal("0.50")
    quantity = notional / price if price > 0 else notional
    source_candidate = output.get("source_payload", {}).get("candidate", {})
    if not isinstance(source_candidate, dict):
        source_candidate = {}
    candidate_source = (candidate or {}).get("source_payload", {})
    if not isinstance(candidate_source, dict):
        candidate_source = {}
    source_candidate_payload = source_candidate.get("source_payload", {}) if isinstance(source_candidate, dict) else {}
    if not isinstance(source_candidate_payload, dict):
        source_candidate_payload = {}
    market_slug = (
        (candidate or {}).get("marketSlug")
        or (candidate or {}).get("market_slug")
        or candidate_source.get("marketSlug")
        or candidate_source.get("market_slug")
        or source_candidate.get("marketSlug")
        or source_candidate.get("market_slug")
        or source_candidate_payload.get("marketSlug")
        or source_candidate_payload.get("market_slug")
        or ""
    )
    is_market_order = str(order_type).lower() == OrderType.MARKET.value
    return PolymarketLiveOrderRequest(
        market_slug=str(market_slug),
        intent=_polymarket_entry_intent(side=side, output=output),
        order_type=order_type,
        price=None if is_market_order else price,
        quantity=None if is_market_order else quantity,
        cash_order_qty=notional if is_market_order else None,
        current_price=price,
    )


def _polymarket_entry_intent(*, side: str, output: dict[str, Any]) -> str:
    source_payload = output.get("source_payload") if isinstance(output.get("source_payload"), dict) else {}
    source_output = source_payload.get("output") if isinstance(source_payload.get("output"), dict) else {}
    signal = str(
        output.get("directional_signal")
        or output.get("directionalSignal")
        or source_output.get("directional_signal")
        or source_output.get("directionalSignal")
        or ""
    ).strip().lower()
    if signal in {"buy_no", "bearish"}:
        return "ORDER_INTENT_BUY_SHORT"
    if signal in {"buy_yes", "bullish"}:
        return "ORDER_INTENT_BUY_LONG"
    return "ORDER_INTENT_BUY_LONG" if side == OrderSide.BUY.value else "ORDER_INTENT_SELL_LONG"


def _candidate_price(candidate: dict[str, Any] | None) -> Decimal | None:
    if not candidate:
        return None
    return _decimal_or_none(candidate.get("price"))


def _candidate_metric(candidate: dict[str, Any] | None, key: str) -> Decimal:
    if not candidate:
        return Decimal("0")
    metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    return _decimal_or_zero(metrics.get(key) or candidate.get(key))


def _position_notional(position: dict[str, Any]) -> Decimal:
    quantity = _decimal_or_zero(position.get("quantity"))
    current = position.get("current_price") or position.get("entry_price") or Decimal("0")
    return abs(quantity) * _decimal_or_zero(current)


def _market_local_datetime(value: datetime) -> datetime:
    observed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return observed.astimezone(ZoneInfo("America/New_York"))


def _is_market_hours(value: datetime) -> bool:
    local = _market_local_datetime(value)
    return local.weekday() < 5 and time(9, 30) <= local.time() <= time(16, 0)


def _minutes_until_regular_market_close(value: datetime) -> int | None:
    local = _market_local_datetime(value)
    if local.weekday() >= 5 or not _is_market_hours(value):
        return None
    close = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return max(0, int((close - local).total_seconds() // 60))


def _alpaca_entry_time_refusals(
    created_at: datetime,
    config_payload: Mapping[str, Any],
) -> list[str]:
    exit_config = config_payload.get("exit", {})
    alpaca_config = exit_config.get("alpaca", {}) if isinstance(exit_config, Mapping) else {}
    if not isinstance(alpaca_config, Mapping) or not alpaca_config.get("market_hours_only", True):
        return []
    if not _is_market_hours(created_at):
        return ["OUTSIDE_MARKET_HOURS"]
    close_before = max(0, int(alpaca_config.get("close_before_market_close_minutes", 15)))
    minutes_to_close = _minutes_until_regular_market_close(created_at)
    if minutes_to_close is not None and minutes_to_close <= close_before:
        return ["MARKET_CLOSE_WINDOW"]
    return []


def _minutes_until_broker_market_close(
    position: Mapping[str, Any],
    now: datetime,
) -> int | None:
    source = position.get("source") if isinstance(position.get("source"), Mapping) else {}
    raw_payload = source.get("raw_payload") if isinstance(source.get("raw_payload"), Mapping) else {}
    clock = raw_payload.get("market_clock") if isinstance(raw_payload.get("market_clock"), Mapping) else {}
    if clock.get("is_open") is not True:
        return None
    clock_timestamp = _parse_datetime(clock.get("timestamp"))
    next_close = _parse_datetime(clock.get("next_close"))
    if clock_timestamp is None or next_close is None:
        return None
    if abs((now - clock_timestamp).total_seconds()) > 300:
        return None
    return max(0, int((next_close - clock_timestamp).total_seconds() // 60))


def _alpaca_realized_loss_for_day(fills: list[dict[str, Any]], now: datetime) -> Decimal:
    local_day = _market_local_datetime(now).date()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fill in fills:
        key = (str(fill.get("account_id") or ""), str(fill.get("symbol") or "").upper())
        grouped.setdefault(key, []).append(fill)
    loss = Decimal("0")
    for account_fills in grouped.values():
        open_quantity = Decimal("0")
        average_entry = Decimal("0")
        for fill in sorted(account_fills, key=lambda row: _datetime_or_min(row.get("filled_at"))):
            quantity = _decimal_or_zero(fill.get("quantity"))
            price = _decimal_or_zero(fill.get("price"))
            side = str(fill.get("side") or "").lower()
            if quantity <= 0 or price <= 0 or side not in {"buy", "sell"}:
                continue
            delta = quantity if side == "buy" else -quantity
            if open_quantity == 0 or open_quantity * delta > 0:
                combined = abs(open_quantity) + abs(delta)
                average_entry = (
                    (average_entry * abs(open_quantity)) + (price * abs(delta))
                ) / combined
                open_quantity += delta
                continue
            closed_quantity = min(abs(delta), abs(open_quantity))
            realized = (
                (price - average_entry) * closed_quantity
                if open_quantity > 0
                else (average_entry - price) * closed_quantity
            )
            if realized < 0 and _same_market_day(fill.get("filled_at"), local_day):
                loss += abs(realized)
            prior_quantity = open_quantity
            open_quantity += delta
            if open_quantity == 0:
                average_entry = Decimal("0")
            elif prior_quantity * open_quantity < 0:
                average_entry = price
    return loss


def _current_stock_position_opened_at(fills: list[dict[str, Any]]) -> datetime | None:
    open_quantity = Decimal("0")
    opened_at: datetime | None = None
    for fill in sorted(fills, key=lambda row: _datetime_or_min(row.get("filled_at"))):
        quantity = _decimal_or_zero(fill.get("quantity"))
        side = str(fill.get("side") or "").lower()
        filled_at = _parse_datetime(fill.get("filled_at"))
        if quantity <= 0 or side not in {"buy", "sell"}:
            continue
        delta = quantity if side == "buy" else -quantity
        prior_quantity = open_quantity
        open_quantity += delta
        if prior_quantity == 0:
            opened_at = filled_at
        elif open_quantity == 0:
            opened_at = None
        elif prior_quantity * open_quantity < 0:
            opened_at = filled_at
    return opened_at


def _same_market_day(value: Any, expected_day: Any) -> bool:
    parsed = _parse_datetime(value)
    return parsed is not None and _market_local_datetime(parsed).date() == expected_day


def _datetime_or_min(value: Any) -> datetime:
    parsed = _parse_datetime(value)
    return parsed or datetime.min.replace(tzinfo=UTC)


def _idempotency_key(*parts: str) -> str:
    raw = "|".join(parts)
    return sha256(raw.encode("utf-8")).hexdigest()


def _lifecycle_run_status(
    *,
    source_count: int,
    action_count: int,
    submitted_count: int,
    simulated_count: int,
    refused_count: int,
) -> str:
    if source_count == 0:
        return "no_consensus"
    if action_count == 0:
        return "no_intents"
    if refused_count and not (submitted_count or simulated_count):
        return "refused"
    if refused_count:
        return "partial"
    return "completed"


def _exit_run_status(
    *,
    open_position_count: int,
    triggered_count: int,
    submitted_count: int,
    simulated_count: int,
    refused_count: int,
) -> str:
    if open_position_count == 0:
        return "no_positions"
    if triggered_count == 0:
        return "no_triggers"
    if refused_count and not (submitted_count or simulated_count):
        return "refused"
    if refused_count:
        return "partial"
    return "completed"


def _dedupe_triggers(triggers: list[ExitTrigger]) -> list[ExitTrigger]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ExitTrigger] = []
    for trigger in triggers:
        key = (trigger.position_id, trigger.trigger_type.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(trigger)
    return deduped


def _primary_exit_trigger(triggers: list[ExitTrigger]) -> ExitTrigger | None:
    """Choose one full-position exit when several rules match the same position."""

    if not triggers:
        return None
    priority = {
        ExitTriggerType.STOP_LOSS: 0,
        ExitTriggerType.TRAILING_STOP: 1,
        ExitTriggerType.PROFIT_TARGET: 2,
        ExitTriggerType.MARKET_HOURS: 3,
        ExitTriggerType.VOLUME_SPIKE: 4,
        ExitTriggerType.STALE_THESIS: 5,
        ExitTriggerType.STALE_POSITION: 6,
    }
    return min(triggers, key=lambda trigger: priority.get(trigger.trigger_type, 99))


def _stock_position_high_watermark(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    account_mode: str,
    account_id: str,
    opened_at: datetime | None,
    position_side: str = "long",
) -> Decimal | None:
    prices: list[Decimal] = []
    for row in rows:
        if str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if account_mode and str(row.get("account_mode") or "") != account_mode:
            continue
        if account_id and str(row.get("account_id") or "") != account_id:
            continue
        observed_at = _parse_datetime(row.get("observed_at"))
        if opened_at is not None and (observed_at is None or observed_at < opened_at):
            continue
        price = _decimal_or_none(row.get("current_price"))
        if price is not None and price > 0:
            prices.append(price)
    if not prices:
        return None
    return min(prices) if position_side == "short" else max(prices)


def _exit_position_identity(position: Mapping[str, Any]) -> str:
    venue = str(position.get("venue") or "unknown")
    instrument_id = str(position.get("instrument_id") or position.get("position_id") or "unknown")
    if venue != Venue.ALPACA.value:
        return f"{venue}:{position.get('position_id') or instrument_id}"
    source = position.get("source") if isinstance(position.get("source"), Mapping) else {}
    account_id = str(
        position.get("safe_account_ref")
        or _sanitized_alpaca_account_ref(str(source.get("account_id") or ""))
    )
    account_mode = str(position.get("account_mode") or source.get("account_mode") or "unknown")
    model_provider = _position_model_provider(position).value
    position_side = str(position.get("position_side") or "long")
    opened_at = _parse_datetime(position.get("opened_at"))
    opened_key = opened_at.isoformat() if opened_at is not None else str(position.get("position_id"))
    return (
        f"{venue}:{model_provider}:{account_mode}:{account_id}:"
        f"{position_side}:{instrument_id}:{opened_key}"
    )


def _order_event_message(status: str, refusal_reason: str | None) -> str:
    if status == "refused":
        return f"order intent refused: {refusal_reason or 'risk gate failed'}"
    if status == "simulated":
        return "dry-run order simulated"
    if status == "submitted":
        return "live order submitted"
    return f"order intent recorded with status {status}"


def _refusal_text(result: RiskLimitResult) -> str | None:
    if not result.refusal_reasons:
        return None
    return "; ".join(result.refusal_reasons)


def _exit_event_message(
    status: str,
    trigger: ExitTrigger,
    refusal_reason: str | None,
) -> str:
    if status == "refused":
        return f"exit refused for {trigger.trigger_type.value}: {refusal_reason}"
    if status == "simulated":
        return f"dry-run exit simulated for {trigger.trigger_type.value}"
    if status == "submitted":
        return f"live exit submitted for {trigger.trigger_type.value}"
    return f"exit recorded for {trigger.trigger_type.value}"


def _decimal_or_zero(value: Any) -> Decimal:
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None else Decimal("0")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    return decimal


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _isoformat_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _submit_exception_reason(exc: Exception) -> str:
    reason = getattr(exc, "refusal_reason", None)
    if reason:
        return str(reason)
    return f"{type(exc).__name__}: venue submit failed"


def _submit_exception_payload(exc: Exception) -> dict[str, Any]:
    payload = getattr(exc, "payload", None)
    if isinstance(payload, dict):
        return dict(payload)
    status_code = getattr(exc, "status_code", None)
    result: dict[str, Any] = {"error_type": type(exc).__name__}
    if status_code is not None:
        result["status_code"] = status_code
    return result


def _polymarket_position_slug(position: dict[str, Any]) -> str:
    source = position.get("source") if isinstance(position.get("source"), dict) else {}
    for value in (
        position.get("market_slug"),
        position.get("marketSlug"),
        source.get("market_slug"),
        source.get("marketSlug"),
        position.get("market_id"),
    ):
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _polymarket_exit_slippage_bips(config_payload: dict[str, Any]) -> int | None:
    raw = config_payload.get("risk", {}).get("polymarket", {}).get(
        "market_order_slippage_threshold"
    )
    threshold = _decimal_or_none(raw)
    if threshold is None or threshold < 0:
        return None
    return int((threshold * Decimal("10000")).to_integral_value())


class _NoopAlpacaSubmitter:
    def submit_order(
        self,
        *,
        account_mode: str,
        symbol: str,
        notional: Decimal | None = None,
        quantity: Decimal | None = None,
        side: str = "buy",
        client_order_id: str | None = None,
        position_intent: str | None = None,
        estimated_unit_price: Decimal | None = None,
        expected_account_id: str | None = None,
        entry_cutoff_minutes: int | None = None,
        max_quote_age_seconds: int | None = None,
    ) -> str:
        return f"alpaca-{account_mode}-{symbol}-dry-run"


class _NoopPolymarketSubmitter:
    def submit_order(self, request: PolymarketLiveOrderRequest) -> VenueCallResult:
        return VenueCallResult(
            ok=True,
            payload={
                "market_slug": request.market_slug,
                "venue_order_id": f"polymarket-{request.market_slug}-dry-run",
            },
        )


class _NoopExitSubmitter:
    def submit_order(self) -> str:
        return "exit-dry-run"
