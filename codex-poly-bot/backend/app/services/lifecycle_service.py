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
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Mapping

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
        "profit_target_pct": "0.08",
        "stop_loss_pct": "0.04",
        "trailing_stop_pct": "0.05",
        "max_position_age_hours": "168",
        "min_stale_price_move_pct": "0.03",
        "market_hours_only": True,
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
        run_row.update(
            {
                "status": _lifecycle_run_status(
                    source_count=len(approved_outputs),
                    action_count=len(intents),
                    submitted_count=submitted_count,
                    simulated_count=simulated_count,
                    refused_count=refused_count,
                ),
                "intent_count": len(intents),
                "submitted_count": submitted_count,
                "simulated_count": simulated_count,
                "refused_count": refused_count,
                "reconciliation_count": reconciliation_count,
            }
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
        positions = self._open_positions(environment)
        intents: list[dict[str, Any]] = []
        for position in positions:
            triggers = self._exit_triggers_for_position(
                position=position,
                market_candidates=market_candidates,
                config=config,
                now=completed_at,
            )
            for exit_trigger in triggers:
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
        run_row.update(
            {
                "status": _exit_run_status(
                    open_position_count=len(positions),
                    triggered_count=len(intents),
                    submitted_count=submitted_count,
                    simulated_count=simulated_count,
                    refused_count=refused_count,
                ),
                "open_position_count": len(positions),
                "triggered_count": len(intents),
                "simulated_count": simulated_count,
                "submitted_count": submitted_count,
                "refused_count": refused_count,
            }
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
        idempotency_key = _idempotency_key(
            "entry",
            environment.value,
            pipeline_run_id,
            str(output.get("id") or instrument_id),
            side,
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
        if risk_result.approved:
            execution_result = self._execute_entry_order(
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
            )
            status = execution_result["status"]
            refusal_reason = execution_result.get("refusal_reason")
            venue_order_id = execution_result.get("venue_order_id")
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
                    daily_loss=self._daily_loss(environment),
                    open_positions=self._provider_open_position_count(_model_provider(output)),
                    creates_new_position=True,
                    model_capital=str(config["alpaca"]["model_capital_usd"]),
                )
            )
        else:
            venue_risk = evaluate_polymarket_risk_limits(
                PolymarketRiskInput(
                    proposed_notional=notional,
                    daily_loss=self._daily_loss(environment),
                    open_positions=self._provider_open_position_count(_model_provider(output)),
                    creates_new_position=True,
                )
            )
        reasons = list(venue_risk.refusal_reasons)
        if venue == Venue.ALPACA.value and side != OrderSide.BUY.value:
            reasons.append("ALPACA_ENTRY_SELL_UNSUPPORTED")
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
    ) -> dict[str, Any]:
        execution_mode = _execution_mode(config_payload)
        if venue == Venue.ALPACA.value:
            alpaca_submitter = self._alpaca_submitter_for(model_provider)
            if execution_mode == "live" and alpaca_submitter is None:
                return {
                    "status": "refused",
                    "refusal_reason": "LIVE_SUBMITTER_NOT_CONFIGURED",
                }
            result = execute_alpaca_order(
                AlpacaExecutionRequest(
                    global_execution_mode=execution_mode,
                    account_mode=str(config_payload.get("alpaca", {}).get("account_mode", "paper")),
                    risk_approved=True,
                    symbol=_symbol_from_instrument(instrument_id, candidate),
                    notional=notional,
                    client_order_id=idempotency_key,
                ),
                submitter=alpaca_submitter or _NoopAlpacaSubmitter(),
            )
            return {
                "status": result.status,
                "refusal_reason": result.refusal_reason,
                "venue_order_id": result.payload.get("venue_order_id"),
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
        }

    def _open_positions(self, environment: Environment) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        positions.extend(self._open_polymarket_positions(environment))
        positions.extend(self._open_alpaca_positions(environment))
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

    def _open_alpaca_positions(self, environment: Environment) -> list[dict[str, Any]]:
        try:
            rows = self.registry.shared().alpaca_historical_positions(environment=environment)
        except PersistenceUnavailableError:
            return []
        latest_by_symbol: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = str(row["symbol"]).upper()
            current = latest_by_symbol.get(symbol)
            if current is None or row.get("observed_at") > current.get("observed_at"):
                latest_by_symbol[symbol] = row
        positions = []
        for row in latest_by_symbol.values():
            quantity = _decimal_or_zero(row.get("quantity"))
            if quantity <= 0:
                continue
            symbol = str(row["symbol"]).upper()
            positions.append(
                {
                    "position_id": row["id"],
                    "venue": Venue.ALPACA.value,
                    "instrument_id": f"alpaca:{symbol}",
                    "symbol": symbol,
                    "quantity": quantity,
                    "entry_price": _decimal_or_none(row.get("average_entry_price")),
                    "current_price": _decimal_or_none(row.get("current_price")),
                    "unrealized_pnl": _decimal_or_zero(row.get("unrealized_pnl_usd")),
                    "opened_at": self._stock_opened_at(environment, symbol),
                    "source": row,
                }
            )
        return positions

    def _stock_opened_at(self, environment: Environment, symbol: str) -> datetime | None:
        try:
            fills = [
                row
                for row in self.registry.shared().alpaca_historical_fills(environment=environment)
                if row["symbol"] == symbol.upper()
            ]
        except PersistenceUnavailableError:
            return None
        if not fills:
            return None
        return min((row["filled_at"] for row in fills if row.get("filled_at")), default=None)

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
        idempotency_key = _idempotency_key(
            "exit",
            environment.value,
            pipeline_run_id,
            position["position_id"],
            exit_trigger.trigger_type.value,
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
            side=OrderSide.SELL.value,
            quantity=position.get("quantity"),
            notional_usd=notional,
            threshold=exit_trigger.threshold,
            observed_value=exit_trigger.observed_value,
            idempotency_key=idempotency_key,
            refusal_reason=result.refusal_reason,
            venue_order_id=result.payload.get("venue_order_id"),
            source_payload={
                "position": _json_ready(position["source"]),
                "triggerReason": exit_trigger.reason,
                "executionMode": execution_mode,
            },
            created_at=created_at,
            updated_at=created_at,
        )
        self._record_order_event(
            environment=environment,
            order_id=idempotency_key,
            venue=venue,
            model_provider=ModelProvider.OPENAI,
            status=status,
            message=_exit_event_message(status, exit_trigger, result.refusal_reason),
        )
        if status == "submitted":
            self._send_trade_placed_notification(
                config_payload=config_payload,
                trade=TradePlacedAlert(
                    venue=venue,
                    side=OrderSide.SELL.value,
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
            if self.alpaca_exit_submitter is None:
                return ExitExecutionResult(
                    status="refused",
                    exit_recorded=False,
                    venue_submitted=False,
                    refusal_reason="LIVE_EXIT_SUBMITTER_NOT_CONFIGURED",
                )
            try:
                venue_order_id = self.alpaca_exit_submitter.submit_order(
                    account_mode=str(config_payload.get("alpaca", {}).get("account_mode", "paper")),
                    symbol=str(position.get("symbol") or _symbol_from_instrument(position["instrument_id"], None)),
                    quantity=_decimal_or_zero(position.get("quantity")),
                    side="sell",
                    client_order_id=idempotency_key,
                )
            except Exception as exc:
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

    def _daily_loss(self, environment: Environment) -> Decimal:
        loss = Decimal("0")
        for provider in ModelProvider:
            try:
                rows = self.registry.state.rows(f"{provider.value}.positions")
            except PersistenceUnavailableError:
                continue
            for row in rows:
                if row.get("state") == PositionState.CLOSED.value:
                    realized = _decimal_or_zero(row.get("realized_pnl"))
                    if realized < 0:
                        loss += abs(realized)
        try:
            pnl_rows = self.registry.shared().alpaca_symbol_pnl_snapshots(environment=environment)
        except PersistenceUnavailableError:
            pnl_rows = []
        for row in pnl_rows:
            realized = _decimal_or_zero(row.get("realized_pnl_usd"))
            if realized < 0:
                loss += abs(realized)
        return loss

    def _provider_open_position_count(self, provider: ModelProvider) -> int:
        try:
            rows = self.registry.state.rows(f"{provider.value}.positions")
        except PersistenceUnavailableError:
            return 0
        return sum(1 for row in rows if row.get("state") != PositionState.CLOSED.value)

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
    pnl_pct = (current - entry) / entry
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
    high_watermark = _decimal_or_none(
        position.get("source", {}).get("raw_payload", {}).get("high_watermark_price")
    )
    trailing_stop = _decimal_or_zero(config["trailing_stop_pct"])
    if high_watermark and high_watermark > entry:
        drawdown_from_high = (high_watermark - current) / high_watermark
        if drawdown_from_high >= trailing_stop:
            triggers.append(
                ExitTrigger(
                    trigger_type=ExitTriggerType.TRAILING_STOP,
                    position_id=position["position_id"],
                    threshold=trailing_stop,
                    observed_value=drawdown_from_high,
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
    if config.get("market_hours_only", True) and not _is_market_hours(now):
        triggers.append(
            ExitTrigger(
                trigger_type=ExitTriggerType.MARKET_HOURS,
                position_id=position["position_id"],
                threshold=Decimal("1"),
                observed_value=Decimal("0"),
                reason="outside stock market hours",
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
    observed = _decimal_or_zero(candidate.get("spread"))
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


def _symbol_from_instrument(instrument_id: str, candidate: dict[str, Any] | None) -> str:
    if candidate and candidate.get("symbol"):
        return str(candidate["symbol"]).upper()
    return instrument_id.removeprefix("alpaca:").upper()


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
    market_slug = (
        (candidate or {}).get("marketSlug")
        or (candidate or {}).get("market_slug")
        or source_candidate.get("marketSlug")
        or source_candidate.get("market_slug")
        or instrument_id.split(":", 1)[0]
    )
    return PolymarketLiveOrderRequest(
        market_slug=str(market_slug),
        intent="ORDER_INTENT_BUY_LONG" if side == OrderSide.BUY.value else "ORDER_INTENT_SELL_LONG",
        order_type=order_type,
        quantity=quantity,
        cash_order_qty=notional,
        current_price=price,
    )


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
    return quantity * _decimal_or_zero(current)


def _is_market_hours(value: datetime) -> bool:
    eastern_hour = value.astimezone(UTC).hour - 4
    if eastern_hour < 0:
        eastern_hour += 24
    local_time = time(eastern_hour, value.minute)
    return value.weekday() < 5 and time(9, 30) <= local_time <= time(16, 0)


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
