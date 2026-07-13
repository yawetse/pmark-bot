# codex-poly-bot Low-Level Design

**Spec ID:** SPEC-CODEX-POLY-BOT  
**Version:** 1.0  
**Date:** 2026-04-24  
**Status:** DRAFT  
**Requirements Source:** `requirements.md`  
**HLD Source:** `design-hld.md`  

## LLD Conventions

- Interfaces use strict Python type hints.
- API and configuration shapes use Pydantic models.
- Service and adapter modules use classes with injected dependencies.
- Deterministic calculations use pure functions where practical.
- Expected trading refusals return typed `Result` objects.
- Unexpected failures use typed domain exceptions.
- Runtime defaults are seeded into Postgres config; Python defaults exist only as bootstrap fallback.
- Money, prices, probabilities, and P&L use `Decimal`.

---

## 1. Domain Models

**File:** `backend/app/domain/`  
**Responsibility:** Define typed domain objects, enums, validation rules, and shared result types.  
**Requirements Covered:** REQ-VEN-001, REQ-ALP-001, REQ-ALP-002, REQ-DB-004, REQ-DB-005, REQ-LLM-003, REQ-STR-007, REQ-EXE-008, REQ-EXE-016, REQ-EXT-001, REQ-CMP-001, REQ-CMP-003, REQ-OBS-001  
**Dependencies:** `decimal`, `datetime`, `enum`, `pydantic`  
**Depended On By:** All backend services, adapters, repositories, tests

### 1.1 Public Interface

#### `class Venue(str, Enum)`

- **Purpose:** Enumerates supported venues: `polymarket_us`, `polymarket_international`, and `alpaca`.
- **Traces:** REQ-VEN-001, REQ-ALP-001
- **Attributes:** Venue string values used in config, persistence, logs, and dashboard APIs.
- **Raises/Errors:** Pydantic validation fails on unsupported values.
- **Side Effects:** None.

#### `class InstrumentType(str, Enum)`

- **Purpose:** Distinguishes `prediction_market`, `stock`, and `etf`.
- **Traces:** REQ-ALP-001, REQ-ALP-002, REQ-CMP-001
- **Raises/Errors:** Pydantic validation fails on unsupported values.
- **Side Effects:** None.

#### `class GlobalExecutionMode(str, Enum)`

- **Purpose:** Represents the global execution gate: `dry_run` or `live`.
- **Traces:** REQ-ALP-005, REQ-ALP-006, REQ-EXE-001, REQ-EXE-002, REQ-EXE-017
- **Raises/Errors:** Pydantic validation fails on unsupported values.
- **Side Effects:** None.

#### `class AlpacaAccountMode(str, Enum)`

- **Purpose:** Represents Alpaca account endpoint mode: `paper` or `live`.
- **Traces:** REQ-ALP-007
- **Raises/Errors:** Pydantic validation fails on unsupported values.
- **Side Effects:** None.

#### `class Instrument(BaseModel)`

- **Purpose:** Identifies a tradable prediction-market outcome, stock, or ETF.
- **Traces:** REQ-DB-004, REQ-CMP-001
- **Fields:**
  - `venue: Venue`
  - `instrument_type: InstrumentType`
  - `symbol: str | None`
  - `market_id: str | None`
  - `outcome_id: str | None`
  - `display_name: str`
- **Returns:** Validated instrument object.
- **Raises/Errors:** `DomainValidationError` when required identifiers for a venue/type are missing.
- **Side Effects:** None.

#### `class OrderIntent(BaseModel)`

- **Purpose:** Captures a persisted intent before any live order submission.
- **Traces:** REQ-DB-004, REQ-EXE-016, REQ-OBS-003
- **Fields:** `idempotency_key`, `environment`, `venue`, `model_provider`, `instrument`, `side`, `order_type`, `global_execution_mode`, `alpaca_account_mode`, `loop_run_id`, `reservation_id`, `risk_decision_id`, `requested_notional`, `requested_quantity`, `limit_price`, `slippage_limit`, `price_guardrails`, `config_version`, `strategy_signal_ids`, `status`.
- **Returns:** Validated order intent.
- **Raises/Errors:** Validation rejects missing idempotency key, non-positive size, unsupported order type, or incompatible stock/order fields.
- **Side Effects:** None.

#### `build_order_idempotency_key(input: OrderIdempotencyInput) -> str`

- **Purpose:** Build deterministic idempotency keys matching HLD inputs.
- **Traces:** REQ-EXE-016, REQ-OBS-003
- **Parameters:** `input` contains environment, venue, model provider, instrument identifier, side, strategy set hash, config version, and loop run ID.
- **Returns:** Stable string key.
- **Raises/Errors:** Raises `DomainValidationError` if any required key part is missing.
- **Side Effects:** None.

#### `class OrderIdempotencyInput(BaseModel)`

- **Purpose:** Defines the complete input used to generate an order idempotency key.
- **Traces:** REQ-EXE-016, REQ-OBS-003
- **Fields:** `environment`, `venue`, `model_provider`, `instrument_identifier`, `side`, `strategy_set_hash`, `config_version`, `loop_run_id`.
- **Returns:** Validated key input.
- **Raises/Errors:** Validation rejects empty key parts.
- **Side Effects:** None.

#### `class RiskCheckResult(BaseModel)`

- **Purpose:** Captures one risk check outcome inside a risk decision.
- **Traces:** REQ-EXE-013, REQ-ALP-015, REQ-ALP-018
- **Fields:** `check_name`, `passed`, `limit_value`, `observed_value`, `refusal_reason`.
- **Returns:** Validated risk check result.
- **Raises/Errors:** Validation rejects failed checks without a refusal reason.
- **Side Effects:** None.

#### `class RiskDecision(BaseModel)`

- **Purpose:** Represents an approval or refusal from the risk engine.
- **Traces:** REQ-EXE-008, REQ-EXE-009, REQ-EXE-013, REQ-ALP-008, REQ-ALP-015, REQ-ALP-018
- **Fields:** `approved: bool`, `refusal_reason: str | None`, `approved_notional: Decimal | None`, `approved_quantity: Decimal | None`, `checks: list[RiskCheckResult]`.
- **Returns:** Risk decision object.
- **Raises/Errors:** Validation rejects approved decisions without a positive approved size.
- **Side Effects:** None.

#### `class PositionTransition(BaseModel)`

- **Purpose:** Represents a position state change.
- **Traces:** REQ-DB-005, REQ-ALP-017, REQ-ALP-018
- **Fields:** `position_id`, `prior_state`, `new_state`, `prior_quantity`, `new_quantity`, `realized_pnl`, `unrealized_pnl`, `reason`, `source`, `created_at`.
- **Returns:** Validated position transition.
- **Raises/Errors:** Validation rejects negative Alpaca quantity.
- **Side Effects:** None.

#### `class ScoringOutput(BaseModel)`

- **Purpose:** Captures one LLM scoring response.
- **Traces:** REQ-LLM-003
- **Fields:** `model_provider`, `prompt_version`, `input_summary`, `output_thesis`, `confidence`, `estimated_probability`, `estimated_cost`, `actual_cost`, `instrument`, `created_at`.
- **Returns:** Validated scoring output.
- **Raises/Errors:** Validation rejects confidence/probability outside `0..1`.
- **Side Effects:** None.

#### `class StrategySignal(BaseModel)`

- **Purpose:** Captures one strategy signal before execution decision.
- **Traces:** REQ-STR-007
- **Fields:** `strategy_name`, `model_provider`, `instrument`, `direction`, `confidence`, `inputs_hash`, `created_at`.
- **Returns:** Validated signal.
- **Raises/Errors:** Validation rejects unsupported direction.
- **Side Effects:** None.

#### `class ExitTrigger(BaseModel)`

- **Purpose:** Represents a configured or observed exit trigger.
- **Traces:** REQ-EXT-001
- **Fields:** `trigger_type`, `position_id`, `threshold`, `observed_value`, `reason`, `created_at`.
- **Returns:** Validated exit trigger.
- **Raises/Errors:** Validation rejects unsupported trigger type.
- **Side Effects:** None.

#### `class ComparisonMetric(BaseModel)`

- **Purpose:** Represents a calculated comparison metric.
- **Traces:** REQ-CMP-003
- **Fields:** `metric_name`, `model_provider`, `venue`, `instrument_type`, `window`, `value`, `unavailable_reason`, `calculated_at`.
- **Returns:** Validated metric value or unavailable marker.
- **Raises/Errors:** Validation rejects missing `value` and `unavailable_reason`.
- **Side Effects:** None.

#### `class StructuredLogEvent(BaseModel)`

- **Purpose:** Defines structured log context used by services.
- **Traces:** REQ-OBS-001
- **Fields:** `event_name`, `correlation_id`, `environment`, `venue`, `model_provider`, `entity_id`, `metadata`.
- **Returns:** Validated log event.
- **Raises/Errors:** Validation rejects missing event name or correlation ID.
- **Side Effects:** None.

#### `class ConfigSnapshot(BaseModel)`

- **Purpose:** Immutable runtime configuration used for one worker loop.
- **Traces:** REQ-VEN-006, REQ-LLM-006, REQ-LLM-007, REQ-STR-002, REQ-EXE-007, REQ-ALP-014, REQ-NOT-006, REQ-UI-005, REQ-UI-007
- **Fields:** `version`, `environment`, `live_enabled`, `venue_configs`, `model_configs`, `risk_configs`, `strategy_configs`, `notification_config`, `created_at`.
- **Returns:** Versioned config snapshot.
- **Raises/Errors:** Validation rejects missing provider configs, invalid risk values, and enabled venues without required bootstrap references.
- **Side Effects:** None.

#### `class KillSwitchState(BaseModel)`

- **Purpose:** Represents current kill-switch state returned by config service and shown in the dashboard.
- **Traces:** REQ-EXE-014, REQ-EXE-015, REQ-UI-008
- **Fields:** `active`, `activated_by`, `activated_at`, `environment`, `cancel_status`, `unresolved_order_count`.
- **Returns:** Validated kill-switch status.
- **Raises/Errors:** Validation rejects active state without actor or timestamp.
- **Side Effects:** None.

#### `class ServiceResult[T](BaseModel)`

- **Purpose:** Standard result envelope for expected outcomes and refusals.
- **Traces:** REQ-EXE-013, REQ-OBS-001
- **Fields:** `ok: bool`, `value: T | None`, `error_code: str | None`, `message: str | None`, `audit_context: dict[str, str]`.
- **Returns:** Typed success/refusal value.
- **Raises/Errors:** Validation rejects `ok=true` without `value`.
- **Side Effects:** None.

### 1.2 Internal Implementation Details

#### Decimal Validation

- **What it does:** Converts money, probability, price, P&L, and exposure fields into bounded `Decimal` values.
- **Why this approach:** Avoids float drift in trading decisions and comparison metrics.
- **Complexity:** O(1) per field.
- **Key steps:**
  1. Coerce input to `Decimal` from string or integer-safe values.
  2. Reject `NaN`, infinity, and negative values where not allowed.
  3. Quantize only at display or venue-adapter boundaries.

### 1.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `Instrument` | Pydantic model | Venue-neutral tradable identifier | Has exactly the identifiers required by venue/type |
| `OrderIntent` | Pydantic model | Pre-submit order record | Has stable idempotency key and positive size |
| `ConfigSnapshot` | Pydantic model | Immutable loop config | Version never changes after creation |
| `ServiceResult` | Generic Pydantic model | Expected success/refusal wrapper | `ok` determines whether `value` or `error_code` is populated |
| `PositionTransition` | Pydantic model | Position state change | Alpaca quantity cannot become negative |
| `ScoringOutput` | Pydantic model | LLM response | Probability and confidence are bounded |
| `StrategySignal` | Pydantic model | Strategy vote | Direction is one of buy/sell/hold/neutral |
| `ExitTrigger` | Pydantic model | Exit condition | Trigger type is supported |
| `ComparisonMetric` | Pydantic model | Dashboard metric | Missing metric has unavailable reason |
| `OrderIdempotencyInput` | Pydantic model | Idempotency key input | All key parts are non-empty |
| `RiskCheckResult` | Pydantic model | One risk check result | Failed checks include refusal reason |
| `KillSwitchState` | Pydantic model | Kill-switch status | Active state has actor and timestamp |

### 1.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Alpaca stock instrument has no symbol | Validation fails | REQ-ALP-001 |
| 2 | Polymarket instrument has no market/outcome identifier | Validation fails | REQ-VEN-001 |
| 3 | Approved risk decision has zero size | Validation fails | REQ-EXE-008 |
| 4 | Unsupported instrument type appears in comparison metrics | Validation fails | REQ-CMP-001 |
| 5 | Money field receives float `NaN` | Validation fails | REQ-DB-004 |
| 6 | Idempotency key input misses loop run ID | Validation fails | REQ-EXE-016 |
| 7 | Alpaca position transition creates negative quantity | Validation fails | REQ-ALP-008 |
| 8 | Comparison metric cannot be calculated | Return unavailable marker, not zero | REQ-CMP-003 |

### 1.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Invalid domain value | Pydantic validation | Raise `DomainValidationError` through service boundary | Yes, via API validation message |
| Expected trade refusal | Risk/config/service logic | Return `ServiceResult(ok=False)` | Yes, via dashboard refusal reason |
| Unsupported enum value | API or DB hydration | Raise validation error and log structured error | Yes, degraded status if persisted data is invalid |

### 1.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Data Integrity | Financial values must be exact enough for risk checks | Use `Decimal`, not float |
| Testability | Domain validation must be testable without DB/API | Pure Pydantic models and functions |
| Observability | Refusals need structured context | `ServiceResult.audit_context` |

### 1.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Exports to | All backend modules | Pydantic models and enums | Typed domain objects |
| Imports | None internal | N/A | N/A |

### 1.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | No additional asset classes are represented in v1 beyond prediction markets, stocks, and ETFs. | Domain enums would need expansion. | APPROVED BY REQUIREMENTS |

---

## 2. Database Layer

**File:** `backend/app/db/`  
**Responsibility:** Manage SQLAlchemy sessions, transactions, model-provider schemas, migrations, repositories, and unit-of-work boundaries.  
**Requirements Covered:** REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005, REQ-DB-006, REQ-DB-007, REQ-ALP-016, REQ-ALP-017, REQ-ALP-018, REQ-EXE-016, REQ-OBS-003, REQ-OBS-004  
**Dependencies:** SQLAlchemy, Alembic, Postgres  
**Depended On By:** Services, adapters that persist state, workers, API routers

### 2.1 Public Interface

#### `class UnitOfWork`

- **Purpose:** Own one transaction boundary for service operations.
- **Traces:** REQ-DB-001, REQ-DB-007, REQ-EXE-016
- **Methods:**
  - `__enter__() -> UnitOfWork`
  - `__exit__(exc_type, exc, tb) -> None`
  - `commit() -> None`
  - `rollback() -> None`
- **Raises/Errors:** Raises `PersistenceUnavailableError` when the session cannot be opened or committed.
- **Side Effects:** Opens, commits, rolls back, and closes DB sessions.

#### `class RepositoryRegistry`

- **Purpose:** Provides typed repository instances for shared, Claude, and OpenAI schemas.
- **Traces:** REQ-DB-002, REQ-DB-003
- **Methods:**
  - `shared() -> SharedRepositories`
  - `for_model(provider: ModelProvider) -> ModelRepositories`
- **Raises/Errors:** Raises `DomainValidationError` for unsupported provider.
- **Side Effects:** None beyond repository creation.

#### `create_session_factory(database_url: str) -> sessionmaker`

- **Purpose:** Build SQLAlchemy session factory.
- **Traces:** REQ-DB-001, REQ-DB-007
- **Parameters:** `database_url` must be a valid Postgres DSN. Bare `postgresql://` URLs are normalized to the packaged `postgresql+psycopg://` driver.
- **Returns:** SQLAlchemy session factory.
- **Raises/Errors:** Raises `PersistenceConfigurationError` for malformed DSN or missing driver support.
- **Side Effects:** Initializes DB engine.

#### `run_migrations(target: str = "head") -> None`

- **Purpose:** Apply Alembic migrations for shared, Claude, and OpenAI schemas.
- **Traces:** REQ-DB-002, REQ-DB-003, REQ-DEP-005
- **Raises/Errors:** Raises `MigrationError` on migration failure.
- **Side Effects:** Mutates database schema.

### 2.2 Internal Implementation Details

#### Schema Strategy

- **What it does:** Uses `shared` schema for config, users, audits, jobs, ingestion, and deployment state; `claude` and `openai` schemas for provider-specific scoring, decisions, positions, orders, and P&L.
- **Why this approach:** Keeps model comparison clean without operating separate databases.
- **Complexity:** O(1) schema routing per repository call.
- **Key steps:**
  1. Validate provider.
  2. Select schema-bound table metadata.
  3. Run repository operation inside `UnitOfWork`.

#### Idempotency and Reservations

- **What it does:** Enforces unique keys for order intents and market/model reservations.
- **Why this approach:** Prevents duplicate order submission and conflicting entry/exit decisions.
- **Complexity:** O(log n) unique-index lookup.
- **Key steps:**
  1. Insert reservation or order intent with unique key.
  2. Handle conflict as expected refusal or existing intent lookup.
  3. Release reservations only through terminal state transition.

### 2.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `config_versions` | Shared table | Immutable config snapshots | Exactly one active version per environment |
| `audit_events` | Shared table | Append-only audit log | No application update/delete path |
| `job_runs` | Shared table | Worker lock and heartbeat records | Active job has current heartbeat or is marked abandoned |
| `order_intents` | Provider schema table | Pre-submit order records | Unique idempotency key |
| `trade_decisions` | Provider schema table | Model/strategy decision before risk/execution | Has environment, model provider, venue, instrument identifier/type, signal input references, decision, order type, size, timestamp |
| `strategy_signals` | Provider schema table | Individual strategy outputs | Has strategy name, direction, and source inputs hash |
| `positions` | Provider schema table | Live and dry-run positions | Quantity cannot be negative for Alpaca |
| `position_events` | Provider schema table | Position transition history | Prior and new state are both recorded |
| `alpaca_account_snapshots` | Provider schema table | Broker account state | Account ID must match configured provider/environment |
| `comparison_metric_snapshots` | Shared table | Materialized dashboard metrics | Missing metrics store unavailable reason |
| `venue_portfolio_snapshots` | Shared table | Sanitized venue account balances and P&L by environment, provider, and account | Credential material is never stored |
| `venue_position_snapshots` | Shared table | Open positions tied to a confirmed portfolio snapshot | Snapshot and account references are required |
| `venue_confirmed_fills` | Shared table | Deduplicated venue-confirmed executions | Simulated and unfilled orders are excluded |

### 2.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Postgres unavailable before live order | Block live order and surface degraded status | REQ-DB-007 |
| 2 | Duplicate order idempotency key | Return existing intent or duplicate-refusal result | REQ-EXE-016 |
| 3 | Claude and OpenAI Alpaca credentials resolve to same account ID | Block duplicated account live trading | REQ-ALP-016 |
| 4 | Broker position and Postgres position mismatch | Persist mismatch and block affected Alpaca live orders | REQ-ALP-018 |
| 5 | Audit event correction needed | Write new corrective audit event, do not mutate original | REQ-OBS-004 |

### 2.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| DB connection failure | SQLAlchemy | Raise `PersistenceUnavailableError`; trading refuses live action | Yes |
| Unique constraint conflict | Postgres | Convert to typed duplicate/refusal result where expected | Yes, for order/config conflicts |
| Migration failure | Alembic | Fail CI/deploy step | Yes, CI logs |
| Serialization mismatch | Repository hydration | Raise validation error and mark dashboard degraded | Yes |

### 2.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Data Integrity | Live orders require durable persistence first | Transactional `UnitOfWork` and order-intent insert before submit |
| Concurrency | Multiple workers must not overlap unsafe work | Advisory locks, job rows, unique reservations |
| Auditability | History retained indefinitely | No TTL/archive/delete job in v1 |
| Testability | Repositories testable with local Postgres | Docker Compose Postgres and migrations |

### 2.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Domain models | Pydantic objects | Validated persisted objects |
| Exports to | Services | `UnitOfWork`, repositories | Transactions and query/write methods |
| Exports to | CI/CD | `run_migrations()` | Migration status |

### 2.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Local tests can run Postgres through Docker rather than SQLite. | SQLite would not validate schemas/advisory locks. | ACCEPTED BY TESTING APPROACH |

---

## 3. Config Service

**File:** `backend/app/services/config_service.py`  
**Responsibility:** Read, validate, update, version, seed, and audit runtime configuration.  
**Requirements Covered:** REQ-VEN-002, REQ-VEN-003, REQ-VEN-006, REQ-ALP-007, REQ-ALP-014, REQ-LLM-006, REQ-LLM-007, REQ-STR-002, REQ-STR-009, REQ-EXE-001, REQ-EXE-003, REQ-EXE-007, REQ-NOT-006, REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-DEP-010  
**Dependencies:** Domain models, database repositories, audit service  
**Depended On By:** API routers, workers, risk engine, adapters, dashboard

### 3.1 Public Interface

#### `class ConfigService`

- **Purpose:** Own active runtime config lifecycle by environment and config owner.
- **Traces:** REQ-UI-005, REQ-UI-007
- **Methods:**
  - `config_for_next_loop(environment: str, username: str | None = None) -> ConfigReloadResult`
  - `latest_config_owner(environment: str, allowed_usernames: tuple[str, ...]) -> str | None`
  - `save_config_patches(request: ConfigUpdateRequest, actor: ActorContext, username: str | None = None) -> ConfigSaveResult`
  - `seed_defaults(environment: str) -> ConfigSnapshot`
  - `activate_kill_switch(actor: ActorContext) -> KillSwitchState`
- **Raises/Errors:** Raises `ConfigValidationError`, `AuthorizationError`, or `PersistenceUnavailableError`.
- **Side Effects:** Writes config versions and audit events.

#### `class ConfigUpdateRequest(BaseModel)`

- **Purpose:** Validates dashboard config writes.
- **Traces:** REQ-UI-005, REQ-ALP-014, REQ-NOT-006
- **Fields:** `environment`, `base_version`, `patch`, `reason`.
- **Returns:** Validated config update request.
- **Raises/Errors:** Rejects stale base version, invalid paths, and unsupported values.
- **Side Effects:** None.

### 3.2 Internal Implementation Details

#### Versioned Updates

- **What it does:** Applies dashboard patches to a config snapshot and persists a new immutable owner-scoped version.
- **Why this approach:** Workers use one stable snapshot per loop, and changes apply next loop.
- **Complexity:** O(n) in config document size.
- **Key steps:**
  1. Load active version by environment and normalized owner, falling back to the shared row when no user row exists.
  2. Validate `base_version` to avoid overwriting a newer dashboard change.
  3. Apply patch.
  4. Validate full config.
  5. Persist new owner-scoped version and audit old/new values.

#### Scheduler Owner Resolution

- **What it does:** Chooses the database config owner used by the background scheduler when no explicit `RUNTIME_CONFIG_USERNAME` is set.
- **Why this approach:** Multi-user dashboard saves are stored by authenticated user, so the worker must resolve the same owner before loading the next-loop snapshot.
- **Complexity:** O(active config versions for the environment).
- **Key steps:**
  1. Use `RUNTIME_CONFIG_USERNAME` when configured.
  2. Use the only allowlisted username in single-user deployments.
  3. In multi-user deployments, read active config versions and select the latest allowlisted user-owned row for the environment.
  4. Fall back to shared config only when no user-owned config exists or persistence is unavailable.

#### Kill Switch Override

- **What it does:** Disables live trading immediately and records active kill-switch state.
- **Why this approach:** Kill switch cannot wait for ordinary next-loop config behavior.
- **Complexity:** O(1) config write plus O(n) open-order cancel follow-up in execution service.
- **Key steps:**
  1. Start DB transaction.
  2. Write new config version with `live_enabled=false`.
  3. Write kill-switch state and audit event.
  4. Commit before returning API success.

### 3.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `ConfigSnapshot` | Pydantic model | Full runtime config | Immutable once persisted |
| `ConfigPatch` | JSON patch subset | Dashboard edit | Only approved paths allowed |
| `ConfigOwner` | String | Normalized username or `__shared__` for shared fallback | User-owned rows never overwrite shared rows |
| `ActorContext` | Pydantic model | Authenticated user and request metadata | Contains username, environment, IP |

#### Seeded Defaults

| Config Path | Default | REQ Trace |
|-------------|---------|-----------|
| `default_selected_venue` | `polymarket_us` | REQ-VEN-002 |
| `live_enabled` | `false` | REQ-EXE-001 |
| `venues.*.enabled` | `false` | REQ-VEN-003 |
| `risk.polymarket.max_position_usd` | `25.00` | REQ-EXE-004 |
| `risk.polymarket.max_daily_loss_usd` | `50.00` | REQ-EXE-005 |
| `risk.polymarket.max_open_positions` | `5` | REQ-EXE-006 |
| `risk.polymarket.market_order_slippage_threshold` | `0.02` | REQ-EXE-012 |
| `risk.alpaca.max_position_usd` | `100.00` | REQ-ALP-009 |
| `risk.alpaca.max_daily_loss_usd` | `100.00` | REQ-ALP-010 |
| `risk.alpaca.max_open_positions` | `5` | REQ-ALP-011 |
| `risk.alpaca.max_portfolio_allocation_per_symbol` | `0.10` | REQ-ALP-012 |
| `risk.alpaca.market_order_slippage_threshold` | `0.005` | REQ-ALP-013 |
| `alpaca.account_mode` | `paper` | REQ-ALP-007 |
| `alpaca.allowed_asset_classes` | `stocks`, `etfs` | REQ-ALP-002 |
| `alpaca.allow_shorting` | `false` | REQ-ALP-008 |
| `alpaca.allow_margin` | `false` | REQ-ALP-008 |
| `alpaca.extended_hours_enabled` | `false` | REQ-ALP-015 |
| `trading_loop_interval_seconds` | `60` | REQ-STR-001 |
| `max_kelly_fraction` | `0.25` | REQ-EXE-008 |

### 3.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Dashboard edits stale config version | Reject with conflict and current version | REQ-UI-007 |
| 2 | User enables Alpaca live mode without account capital | Reject config or mark Alpaca live refused | REQ-ALP-014 |
| 3 | User sets loop interval below safe minimum | Reject validation | REQ-STR-002 |
| 4 | User disables a venue with open orders | Save config but execution still reconciles/cancels known open orders when needed | REQ-EXE-015 |
| 5 | Notification recipient has no email | Save allowlist but mark notification setup incomplete | REQ-NOT-006 |
| 6 | Seed defaults run twice | Return existing active defaults without duplicating active config | REQ-DEP-010 |
| 7 | Multi-user scheduler has no explicit runtime owner | Select the latest active allowlisted user config from the database, falling back to shared config only when none exists | REQ-UI-007 |

### 3.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Invalid config value | Pydantic/domain validation | Reject request with field-level message | Yes |
| Stale base version | Config repository | Return conflict result | Yes |
| DB unavailable | Repository | Raise `PersistenceUnavailableError`; API returns degraded error | Yes |
| Unauthorized actor | Auth service | Raise `AuthorizationError` | Yes |

### 3.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Auditability | Every config change records old/new values | Config updates call audit service in same transaction |
| Data Integrity | Workers must see consistent config | Immutable config versions |
| Security | Only allowlisted users can mutate config | API calls auth service before config service |
| Testability | Config validation testable without adapters | Pure Pydantic validation and repository mocks |

### 3.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Database layer | Config repositories and unit of work | Config versions |
| Imports | Audit service | `record_event()` | Config change audit |
| Exports to | Workers | `get_active()` | Config snapshot |
| Exports to | Dashboard API | `update_config()` | Updated config snapshot |

### 3.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Dashboard edits use a constrained JSON patch rather than replacing entire config documents. | Full replacement would increase accidental deletion risk. | DESIGN CHOICE |

---

## 4. Auth Service

**File:** `backend/app/services/auth_service.py`  
**Responsibility:** Validate signed Next.js session tokens and enforce GitHub username allowlist for protected API actions.  
**Requirements Covered:** REQ-UI-002, REQ-UI-003, REQ-UI-006, REQ-UI-008, REQ-OBS-004  
**Dependencies:** Config service or config repository, JWT/session verifier, domain models  
**Depended On By:** API routers, config service caller paths, dashboard mutation endpoints

### 4.1 Public Interface

#### `class AuthService`

- **Purpose:** Authorize dashboard API requests.
- **Traces:** REQ-UI-002, REQ-UI-003
- **Methods:**
  - `authenticate(token: str, request_context: RequestContext) -> ActorContext`
  - `require_allowlisted(actor: ActorContext) -> None`
  - `require_admin_action(actor: ActorContext, action: str) -> None`
  - `validate_mutation_request(request_context: RequestContext) -> None`
- **Raises/Errors:** Raises `AuthenticationError` or `AuthorizationError`.
- **Side Effects:** None.

#### `class RequestContext(BaseModel)`

- **Purpose:** Carries request metadata needed for secure auth and audit.
- **Traces:** REQ-UI-006, REQ-OBS-004
- **Fields:** `ip_address`, `origin`, `csrf_token`, `forwarded_for`, `request_id`.
- **Raises/Errors:** Validation rejects missing IP address or request ID.
- **Side Effects:** None.

#### `class ActorContext(BaseModel)`

- **Purpose:** Carries authenticated user and request metadata.
- **Traces:** REQ-UI-006, REQ-OBS-004
- **Fields:** `github_username`, `email`, `ip_address`, `session_id`, `environment`, `authenticated_at`.
- **Raises/Errors:** Validation rejects missing username or environment.
- **Side Effects:** None.

### 4.2 Internal Implementation Details

#### Signed Session Validation

- **What it does:** Verifies the token from Next.js before allowing API access.
- **Why this approach:** FastAPI must not trust unsigned headers from the frontend.
- **Complexity:** O(1) cryptographic verification per request.
- **Key steps:**
  1. Verify signature, issuer, audience, and expiration.
  2. Validate same-origin or CSRF token for mutation requests.
  3. Resolve IP address using configured trusted proxy headers only.
  4. Extract GitHub username and email.
  5. Load allowlist from active config.
  6. Return actor context or raise authorization error.

### 4.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `ActorContext` | Pydantic model | Authenticated principal | Username and environment present |
| `RequestContext` | Pydantic model | Request metadata | IP and request ID present |
| `AllowlistEntry` | Config model | GitHub username and optional email | Username is unique per environment |

### 4.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Token is expired | Reject request | REQ-UI-002 |
| 2 | Username not on allowlist | Deny dashboard API access | REQ-UI-003 |
| 3 | Token has valid username but wrong audience | Reject request | REQ-UI-002 |
| 4 | Allowlist config unavailable | Deny mutation actions and surface degraded status | REQ-UI-003 |
| 5 | Mutation request has untrusted origin | Reject request | REQ-UI-002 |
| 6 | Proxy headers are present from untrusted source | Ignore forwarded IP and use direct client IP | REQ-UI-006 |

### 4.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Missing token | API request | Return 401 | Yes |
| Invalid token | Session verifier | Return 401 and log reason category only | Yes |
| Not allowlisted | Config allowlist | Return 403 | Yes |
| Config unavailable | Database/config | Return 503 for protected writes | Yes |
| CSRF or origin validation fails | Request context | Return 403 | Yes |

### 4.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Security | Do not trust frontend headers | Signed token verification in API |
| Security | Mutations require CSRF/same-origin protection | `validate_mutation_request()` |
| Security | CORS restricted by active environment | API router middleware uses config-provided dashboard origin |
| Auditability | Mutations need actor context | `ActorContext` passed to config/audit services |
| Privacy | Do not log token contents | Logs include only reason category and username when safe |

### 4.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Config service/repository | Allowlist read | GitHub usernames and emails |
| Exports to | API routers | `authenticate()` | Actor context |
| Exports to | Audit service callers | `ActorContext` | User metadata |

### 4.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Next.js auth library can mint a signed token accepted by FastAPI. | If not, API will need direct GitHub token introspection. | DESIGN ASSUMPTION |

---

## 5. Audit Service

**File:** `backend/app/services/audit_service.py`  
**Responsibility:** Persist append-only audit events and provide query access for dashboard and debugging.  
**Requirements Covered:** REQ-UI-006, REQ-EXE-016, REQ-OBS-001, REQ-OBS-003, REQ-OBS-004, REQ-OBS-005, REQ-DB-006  
**Dependencies:** Domain models, database repositories  
**Depended On By:** Config service, execution service, risk engine, notification service, API routers

### 5.1 Public Interface

#### `class AuditService`

- **Purpose:** Create and query audit events.
- **Traces:** REQ-OBS-003, REQ-OBS-004, REQ-OBS-005
- **Methods:**
  - `record_event(uow: UnitOfWork, event: AuditEventCreate) -> AuditEvent`
  - `record_config_change(uow: UnitOfWork, actor: ActorContext, changes: list[ConfigChange]) -> AuditEvent`
  - `record_order_event(uow: UnitOfWork, order_event: OrderAuditEvent) -> AuditEvent`
  - `list_events(filters: AuditEventFilter, limit: int = 100) -> list[AuditEvent]`
- **Raises/Errors:** Raises `PersistenceUnavailableError` if audit event cannot be persisted.
- **Side Effects:** Writes append-only audit records.

#### `class AuditEventCreate(BaseModel)`

- **Purpose:** Validated audit event input.
- **Traces:** REQ-OBS-001
- **Fields:** `event_type`, `environment`, `actor`, `correlation_id`, `entity_type`, `entity_id`, `old_value`, `new_value`, `reason`, `metadata`, `occurred_at`, `created_at`.
- **Raises/Errors:** Validation rejects missing event type or environment.
- **Side Effects:** None.

### 5.2 Internal Implementation Details

#### Append-Only Auditing

- **What it does:** Stores each audit event as an immutable row.
- **Why this approach:** Preserves review trail for live trading and dashboard changes.
- **Complexity:** O(1) insert, O(log n) query with indexes.
- **Key steps:**
  1. Validate event.
  2. Attach correlation ID and timestamps if missing.
  3. Insert audit row through the caller's `UnitOfWork`.
  4. Return persisted event.

Sensitive actions fail if audit persistence fails. This includes config changes, live-mode toggles, kill-switch activation, wallet/account status changes, order submit/refusal/fill/cancel/failure events, and manual reconciliation acknowledgements.

### 5.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `AuditEvent` | Shared table/domain model | Immutable event record | No application update/delete path |
| `ConfigChange` | Pydantic model | Old/new config value | Has path, old value, new value |
| `OrderAuditEvent` | Pydantic model | Order lifecycle event context | Has order ID and status |

### 5.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Config change includes secret value | Redact before persistence | REQ-WAL-003 |
| 2 | Audit write fails during live order preparation | Block live order | REQ-OBS-003 |
| 3 | Dashboard requests too many events | Enforce max limit | REQ-OBS-005 |
| 4 | Corrective audit needed | Add new event instead of editing old event | REQ-DB-006 |

### 5.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Persistence failure | Database | Raise and block sensitive action | Yes |
| Secret detected in metadata | Redaction filter | Redact and persist redaction marker | No, except audit detail shows redacted |
| Invalid filter | API request | Return validation error | Yes |

### 5.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Auditability | Sensitive actions need durable records | Append-only event table |
| Security | Secrets must not be logged | Redaction filter before persistence |
| Observability | Events need trace correlation | Correlation ID on every event |
| Performance | Dashboard should load recent events quickly | Indexed filters and bounded limits |

### 5.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Database layer | Audit repository | Audit rows |
| Imports | Domain models | Audit event schemas | Validated audit objects |
| Exports to | Dashboard API | `list_events()` | Recent audit events |
| Exports to | Services | `record_event()` | Durable audit trail |

### 5.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Audit rows are immutable at the application layer; DB admins could still alter data outside the app. | Stronger tamper resistance would require WORM storage or hash chaining. | ACCEPTED FOR V1 |

---

## 6. Venue Ports

**File:** `backend/app/ports/venue.py`  
**Responsibility:** Define venue-neutral interfaces for market data, account state, order execution, cancellation, and reconciliation.  
**Requirements Covered:** REQ-VEN-001, REQ-VEN-003, REQ-VEN-004, REQ-VEN-005, REQ-DAT-001, REQ-DAT-002, REQ-ALP-001, REQ-ALP-003, REQ-ALP-015, REQ-ALP-017, REQ-EXE-010, REQ-EXE-011, REQ-EXE-015, REQ-EXE-016, REQ-EXT-006, REQ-OBS-006  
**Dependencies:** Domain models, typing protocols  
**Depended On By:** Polymarket adapters, Alpaca adapter, ingestion service, execution service, exit monitor, tests

### 6.1 Public Interface

#### `class MarketDataPort(Protocol)`

- **Purpose:** Fetch venue-neutral market or instrument data for scanning, scoring, and risk checks.
- **Traces:** REQ-VEN-001, REQ-ALP-001, REQ-DAT-001, REQ-DAT-002
- **Methods:**
  - `list_active_instruments(config: VenueConfig) -> VenueCallResult[list[InstrumentSnapshot]]`
  - `get_market_snapshot(instrument: Instrument) -> VenueCallResult[MarketSnapshot]`
  - `get_order_book(instrument: Instrument) -> VenueCallResult[OrderBookSnapshot | None]`
  - `is_data_stale(snapshot: MarketSnapshot, threshold_seconds: int) -> bool`
- **Raises/Errors:** Raises only for adapter bugs or unsupported interface use; expected provider failures return `VenueCallResult(ok=False)`.
- **Side Effects:** External read calls only.

#### `class SnapshotIngestionPort(Protocol)`

- **Purpose:** Fetch full and incremental raw venue snapshots for S3 ingestion.
- **Traces:** REQ-DAT-001, REQ-DAT-002
- **Methods:**
  - `fetch_full_snapshot(config: VenueConfig, window: SnapshotWindow) -> VenueCallResult[RawVenueSnapshot]`
  - `fetch_incremental_snapshot(config: VenueConfig, checkpoint: IngestionCheckpoint) -> VenueCallResult[RawVenueSnapshot]`
- **Raises/Errors:** Raises only for adapter bugs; unavailable/rate-limited venues return failure results.
- **Side Effects:** External read calls only.

#### `class OrderExecutionPort(Protocol)`

- **Purpose:** Submit, cancel, and reconcile venue orders.
- **Traces:** REQ-VEN-004, REQ-ALP-003, REQ-EXE-010, REQ-EXE-016
- **Methods:**
  - `submit_order(intent: OrderIntent, credentials: VenueCredentials) -> VenueCallResult[VenueOrderAck]`
  - `cancel_order(ref: VenueOrderRef, credentials: VenueCredentials) -> VenueCallResult[VenueCancelAck]`
  - `get_order(ref: VenueOrderRef, credentials: VenueCredentials) -> VenueCallResult[VenueOrderState]`
- **Raises/Errors:** Raises only for adapter bugs; ambiguous submits return `VenueCallResult(ok=False, error_code="AMBIGUOUS_SUBMIT")`.
- **Side Effects:** May submit or cancel live orders.

#### `class ReconciliationPort(Protocol)`

- **Purpose:** Fetch venue state needed to reconcile local order and position records.
- **Traces:** REQ-ALP-017, REQ-EXE-015, REQ-EXE-016, REQ-EXT-006
- **Methods:**
  - `get_account_state(credentials: VenueCredentials) -> VenueCallResult[VenueAccountState]`
  - `list_open_orders(credentials: VenueCredentials) -> VenueCallResult[list[VenueOrderState]]`
  - `list_positions(credentials: VenueCredentials) -> VenueCallResult[list[VenuePositionState]]`
  - `list_fills(credentials: VenueCredentials, since: datetime) -> VenueCallResult[list[VenueFillState]]`
  - `list_order_activity(credentials: VenueCredentials, since: datetime) -> VenueCallResult[list[VenueOrderActivity]]`
  - `reconcile_order(ref: VenueOrderRef, credentials: VenueCredentials) -> VenueCallResult[ReconciliationResult]`
- **Raises/Errors:** Raises only for adapter bugs; expected provider failures return failure results.
- **Side Effects:** External read calls only.

#### `class VenueHealthPort(Protocol)`

- **Purpose:** Report health, account mode, rate-limit, and credential status.
- **Traces:** REQ-VEN-005, REQ-ALP-015, REQ-OBS-006
- **Methods:**
  - `check_health(config: VenueConfig, credentials: VenueCredentials | None) -> VenueCallResult[VenueHealth]`
  - `get_rate_limit_state() -> RateLimitState`
- **Raises/Errors:** Returns degraded health for expected failures; raises only on adapter bugs.
- **Side Effects:** External read calls only.

### 6.2 Internal Implementation Details

#### Adapter Contract

- **What it does:** Forces Polymarket and Alpaca adapters to expose the same execution and reconciliation semantics.
- **Why this approach:** Execution and risk code should not know SDK-specific response shapes.
- **Complexity:** O(1) translation per adapter response.
- **Key steps:**
  1. Convert domain request into provider request.
  2. Execute provider call with timeout and retry rules.
  3. Convert provider response into domain state.
  4. Surface ambiguity explicitly for submit calls.

### 6.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `InstrumentSnapshot` | Pydantic model | Active market, stock, or ETF listing | Has venue and instrument type |
| `MarketSnapshot` | Pydantic model | Latest price/quote/market state | Includes data timestamp |
| `RawVenueSnapshot` | Pydantic model | Raw full or incremental snapshot | Has snapshot window and checksum input |
| `IngestionCheckpoint` | Pydantic model | Last successful ingestion boundary | Monotonic per environment/venue |
| `VenueCallResult[T]` | Generic Pydantic model | Expected provider success/failure envelope | Provider failures do not use exceptions |
| `VenueOrderRef` | Pydantic model | Local and venue order identity | Fields: `local_order_id: str`, `idempotency_key: str`, `venue_order_id: str | None`, `venue: Venue`, `environment: str`, `model_provider: ModelProvider`, `instrument: Instrument`, `side: OrderSide` |
| `OrderBookSnapshot` | Pydantic model | Bids/asks or equivalent depth | Sorted best price first |
| `VenueOrderState` | Pydantic model | Venue order status | Mapped to domain order state |
| `VenueAccountState` | Pydantic model | Account ID, status, buying power where available | Account ID present for Alpaca |
| `VenueFillState` | Pydantic model | Fill execution record | Has venue order ID and fill timestamp |
| `VenueOrderActivity` | Pydantic model | Broker/venue activity event | Has activity type and timestamp |
| `ReconciliationResult` | Pydantic model | Local/venue match or mismatch summary | Mismatch includes blocking reason |
| `VenueHealth` | Pydantic model | Venue health result | Contains status and refusal reason if degraded |

### 6.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Venue is disabled for new work | New scan, score, and entry order calls are blocked before adapter call | REQ-VEN-003 |
| 2 | Submit timeout may have reached venue | Return ambiguous-submit result; execution starts reconciliation | REQ-EXE-016 |
| 3 | Order book unavailable for market order | Market order risk check refuses | REQ-EXE-011 |
| 4 | Alpaca market data rate-limited | Return degraded health and rate-limited refusal | REQ-ALP-015 |
| 5 | Unsupported venue requested | Raise `UnsupportedVenueError` | REQ-VEN-005 |
| 6 | Venue disabled after live orders were created | Allow cancel, reconciliation, and status reads for known open orders | REQ-EXE-015 |

### 6.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Read timeout | Venue API | Return failure result after retries | Yes |
| Submit timeout | Venue API | Return ambiguous-submit result, do not blind retry | Yes |
| Rate limit | Venue API | Return rate-limited result and defer candidate | Yes |
| Bad credentials | Venue API | Return auth-failure result, mark credential stale and refuse live orders | Yes |

### 6.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Testability | Adapters need contract tests | Protocols define mockable interfaces |
| Data Integrity | Execution needs normalized order states | Venue states map into domain states |
| Security | Credentials must not leak | Credentials are opaque objects, never logged |
| Observability | Venue errors need status | `VenueHealth` and structured error categories |

### 6.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Exports to | Execution service | `OrderExecutionPort`, `ReconciliationPort` | Orders, cancels, positions, fills, account state |
| Exports to | Ingestion/scanner | `MarketDataPort`, `SnapshotIngestionPort` | Market snapshots and raw snapshots |
| Implemented by | Polymarket adapters | Protocols | Prediction market data/orders |
| Implemented by | Alpaca adapter | Protocols | Stock/ETF data/orders |

### 6.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Venue-specific SDKs can be wrapped without leaking provider response types into domain services. | Execution service would need provider branches. | DESIGN ASSUMPTION |

---

## 7. Polymarket Adapters

**File:** `backend/app/adapters/polymarket/`  
**Responsibility:** Integrate with Polymarket US and International official SDK or documented APIs for market data, order books, orders, cancellations, and position reconciliation.  
**Requirements Covered:** REQ-VEN-001, REQ-VEN-003, REQ-VEN-004, REQ-VEN-005, REQ-DAT-001, REQ-DAT-002, REQ-DAT-005, REQ-EXE-010, REQ-EXE-011, REQ-EXE-013, REQ-EXE-015, REQ-EXE-016, REQ-EXT-006, REQ-OBS-001  
**Dependencies:** Venue ports, secrets adapter, config service, official Polymarket SDK or documented HTTP APIs  
**Depended On By:** Ingestion service, strategy engine, risk engine, execution service, exit monitor

### 7.1 Public Interface

#### `class PolymarketClient(MarketDataPort, SnapshotIngestionPort, OrderExecutionPort, ReconciliationPort, VenueHealthPort)`

- **Purpose:** Venue-specific adapter for Polymarket US or International.
- **Traces:** REQ-VEN-001, REQ-VEN-004
- **Constructor Parameters:** `venue: Venue`, `http_client`, `clock`, `logger`.
- **Methods:** Implements all venue port methods.
- **Raises/Errors:** Raises `UnsupportedVenueError` if constructed for non-Polymarket venue.
- **Side Effects:** External API calls, live order submission/cancel when called by execution service.

#### `map_polymarket_order_state(raw: dict) -> VenueOrderState`

- **Purpose:** Normalize Polymarket order state into domain state.
- **Traces:** REQ-EXE-016
- **Parameters:** Raw SDK/API order payload.
- **Returns:** `VenueOrderState`.
- **Raises/Errors:** Raises `AdapterMappingError` if required fields are missing.
- **Side Effects:** None.

### 7.2 Internal Implementation Details

#### Polymarket Venue Selection

- **What it does:** Uses config to choose US or International API base and credential references.
- **Why this approach:** Same adapter shape supports both Polymarket venues without duplicating execution code.
- **Complexity:** O(1) per adapter call.
- **Key steps:**
  1. Validate venue is explicitly enabled for new scan, score, and entry-order work.
  2. Resolve venue base URL and credential reference.
  3. Use read-only calls without wallet credentials where supported.
  4. Require wallet/API credentials for live order calls.
  5. Allow cancel, status, and reconciliation calls for known open orders even if the venue was disabled after those orders were created.

#### Market Order Guardrail Support

- **What it does:** Provides order book depth for execution slippage estimation.
- **Why this approach:** Market orders need current depth before submission.
- **Complexity:** O(n) over visible book levels.
- **Key steps:**
  1. Fetch order book for instrument.
  2. Normalize bid/ask levels into `OrderBookSnapshot`.
  3. Risk engine estimates slippage from the snapshot.

### 7.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `PolymarketVenueConfig` | Pydantic model | Base URL, enabled flag, stale threshold | Venue is US or International |
| `PolymarketCredentials` | Opaque secret model | Wallet/API credential references | Secret values never logged |
| `PolymarketMarketSnapshot` | Adapter model | Raw market converted to domain snapshot | Has market/outcome IDs |
| `PolymarketRawSnapshot` | Adapter model | Full or incremental raw snapshot | Has checkpoint/window metadata |

### 7.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | International venue not explicitly enabled | Refuse scan/score/trade before API call | REQ-VEN-003 |
| 2 | Market data older than threshold | Mark stale and block dependent live orders | REQ-DAT-005 |
| 3 | Live order missing wallet credential | Refuse before submit | REQ-EXE-013 |
| 4 | Submit response unknown after timeout | Return ambiguous-submit result | REQ-EXE-016 |
| 5 | Cancel open order fails | Return cancel failure state for retry | REQ-EXE-015 |
| 6 | Venue disabled after order was placed | Permit cancel/reconcile/status calls for that known order | REQ-EXE-015 |

### 7.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| API timeout on read | Polymarket API | Return failure result after retries | Yes |
| API timeout on submit | Polymarket API | Return ambiguous-submit result, reconcile | Yes |
| Auth failure | Polymarket API | Mark credential stale, refuse live orders | Yes |
| Mapping failure | Adapter | Raise `AdapterMappingError`, dashboard degraded | Yes |

### 7.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Compliance | No unsupported venue behavior | Explicit venue enabled/config checks |
| Data Integrity | Orders reconcile after ambiguous states | Order state mapping and list open orders |
| Testability | API calls mockable | Adapter depends on injected HTTP/SDK client |
| Observability | Venue failures traceable | Structured errors with venue and correlation ID |

### 7.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Implements | Venue ports | `MarketDataPort`, `SnapshotIngestionPort`, `OrderExecutionPort`, `ReconciliationPort` | Snapshots, orders, positions, fills |
| Imports | Secrets adapter | Credential lookup | Wallet/API credentials |
| Exports to | Ingestion service | Market snapshots | Raw/normalized data |
| Exports to | Execution service | Order operations | Submit/cancel/reconcile |

### 7.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Official SDK/API exposes enough order and position data to reconcile unknown submits. | Reconciliation may need additional documented endpoints. | DESIGN ASSUMPTION |

---

## 8. Alpaca Adapter

**File:** `backend/app/adapters/alpaca/`  
**Responsibility:** Integrate with Alpaca for long-only stocks and ETFs, account health, market data, market calendar, orders, cancellations, positions, and reconciliation.  
**Requirements Covered:** REQ-ALP-001, REQ-ALP-002, REQ-ALP-003, REQ-ALP-004, REQ-ALP-008, REQ-ALP-015, REQ-ALP-016, REQ-ALP-017, REQ-ALP-018, REQ-DAT-001, REQ-DAT-002, REQ-EXE-010, REQ-EXE-011, REQ-EXE-016  
**Dependencies:** Venue ports, secrets adapter, Alpaca official Python SDK or documented HTTP APIs, config service  
**Depended On By:** Ingestion service, strategy engine, risk engine, execution service, comparison service

### 8.1 Public Interface

#### `class AlpacaClient(MarketDataPort, SnapshotIngestionPort, OrderExecutionPort, ReconciliationPort, VenueHealthPort)`

- **Purpose:** Adapter for Alpaca stock and ETF trading.
- **Traces:** REQ-ALP-001, REQ-ALP-003
- **Constructor Parameters:** `account_mode: AlpacaAccountMode`, `sdk_client`, `data_client`, `clock`, `logger`.
- **Methods:** Implements all venue port methods plus Alpaca-specific helpers below.
- **Raises/Errors:** Returns `VenueCallResult` failures for expected provider conditions; raises `UnsupportedAssetClassError` only for adapter misuse.
- **Side Effects:** External Alpaca calls, live/paper order submission when called by execution service.

#### `get_account_snapshot(credentials: VenueCredentials) -> VenueCallResult[AlpacaAccountSnapshot]`

- **Purpose:** Fetch account ID, buying power, equity, status, and account mode.
- **Traces:** REQ-ALP-004, REQ-ALP-016, REQ-ALP-017
- **Returns:** Account snapshot.
- **Raises/Errors:** Returns auth-failure result on rejected credentials.
- **Side Effects:** External read call.

#### `get_market_calendar(date: date) -> VenueCallResult[MarketCalendarDay]`

- **Purpose:** Determine regular market open/close, holidays, and early closes.
- **Traces:** REQ-ALP-015
- **Returns:** Calendar day object.
- **Raises/Errors:** Returns failure result if calendar cannot be fetched.
- **Side Effects:** External read call.

#### `validate_asset_tradable(symbol: str) -> VenueCallResult[AssetTradability]`

- **Purpose:** Check whether a symbol is stock/ETF, tradable, not halted/suspended, and eligible for v1.
- **Traces:** REQ-ALP-002, REQ-ALP-008, REQ-ALP-015
- **Returns:** Tradability result.
- **Raises/Errors:** Returns refusal state for unsupported or untradable assets.
- **Side Effects:** External read call or cache read.

### 8.2 Internal Implementation Details

#### Account Isolation Check

- **What it does:** Verifies Claude and OpenAI credentials resolve to separate Alpaca account IDs per environment/account mode.
- **Why this approach:** Prevents mixed P&L and risk across models.
- **Complexity:** O(n) over configured model providers.
- **Key steps:**
  1. Load credentials for each model provider.
  2. Fetch account snapshot.
  3. Compare account IDs for duplicates.
  4. Persist duplicate-account refusal state if duplicates exist.

#### Long-Only Order Mapping

- **What it does:** Converts approved order intents into Alpaca buy-to-open or sell-to-close requests.
- **Why this approach:** v1 excludes short selling and margin.
- **Complexity:** O(1) per order.
- **Key steps:**
  1. Validate asset class and tradability.
  2. Validate regular market hours and stale-data threshold.
  3. Use notional order where supported.
  4. Round down to whole shares if fractional unsupported.
  5. Set time in force `day` and extended-hours `false`.

#### Alpaca Snapshot Ingestion

- **What it does:** Produces full and incremental raw snapshots for configured symbol universes and account state.
- **Why this approach:** Ingestion service owns S3/checkpoints, while the adapter owns Alpaca-specific data collection.
- **Complexity:** O(n) over configured symbols and recent account activities.
- **Key steps:**
  1. Full snapshot fetches asset metadata, previous-market-day bars where available, account snapshot, positions, open orders, and recent activity.
  2. Incremental snapshot fetches changed account state, positions, orders, fills, quotes or bars, and activity since checkpoint.
  3. Corporate actions are included when exposed by account activity or selected data plan.
  4. Snapshot returns raw payload plus source timestamps and checkpoint candidate.

### 8.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `AlpacaAccountSnapshot` | Pydantic model | Account ID, equity, buying power, status | Account ID present |
| `MarketCalendarDay` | Pydantic model | Regular session open/close | Extended hours excluded |
| `AssetTradability` | Pydantic model | Asset class and trading status | Only stock/ETF allowed |
| `AlpacaMarketSnapshot` | Pydantic model | Quote/bar timestamp and price data | Timestamp required |
| `AlpacaOrderRequest` | Adapter model | SDK/API order request | No short/margin fields enabled |
| `AlpacaRawSnapshot` | Adapter model | Full or incremental Alpaca snapshot | Has account/symbol window metadata |

### 8.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Claude/OpenAI credentials resolve to same account ID | Block Alpaca live trading for duplicated account | REQ-ALP-016 |
| 2 | Quote is stale for one symbol | Refuse live orders for that symbol only | REQ-ALP-015 |
| 3 | Market is closed, holiday, or early close passed | Refuse live orders | REQ-ALP-015 |
| 4 | Asset is option, crypto, suspended, halted, or non-tradable | Refuse live orders | REQ-ALP-002 |
| 5 | Sell order exceeds broker/Postgres reconciled quantity | Refuse order | REQ-ALP-008 |
| 6 | Fractional unsupported and rounded quantity is zero | Refuse order | REQ-EXE-010 |
| 7 | Broker/Postgres mismatch unresolved | Block affected model provider live orders | REQ-ALP-018 |
| 8 | Alpaca market data rate-limited | Mark `DEFERRED_RATE_LIMITED` and expose dashboard status | REQ-ALP-015 |
| 9 | Manual broker activity changes position outside bot | Record mismatch and block affected model live orders | REQ-ALP-018 |
| 10 | Split, dividend, or symbol change changes broker state | Use account activity/corporate action data when available; otherwise block affected symbol | REQ-ALP-018 |
| 11 | Partial fill arrives after local cancel request | Reconcile fill, update position, keep remaining cancel state | REQ-ALP-017 |
| 12 | Cancel race leaves order open at broker | Keep order cancel-requested and retry with backoff | REQ-EXE-016 |
| 13 | Broker buying power differs from Postgres snapshot | Refresh account snapshot; block live orders if mismatch remains | REQ-ALP-017 |
| 14 | Broker account status is restricted, inactive, or mismatched to configured mode | Block Alpaca live orders for that model provider | REQ-ALP-017 |
| 15 | Broker account ID differs from configured account identifier | Block Alpaca live orders and record account mismatch | REQ-ALP-016 |

### 8.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Auth failure | Alpaca API | Return auth-failure result, mark credential stale, refuse live orders | Yes |
| Rate limit | Alpaca API | Return rate-limited result, defer symbol, emit metric | Yes |
| Submit timeout | Alpaca API | Return ambiguous-submit result and reconcile before retry | Yes |
| Reconciliation mismatch | Broker/Postgres | Block affected model provider | Yes |
| Unsupported asset | Alpaca asset metadata | Refuse with explicit reason | Yes |

### 8.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Safety | No short/margin in v1 | Long-only validation and sell-to-close cap |
| Data Integrity | Broker is source of holdings | Reconciliation before live orders |
| Security | Separate accounts per model | Account ID duplicate check |
| Observability | Alpaca-specific status | Rate-limit, stale data, account health metrics |
| Testability | SDK calls mockable | Injected SDK/data clients and contract tests |

### 8.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Implements | Venue ports | Market/snapshot/order/reconciliation/health protocols | Alpaca snapshots, orders, fills, account state |
| Imports | Secrets adapter | Credential lookup | Alpaca keys |
| Exports to | Risk engine | Account and market snapshots | Buying power, positions, quotes |
| Exports to | Execution service | Submit/cancel/reconcile | Alpaca order states |

### 8.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Alpaca account IDs are stable and exposed by account endpoint. | Duplicate-account guard would need another identity field. | DESIGN ASSUMPTION |

---

## 9. AWS Adapters

**File:** `backend/app/adapters/aws/`  
**Responsibility:** Provide S3 snapshot storage, Secrets Manager secret access, and SES email delivery with AWS-safe defaults.  
**Requirements Covered:** REQ-DAT-003, REQ-DAT-004, REQ-DAT-006, REQ-DAT-007, REQ-DAT-008, REQ-WAL-003, REQ-WAL-007, REQ-NOT-001, REQ-NOT-003, REQ-NOT-004, REQ-NOT-007, REQ-DEP-002, REQ-OBS-002  
**Dependencies:** boto3 or AWS SDK, domain models, config service  
**Depended On By:** Ingestion service, wallet service, notification service, deployment

### 9.1 Public Interface

#### `class S3StorageAdapter`

- **Purpose:** Store and retrieve raw and normalized snapshots.
- **Traces:** REQ-DAT-003, REQ-DAT-004, REQ-DAT-006, REQ-DAT-007
- **Methods:**
  - `put_snapshot(snapshot: SnapshotObject) -> S3ObjectMetadata`
  - `get_snapshot(key: str) -> bytes`
  - `build_snapshot_key(environment: str, venue: Venue, snapshot_type: str, dt: date, window_id: str, extension: str) -> str`
- **Raises/Errors:** Raises `SnapshotStorageError`.
- **Side Effects:** Writes/reads S3 objects.

#### `class SecretsAdapter`

- **Purpose:** Resolve AWS Secrets Manager secrets in deployed environments.
- **Traces:** REQ-WAL-003, REQ-WAL-007
- **Methods:**
  - `get_secret(ref: SecretRef) -> SecretValue`
  - `invalidate(ref: SecretRef) -> None`
  - `mark_stale(ref: SecretRef, reason: str) -> None`
- **Raises/Errors:** Raises `SecretUnavailableError`.
- **Side Effects:** Reads Secrets Manager and updates local cache.

#### `class SesEmailAdapter`

- **Purpose:** Send daily digest and alert emails through SES.
- **Traces:** REQ-NOT-001, REQ-NOT-003, REQ-NOT-004, REQ-NOT-007
- **Methods:**
  - `send_email(message: EmailMessage) -> EmailDeliveryResult`
  - `send_digest(digest: DigestEmail) -> EmailDeliveryResult`
  - `send_alert(alert: AlertEmail) -> EmailDeliveryResult`
- **Raises/Errors:** Returns failure result for SES delivery failures.
- **Side Effects:** Sends email through SES.

### 9.2 Internal Implementation Details

#### S3 Key Builder

- **What it does:** Builds partitioned keys matching HLD.
- **Why this approach:** Required for lifecycle rules and deterministic retries.
- **Complexity:** O(1).
- **Key steps:**
  1. Validate environment, venue, snapshot type, date, and window ID.
  2. Return `{environment}/{venue}/{snapshot_type}/dt={YYYY-MM-DD}/{window_id}.{extension}`.
  3. Attach tags for lifecycle and metadata.

#### S3 Idempotency and Checksum Handling

- **What it does:** Treats retries safely when a deterministic snapshot key already exists.
- **Why this approach:** Checkpoints advance only after S3 and Postgres metadata both succeed.
- **Complexity:** O(1) metadata lookup plus checksum comparison.
- **Key steps:**
  1. Calculate SHA-256 checksum before upload. Do not rely on multipart ETag as the checksum.
  2. If the key exists with the same checksum, return idempotent success.
  3. If the key exists with a different checksum, mark the new snapshot as conflict/corrupt and do not advance checkpoint.
  4. Persist conflict metadata for dashboard and retry diagnosis.

#### Secret Cache

- **What it does:** Caches secrets with TTL and invalidation on config change.
- **Why this approach:** Supports credential rotation without reading secrets on every call.
- **Complexity:** O(1) cache lookup.
- **Key steps:**
  1. Check in-memory cache and expiration.
  2. Read Secrets Manager if missing/stale.
  3. Store value with expiration.
  4. Never log secret contents.

### 9.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `SnapshotObject` | Pydantic model | Snapshot bytes and metadata | Has checksum and key parts |
| `S3ObjectMetadata` | Pydantic model | Stored object key, etag, SHA-256 checksum | Key follows partition format |
| `SecretRef` | Pydantic model | Secret path reference | Does not contain secret value |
| `EmailMessage` | Pydantic model | SES message | Recipients non-empty |
| `EmailDeliveryResult` | Pydantic model | SES result | Failure has error summary |

### 9.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | S3 write succeeds but DB checkpoint fails | Deterministic key/checksum allow retry without duplicate logical ingestion | REQ-DAT-008 |
| 2 | Snapshot type missing from key parts | Reject before S3 write | REQ-DAT-004 |
| 3 | Secret rotated in Secrets Manager | Use updated secret on next refresh/invalidation | REQ-WAL-007 |
| 4 | SES delivery fails | Persist failure and retry with backoff | REQ-NOT-007 |
| 5 | Recipient list empty | Return failure result and mark notification config incomplete | REQ-NOT-001 |
| 6 | Same S3 key exists with same checksum | Return idempotent success | REQ-DAT-008 |
| 7 | Same S3 key exists with different checksum | Mark conflict/corrupt and preserve checkpoint | REQ-DAT-008 |

### 9.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| S3 put failure | AWS | Raise storage error; ingestion preserves checkpoint | Yes |
| Secrets Manager denied | AWS/IAM | Raise secret unavailable; live orders refuse | Yes |
| SES throttling | AWS SES | Failure result with retry metadata | Yes |
| KMS access denied | AWS | Raise adapter error and surface deployment/security misconfig | Yes |

### 9.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Security | Secrets and buckets encrypted | KMS-backed AWS resources, no secret logging |
| Data Integrity | Snapshot writes deterministic | Partitioned keys and checksums |
| Cost/Data Lifecycle | S3 retention enforced | CloudFormation lifecycle rules |
| Observability | AWS failures visible | Structured adapter errors and CloudWatch logs |

### 9.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Exports to | Ingestion service | `S3StorageAdapter` | Snapshot objects |
| Exports to | Wallet/venue adapters | `SecretsAdapter` | Secret values |
| Exports to | Notification service | `SesEmailAdapter` | Email delivery |

### 9.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | SES identity verification is handled by deployment/runbook before production alerts. | Emails would fail until identity is verified. | DEPLOYMENT ASSUMPTION |

---

## 10. LLM Ports and Provider Adapters

**File:** `backend/app/ports/llm.py`, `backend/app/adapters/llm/`  
**Responsibility:** Provide provider-neutral scoring interface and concrete OpenAI/Claude adapters with current-config scoring inputs and outputs.  
**Requirements Covered:** REQ-LLM-001, REQ-LLM-003, REQ-LLM-004, REQ-LLM-005, REQ-OBS-001  
**Dependencies:** Domain models, secrets adapter, provider SDKs/APIs, scoring repositories  
**Depended On By:** Scoring service, strategy engine, comparison service

### 10.1 Public Interface

#### `class LlmProviderPort(Protocol)`

- **Purpose:** Score a market or stock/ETF candidate through a provider.
- **Traces:** REQ-LLM-001, REQ-LLM-003
- **Methods:**
  - `score_candidate(request: LlmScoreRequest) -> LlmCallResult[ScoringOutput]`
  - `estimate_cost(request: LlmScoreRequest) -> Decimal`
  - `health_check() -> LlmCallResult[LlmProviderHealth]`
- **Raises/Errors:** Raises only for adapter bugs; expected provider failures return `LlmCallResult(ok=False)`.
- **Side Effects:** External LLM API calls.

#### `class OpenAiProvider(LlmProviderPort)`

- **Purpose:** OpenAI scoring adapter.
- **Traces:** REQ-LLM-001, REQ-LLM-003
- **Constructor Parameters:** `client`, `model_name`, `timeout_seconds`, `logger`.
- **Side Effects:** OpenAI API calls.

#### `class ClaudeProvider(LlmProviderPort)`

- **Purpose:** Claude scoring adapter.
- **Traces:** REQ-LLM-001, REQ-LLM-003
- **Constructor Parameters:** `client`, `model_name`, `timeout_seconds`, `logger`.
- **Side Effects:** Anthropic API calls.

### 10.2 Internal Implementation Details

#### Provider-Neutral Prompt Contract

- **What it does:** Converts candidate data into a shared prompt/input schema and requires structured output.
- **Why this approach:** Allows comparison between OpenAI and Claude on the same inputs.
- **Complexity:** O(n) in prompt input size.
- **Key steps:**
  1. Build `LlmScoreRequest` from filtered candidate.
  2. Include config version, loop run ID, candidate fingerprint, venue, instrument, current price, liquidity, data timestamp, strategy context, and risk context.
  3. Request structured output with thesis, confidence, estimated probability, and reasoning summary.
  4. Validate output into `ScoringOutput`.

#### Budget Reservation Contract

- **What it does:** Keeps provider calls tied to a scoring-service budget reservation.
- **Why this approach:** Prevents spending beyond provider budget.
- **Complexity:** O(1) per request.
- **Key steps:**
  1. Estimate provider cost.
  2. Scoring service creates a DB-backed reservation before calling the provider.
  3. `LlmScoreRequest` includes `budget_reservation_id`.
  4. Provider call runs with timeout.
  5. Provider output includes actual usage when available so scoring service can reconcile estimate versus actual cost.
  6. Timeout or provider failure returns a failure result so scoring service can release or mark the reservation failed.

The provider adapter does not mutate budget state directly. Atomic reservation, release, and actual-cost reconciliation are owned by the scoring service and database layer.

### 10.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `LlmScoreRequest` | Pydantic model | Provider-neutral scoring request | Has prompt version, config version, loop run ID, candidate fingerprint, budget reservation ID, and instrument |
| `ScoringOutput` | Pydantic model | Provider-neutral scoring output | Has config version, loop run ID, candidate fingerprint; probability/confidence bounded |
| `LlmCallResult[T]` | Generic Pydantic model | Expected provider success/failure envelope | Provider failures do not use exceptions |
| `LlmProviderHealth` | Pydantic model | Provider status | Has provider name and status |
| `BudgetReservation` | Pydantic model | Reserved estimated spend | Non-negative amount |

### 10.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Scoring service does not provide a budget reservation ID | Refuse provider call before external API request | REQ-LLM-003 |
| 2 | Provider timeout | Block orders for that provider/market in current loop | REQ-LLM-005 |
| 3 | Provider output is not parseable | Record scoring failure and block model-specific order | REQ-LLM-005 |
| 4 | Candidate input fingerprint missing | Refuse provider call before external API request | REQ-LLM-003 |
| 5 | Both providers score same input | Persist both outputs separately by provider schema | REQ-LLM-001 |
| 6 | Provider queue deadline misses current loop | Return deferred result and do not create live order for that loop | REQ-LLM-005 |
| 7 | Budget reservation cannot be created because provider budget is exhausted | Return `DEFERRED_BUDGET_EXHAUSTED`; scoring service records deferred candidate for next loop | REQ-LLM-004 |

### 10.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Provider rate limit | LLM API | Return rate-limited result, defer candidates | Yes |
| Timeout | LLM API | Return timeout result, no live order for provider/candidate | Yes |
| Invalid structured output | Provider response | Return validation-failure result | Yes |
| Missing API key | Secrets/config | Return provider-unavailable result | Yes |

### 10.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Cost Control | Separate model budgets | Budget reservation before call |
| Testability | Providers mockable | Protocol and injected clients |
| Comparability | Same input shape for both models | Provider-neutral request schema |
| Observability | Failures and costs visible | Scoring output/failure records and structured logs |
| Performance | Bounded provider concurrency | Provider adapters honor scoring-service queue and timeout settings |
| Performance | Deferred candidates are reconsidered | Provider failure results include retryable/deferred status for scoring service persistence |

### 10.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Implements | LLM port | `score_candidate()` | Scoring outputs |
| Imports | Secrets adapter | API key lookup | Provider credentials |
| Exports to | Scoring service | Provider interface | Scores, failures, costs |
| Exports to | Comparison service | Scoring records | Model cost metrics |

### 10.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Provider SDKs can return or estimate enough usage data to support model-cost metrics. | Cost metrics may rely on estimates. | DESIGN ASSUMPTION |

---

## 11. Ingestion Service

**File:** `backend/app/services/ingestion_service.py`  
**Responsibility:** Orchestrate full and incremental venue snapshots, validation, normalization, S3 storage, and checkpoint persistence.  
**Requirements Covered:** REQ-DAT-001, REQ-DAT-002, REQ-DAT-003, REQ-DAT-004, REQ-DAT-005, REQ-DAT-006, REQ-DAT-007, REQ-DAT-008, REQ-ALP-015, REQ-OBS-001, REQ-OBS-006  
**Dependencies:** `SnapshotIngestionPort`, `S3StorageAdapter`, database repositories, config service, audit service, retry policy config  
**Depended On By:** Worker scheduler, dashboard status, risk engine stale-data checks

### 11.1 Public Interface

#### `class IngestionService`

- **Purpose:** Execute configured ingestion jobs for enabled venues.
- **Traces:** REQ-DAT-001, REQ-DAT-002, REQ-DAT-008
- **Methods:**
  - `run_full_snapshot(config: ConfigSnapshot, venue: Venue, run_id: str) -> IngestionRunResult`
  - `run_incremental_snapshot(config: ConfigSnapshot, venue: Venue, run_id: str) -> IngestionRunResult`
  - `get_staleness(environment: str, venue: Venue, instrument: Instrument | None = None) -> DataStalenessStatus`
- **Raises/Errors:** Raises only for service bugs; expected adapter/S3/validation failures return `IngestionRunResult(ok=False)`.
- **Side Effects:** Writes S3 objects, checkpoint rows, ingestion metadata, audit/log events.

#### `class IngestionRunResult(BaseModel)`

- **Purpose:** Captures ingestion result for worker status and dashboard.
- **Traces:** REQ-DAT-008, REQ-OBS-006
- **Fields:** `ok`, `environment`, `venue`, `snapshot_type`, `run_id`, `object_keys`, `checkpoint_before`, `checkpoint_after`, `retry_state`, `error_code`, `message`.
- **Raises/Errors:** Validation rejects `ok=true` without object keys and checkpoint status.
- **Side Effects:** None.

### 11.2 Internal Implementation Details

#### Full Snapshot Flow

- **What it does:** Fetches a complete venue snapshot and stores raw plus normalized data.
- **Why this approach:** Provides replayable daily baseline.
- **Complexity:** O(n) over instruments and raw payload size.
- **Key steps:**
  1. Acquire ingestion job lock through scheduler.
  2. Resolve enabled venue and active config version.
  3. Call `fetch_full_snapshot()`.
  4. Validate non-empty payload when venue reports data.
  5. Build deterministic S3 key and checksum.
  6. Store raw and normalized outputs.
  7. Persist metadata and advance checkpoint in one transaction.
  8. Clear prior retry state for the same environment, venue, and snapshot type.

#### Incremental Snapshot Flow

- **What it does:** Fetches changed data since the last checkpoint.
- **Why this approach:** Reduces data volume and supports fresher risk checks.
- **Complexity:** O(k) over changed records.
- **Key steps:** Same as full flow, using `fetch_incremental_snapshot(checkpoint)` and preserving the checkpoint on failure. Expected failures persist retry state from the active `RetryPolicy`.

### 11.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `IngestionCheckpoint` | DB/domain model | Last successful full/incremental boundary | Monotonic per environment/venue/snapshot type |
| `IngestionRunResult` | Pydantic model | Worker-visible result | Failure has error code |
| `SnapshotMetadata` | DB/domain model | S3 key, checksum, row counts, source timestamps | Checksum is SHA-256 |
| `DataStalenessStatus` | Pydantic model | Staleness by venue/instrument | Stale status has threshold and observed age |
| `RetryPolicy` | Config model | Max attempts, base delay, max delay, jitter, retryable error codes | Positive delays and attempts |
| `IngestionRetryState` | DB/domain model | Attempts, last error, next attempt time, exhausted flag | One active state per job key |

### 11.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Incremental job starts while full job active for same venue | Skip incremental and record skipped status | REQ-DAT-002 |
| 2 | S3 write succeeds but checkpoint transaction fails | Preserve checkpoint; retry uses deterministic key/checksum | REQ-DAT-008 |
| 3 | Payload is empty but venue says records exist | Mark corrupt and do not advance checkpoint | REQ-DAT-008 |
| 4 | Alpaca symbol quote is stale | Mark symbol stale and block dependent live orders | REQ-ALP-015 |
| 5 | Same S3 key has different checksum | Mark conflict/corrupt and do not advance checkpoint | REQ-DAT-008 |
| 6 | Retry attempts exhausted | Keep checkpoint unchanged and surface exhausted retry status | REQ-DAT-008 |

### 11.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Venue result failure | Snapshot port | Return failed run, keep checkpoint, persist `next_attempt_at` if retryable | Yes |
| S3 failure | AWS adapter | Return failed run, keep checkpoint, persist `next_attempt_at` if retryable | Yes |
| Validation failure | Ingestion service | Quarantine metadata and keep checkpoint | Yes |
| DB failure | Repository | Return failed run; live orders use stale status | Yes |

### 11.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Data Integrity | Checkpoints advance only after storage and metadata persist | Single transaction after S3 success |
| Observability | Ingestion failures visible | Run result, audit/log event, dashboard staleness |
| Reliability | Retry behavior is testable | Persisted retry attempts, capped exponential backoff, jitter, exhausted state |
| Cost | S3 retention enforced | Lifecycle rules in infrastructure |
| Performance | Full ingestion should not block dashboard | Runs in worker loop with job heartbeat |

### 11.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Venue adapters | `SnapshotIngestionPort` | Raw snapshots |
| Imports | AWS adapters | `S3StorageAdapter` | Snapshot objects |
| Imports | Database layer | Checkpoint and metadata repositories | Checkpoint updates |
| Exports to | Risk engine | `get_staleness()` | Stale data status |

### 11.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Normalization format can be finalized in implementation while preserving raw snapshots. | Downstream analytics may need schema updates. | DESIGN ASSUMPTION |

---

## 12. Wallet Service and CLI

**File:** `backend/app/services/wallet_service.py`, `backend/app/cli/wallets.py`  
**Responsibility:** Generate Polymarket wallet material, validate Alpaca account credentials, manage secret references, and expose safe wallet/account status.  
**Requirements Covered:** REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-004, REQ-WAL-005, REQ-WAL-006, REQ-WAL-007, REQ-ALP-004, REQ-ALP-016, REQ-DEP-007  
**Dependencies:** Secrets adapter, local env loader, Alpaca adapter, Polymarket adapter, database repositories, audit service  
**Depended On By:** Config service, dashboard API, execution service, deployment setup

### 12.1 Public Interface

#### `class WalletService`

- **Purpose:** Manage venue credential references and safe status.
- **Traces:** REQ-WAL-001, REQ-WAL-005, REQ-WAL-006
- **Methods:**
  - `generate_polymarket_wallet(request: WalletGenerationRequest) -> WalletGenerationResult`
  - `validate_alpaca_credentials(ref: SecretRef, model_provider: ModelProvider) -> AlpacaAccountSnapshot`
  - `get_credential_status(environment: str, venue: Venue, model_provider: ModelProvider) -> CredentialStatus`
  - `refresh_credential(ref: SecretRef) -> CredentialStatus`
- **Raises/Errors:** Raises only for service bugs; expected missing/invalid credentials return status/refusal objects.
- **Side Effects:** Writes local `.env` guidance or Secrets Manager values depending on environment, writes audit events.

#### `wallets generate --environment ENV --venue VENUE --model-provider PROVIDER`

- **Purpose:** CLI entrypoint for wallet generation.
- **Traces:** REQ-WAL-002
- **Outputs:** Public identifier, secret reference path, and next setup step. Never prints private key after storage confirmation.
- **Side Effects:** Creates local `.env` entry instructions or deployed secret value.

### 12.2 Internal Implementation Details

#### Secret Placement

- **What it does:** Stores deployed secrets in Secrets Manager and local development secrets in gitignored `.env`.
- **Why this approach:** Matches local/dev/prod safety requirements.
- **Complexity:** O(1).
- **Key steps:**
  1. Determine environment.
  2. Generate or validate credentials.
  3. Store secret or output local `.env` instructions.
  4. Persist non-secret metadata only.
  5. Audit action with secret values redacted.

### 12.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `WalletGenerationRequest` | Pydantic model | Environment, venue, model provider | Venue/model provider required |
| `WalletGenerationResult` | Pydantic model | Public ID and secret ref | No private key value |
| `CredentialStatus` | Pydantic model | Present/stale/missing/invalid status | Secret value absent |

### 12.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | CLI asked to generate Alpaca account | Refuse; Alpaca accounts are external, validate credentials only | REQ-ALP-004 |
| 2 | Dashboard asks for private key | API never exposes private key | REQ-WAL-005 |
| 3 | Credential missing during live order | Execution refuses before venue call | REQ-WAL-006 |
| 4 | Secret rotated | Cache invalidates and new secret used on refresh | REQ-WAL-007 |
| 5 | Alpaca duplicate account ID across model providers | Status is blocked for duplicated account | REQ-ALP-016 |

### 12.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Secret write fails | Secrets adapter | Return setup failure and do not persist metadata | Yes |
| Local `.env` missing | Local loader | Return missing credential status | Yes |
| Alpaca credential invalid | Alpaca adapter | Return invalid credential status | Yes |
| Audit write fails | Audit service | Fail sensitive operation | Yes |

### 12.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Security | Never expose secrets in dashboard/logs | Redacted result models |
| Auditability | Credential actions tracked | Audit service in same transaction |
| Testability | Secret backends mockable | Injected secret/local env adapters |

### 12.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | AWS adapters | `SecretsAdapter` | Secret values |
| Imports | Venue adapters | Credential validation | Account/wallet status |
| Exports to | Execution service | Credential status | Refusal checks |
| Exports to | Dashboard API | Safe status | Public IDs only |

### 12.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Alpaca accounts are created outside the bot, and the bot only validates credentials. | Account provisioning would require additional flow. | REQUIREMENT-ALIGNED |

---

## 13. Scoring Service

**File:** `backend/app/services/scoring_service.py`  
**Responsibility:** Filter candidates for LLM scoring, reserve model budgets, call OpenAI and Claude providers, persist scoring outputs/failures, and expose current-score lookup.  
**Requirements Covered:** REQ-LLM-001, REQ-LLM-002, REQ-LLM-003, REQ-LLM-004, REQ-LLM-005, REQ-LLM-006, REQ-LLM-007, REQ-STR-003, REQ-OBS-001  
**Dependencies:** LLM provider ports, database repositories, config service, audit service  
**Depended On By:** Strategy engine, risk engine, comparison service, dashboard

### 13.1 Public Interface

#### `class ScoringService`

- **Purpose:** Own model-provider scoring lifecycle.
- **Traces:** REQ-LLM-001, REQ-LLM-003, REQ-LLM-004, REQ-LLM-005
- **Methods:**
  - `score_candidates(config: ConfigSnapshot, loop_run_id: str, candidates: list[Candidate]) -> list[ScoringOutcome]`
  - `get_current_score(model_provider: ModelProvider, instrument: Instrument, config_version: int) -> ScoringOutput | None`
  - `reserve_budget(model_provider: ModelProvider, estimate: Decimal, loop_run_id: str) -> BudgetReservationResult`
  - `reconcile_budget(reservation_id: str, actual_cost: Decimal | None, status: str) -> None`
- **Raises/Errors:** Raises only for service bugs; provider failures are persisted as scoring outcomes.
- **Side Effects:** Writes budget ledger, scoring records, failure records.

### 13.2 Internal Implementation Details

#### Score Candidate Flow

- **What it does:** Runs both providers on eligible candidates when budget and loop deadline allow.
- **Why this approach:** Enables direct Claude/OpenAI comparison.
- **Complexity:** O(p * c), where p is providers and c is candidates passing filters.
- **Key steps:**
  1. Build candidate fingerprint from normalized input.
  2. For each provider, reserve estimated budget in DB.
  3. Submit provider call through bounded queue.
  4. Persist scoring output/failure with config version and loop run ID.
  5. Reconcile budget estimate with actual cost where available.
  6. Record `DEFERRED`, `DEFERRED_RATE_LIMITED`, or `DEFERRED_BUDGET_EXHAUSTED` for candidates not scored this loop.

### 13.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `Candidate` | Domain model | Instrument plus normalized scoring context | Has fingerprint input |
| `ScoringOutcome` | Pydantic model | Score, failure, or deferred state | Has provider/instrument/config version |
| `BudgetLedgerEntry` | DB/domain model | Reservation, actual cost, status | Provider budget cannot overspend under lock |
| `CurrentScoreIndex` | Query model | Latest score by provider/instrument/config | Must match active config version for live trading |

### 13.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Provider budget exhausted | Record `DEFERRED_BUDGET_EXHAUSTED`; continue other provider | REQ-LLM-004 |
| 2 | Provider timeout | Persist failure and block model/instrument live order this loop | REQ-LLM-005 |
| 3 | Score exists for older config version | Do not use for live trading | REQ-LLM-005 |
| 4 | Candidate misses loop deadline | Record `DEFERRED`; reconsider next loop | REQ-LLM-001 |
| 5 | Actual cost unavailable | Reconcile using estimate and mark actual unavailable | REQ-LLM-003 |

### 13.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Budget reservation conflict | DB | Retry under lock or mark deferred | Yes |
| Provider failure | LLM adapter | Persist failure outcome | Yes |
| Invalid output | LLM adapter/domain validation | Persist validation failure | Yes |
| DB failure after provider response | Repository | Mark service degraded; live trading blocked by missing current score | Yes |

### 13.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Cost Control | Separate budgets per provider | DB-backed reservations |
| Data Integrity | Live orders require current score | Config-versioned current-score lookup |
| Performance | Loop must not stall on LLMs | Bounded queues, deadlines, deferred outcomes |
| Comparability | Same candidate input per provider | Candidate fingerprint and shared prompt contract |

### 13.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | LLM adapters | `score_candidate()` | Scoring outputs |
| Imports | Database layer | Budget/scoring repositories | Ledger and outputs |
| Exports to | Strategy engine | Current scores | Probability/confidence/thesis |
| Exports to | Comparison service | Cost and scores | Model metrics |

### 13.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Candidate fingerprint can be built from normalized input without storing full prompt in every table. | Debugging may need prompt archive references. | DESIGN ASSUMPTION |

---

## 14. Strategy Engine and Strategies

**File:** `backend/app/strategies/`  
**Responsibility:** Run deterministic filters, generate strategy signals, and apply consensus rules across arbitrage, convergence, whale-copy, and Alpaca stock/ETF strategies.  
**Requirements Covered:** REQ-STR-001, REQ-STR-002, REQ-STR-003, REQ-STR-004, REQ-STR-005, REQ-STR-006, REQ-STR-007, REQ-STR-008, REQ-STR-009, REQ-ALP-001, REQ-ALP-002, REQ-ALP-015  
**Dependencies:** Config service, scoring service, ingestion/staleness, venue adapters, database repositories  
**Depended On By:** Worker scheduler, risk engine, dashboard

### 14.1 Public Interface

#### `class StrategyEngine`

- **Purpose:** Coordinate candidate filtering, scoring inputs, strategy signals, and consensus.
- **Traces:** REQ-STR-003, REQ-STR-007, REQ-STR-008
- **Methods:**
  - `build_candidates(config: ConfigSnapshot, snapshots: list[MarketSnapshot]) -> list[Candidate]`
  - `generate_signals(config: ConfigSnapshot, scores: list[ScoringOutput]) -> list[StrategySignal]`
  - `apply_consensus(signals: list[StrategySignal], config: ConfigSnapshot) -> list[TradeDecision]`
- **Raises/Errors:** Expected no-trade outcomes return neutral/empty decisions; exceptions reserved for service bugs.
- **Side Effects:** Persists strategy signals and trade decisions.

#### Strategy modules

- `ArbitrageStrategy.evaluate(candidate, score, config) -> StrategySignal`
- `ConvergenceStrategy.evaluate(candidate, score, config) -> StrategySignal`
- `WhaleCopyStrategy.evaluate(candidate, target_wallet_state, config) -> StrategySignal`
- `AlpacaStockStrategy.evaluate(candidate, score, account_state, config) -> StrategySignal`

### 14.2 Internal Implementation Details

#### Consensus Rule

- **What it does:** Converts strategy signals into trade decisions.
- **Why this approach:** Prevents single weak signals from overtrading.
- **Complexity:** O(n) per model/instrument signal group.
- **Key steps:**
  1. Group signals by environment, venue, model provider, instrument, and side.
  2. Ignore disabled strategies and neutral signals.
  3. If two or more enabled strategies agree, create full-strength decision.
  4. If one enabled strategy agrees and no conflict exists, create half-strength decision.
  5. If buy/sell conflict or tie exists, create no-trade decision.

### 14.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `Candidate` | Domain model | Filtered instrument for scoring/strategy | Has stale-data status |
| `StrategySignal` | Domain model | Strategy vote | Persisted before decision |
| `TradeDecision` | Domain model/table | Consensus decision | References signal IDs and score IDs |
| `TargetWalletState` | Domain model | Whale-copy target wallet holdings | Source timestamp present |

### 14.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | All strategies disabled | No trade decisions | REQ-STR-009 |
| 2 | Signals conflict buy vs sell | No trade decision | REQ-STR-008 |
| 3 | One strategy signal only | Half-strength decision | REQ-STR-008 |
| 4 | Alpaca symbol halted or stale | No Alpaca candidate/live signal | REQ-ALP-015 |
| 5 | Whale target data stale | Whale-copy emits neutral signal | REQ-STR-006 |
| 6 | No related market group exists | Arbitrage emits neutral signal | REQ-STR-004 |

### 14.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Missing current score | Scoring service | No model-specific trade decision | Yes |
| Invalid strategy config | Config validation | Reject config before loop | Yes |
| Strategy calculation error | Strategy module | Mark strategy degraded and continue other strategies | Yes |

### 14.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Testability | Strategies need isolated tests | Pure evaluate methods |
| Auditability | Signals persisted before decisions | Signal repositories |
| Performance | Filters reduce LLM load | Deterministic filters before scoring |
| Extensibility | Add strategies later | Strategy interface and registry |

### 14.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Scoring service | Current scores | Scores/theses |
| Imports | Ingestion service | Staleness and target wallet state | Candidate filters |
| Exports to | Risk engine | Trade decisions | Direction, size strength, signals |
| Exports to | Dashboard | Strategy signals/decisions | Status and history |

### 14.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Arbitrage relation groups can be manually configured before automated relation discovery is mature. | Fewer arbitrage signals early. | DESIGN ASSUMPTION |

---

## 15. Risk Engine

**File:** `backend/app/services/risk_engine.py`  
**Responsibility:** Apply global and venue-specific risk checks, Kelly sizing, slippage checks, stale-data checks, and expected refusal results before execution.  
**Requirements Covered:** REQ-VEN-003, REQ-VEN-005, REQ-WAL-006, REQ-LLM-005, REQ-DAT-005, REQ-EXE-001, REQ-EXE-002, REQ-EXE-004, REQ-EXE-005, REQ-EXE-006, REQ-EXE-007, REQ-EXE-008, REQ-EXE-009, REQ-EXE-011, REQ-EXE-012, REQ-EXE-013, REQ-EXE-014, REQ-EXE-017, REQ-ALP-002, REQ-ALP-008, REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012, REQ-ALP-013, REQ-ALP-015, REQ-ALP-017, REQ-ALP-018  
**Dependencies:** Config service, scoring service, ingestion service, database repositories, venue snapshots, wallet service, reconciliation port, live-control repository  
**Depended On By:** Execution service, exit monitor, dashboard

### 15.1 Public Interface

#### `class RiskEngine`

- **Purpose:** Approve, size, or refuse trade decisions.
- **Traces:** REQ-EXE-008, REQ-EXE-013, REQ-ALP-008
- **Methods:**
  - `evaluate_entry(decision: TradeDecision, config: ConfigSnapshot) -> RiskDecision`
  - `evaluate_exit(position: Position, trigger: ExitTrigger, config: ConfigSnapshot) -> RiskDecision`
  - `evaluate_live_blockers(intent: OrderIntent, config: ConfigSnapshot, control: KillSwitchState) -> list[RiskCheckResult]`
  - `load_alpaca_reconciliation(intent: OrderIntent) -> AlpacaReconciliationSnapshot | None`
  - `kelly_size(probability: Decimal, price: Decimal, capital: Decimal, max_fraction: Decimal) -> Decimal`
  - `estimate_slippage(intent: OrderIntent, market_data: MarketSnapshot | OrderBookSnapshot) -> Decimal`
- **Raises/Errors:** Expected refusals return `RiskDecision(approved=False)`; exceptions reserved for calculation bugs.
- **Side Effects:** Persists risk check results.

### 15.2 Internal Implementation Details

#### Risk Check Order

- **What it does:** Applies cheap and safety-critical checks before sizing and venue calls.
- **Why this approach:** Avoids unnecessary model/venue operations and unsafe orders.
- **Complexity:** O(1) plus O(book levels) for slippage.
- **Key steps:**
  1. Check global live mode from the loop config snapshot.
  2. Read the current non-snapshot `KillSwitchState` from Postgres and refuse live orders if active.
  3. Check venue enabled, venue support, jurisdiction support, account mode, and credential status.
  4. Check current score/config version and model-specific scoring failure state.
  5. Check stale data, trading hours, halts, tradability, and Alpaca reconciliation.
  6. Check daily loss/open positions/position size.
  7. Check Alpaca long-only, account buying power, and allocation rules.
  8. Calculate Kelly size.
  9. Check slippage for market orders.

#### Live Refusal Matrix

- **What it does:** Converts every approved live-order blocker into a stable reason code.
- **Why this approach:** Tests and dashboard status need exact refusal reasons, not broad text.
- **Complexity:** O(1), except exposure and slippage checks.

| Reason Code | Trigger | Result | REQ Trace |
|-------------|---------|--------|-----------|
| `LIVE_DISABLED` | Active config snapshot has global dry-run/live disabled | Approve only simulated execution path | REQ-EXE-001, REQ-EXE-002, REQ-EXE-013 |
| `KILL_SWITCH_ACTIVE` | Current `KillSwitchState.active=true` in Postgres | Refuse live order immediately | REQ-EXE-014 |
| `VENUE_DISABLED` | Venue flag is false | Refuse scan/score/trade | REQ-VEN-003, REQ-EXE-013 |
| `UNSUPPORTED_VENUE_CONFIG` | Venue, jurisdiction, or account mode is unsupported for the environment | Refuse live order and record reason | REQ-VEN-005, REQ-EXE-013 |
| `CREDENTIAL_MISSING` | Wallet, broker, or API credential status is missing/invalid | Refuse before venue call | REQ-WAL-006, REQ-EXE-013 |
| `DB_UNAVAILABLE` | Position, order, score, or config repository cannot be read | Refuse live order | REQ-EXE-013 |
| `SCORING_MISSING_OR_FAILED` | Current provider score is missing, stale config version, or failed this loop | Refuse model/instrument live order | REQ-LLM-005, REQ-EXE-013 |
| `STALE_MARKET_DATA` | Staleness status is stale or unknown | Refuse dependent live order | REQ-DAT-005, REQ-EXE-013 |
| `TRADING_HOURS_CLOSED` | Alpaca clock/calendar or configured hours disallow trading | Refuse Alpaca live order | REQ-ALP-015 |
| `ASSET_NOT_TRADABLE` | Alpaca asset is halted, suspended, non-tradable, option, crypto, or unsupported class | Refuse Alpaca live order | REQ-ALP-002, REQ-ALP-015 |
| `ALPACA_RECON_STALE` | Alpaca reconciliation snapshot is missing or older than configured freshness threshold | Refuse Alpaca live order | REQ-ALP-017 |
| `ALPACA_RECON_MISMATCH` | Broker and Postgres positions, open orders, buying power, account ID, or account status mismatch | Refuse affected model provider | REQ-ALP-017, REQ-ALP-018 |
| `DAILY_LOSS_LIMIT` | Model provider has reached daily loss cap | Refuse live order | REQ-EXE-005, REQ-EXE-013, REQ-ALP-010 |
| `OPEN_POSITION_LIMIT` | Model provider has reached open-position cap | Refuse live order | REQ-EXE-006, REQ-EXE-013, REQ-ALP-011 |
| `MAX_POSITION_LIMIT` | Proposed order exceeds configured position cap | Refuse or cap size before approval | REQ-EXE-004, REQ-EXE-008, REQ-ALP-009 |
| `ALPACA_ALLOCATION_LIMIT` | Proposed Alpaca order exceeds per-symbol allocation | Refuse live order | REQ-ALP-012 |
| `ALPACA_SHORT_OR_MARGIN` | Proposed Alpaca order would short or require margin | Refuse live order | REQ-ALP-008 |
| `SLIPPAGE_DATA_UNAVAILABLE` | Market-order slippage cannot be estimated from current data | Refuse market order | REQ-EXE-011, REQ-ALP-013 |
| `SLIPPAGE_LIMIT` | Estimated slippage exceeds configured threshold | Refuse market order | REQ-EXE-011, REQ-EXE-012, REQ-ALP-013 |
| `KELLY_NON_POSITIVE` | Kelly calculation produces zero or negative size | Refuse trade | REQ-EXE-009 |

### 15.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `RiskDecision` | Domain model | Approval/refusal | Approved decision has positive size |
| `RiskCheckResult` | Domain model | One risk check | Failure has refusal reason |
| `RiskConfig` | Config model | Polymarket/Alpaca limits | Positive numeric limits |
| `AlpacaReconciliationSnapshot` | Domain model | Broker account ID, account mode, account status, buying power, positions, open orders, freshness, mismatch list | Fresh and mismatch-free before Alpaca live order approval |
| `KillSwitchState` | DB/domain model | Current live-control override | Read fresh from Postgres for live checks |

`AlpacaReconciliationSnapshot` fields are `environment`, `model_provider`, `account_mode`, `configured_account_id`, `broker_account_id`, `account_status`, `buying_power`, `broker_positions`, `postgres_positions`, `broker_open_orders`, `postgres_open_orders`, `observed_at`, `freshness_seconds`, `mismatches`, and `is_live_safe`. `is_live_safe` is true only when account ID, account mode, account status, buying power, open orders, and positions reconcile within configured tolerances.

### 15.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Kelly size non-positive | Refuse trade | REQ-EXE-009 |
| 2 | Global dry-run enabled | Approve only simulated execution path | REQ-EXE-002 |
| 3 | Missing current score | Refuse model-specific live order | REQ-EXE-013 |
| 4 | Alpaca order would short | Refuse order | REQ-ALP-008 |
| 5 | Alpaca per-symbol allocation exceeded | Refuse order | REQ-ALP-012 |
| 6 | Slippage exceeds threshold | Refuse market order | REQ-EXE-011 |
| 7 | Alpaca data rate-limited | Refuse live order for affected symbol | REQ-ALP-015 |
| 8 | Kill switch activates after loop config snapshot was read | Refuse live order based on fresh control-plane read | REQ-EXE-014 |
| 9 | Alpaca buying power reconciles as stale or mismatched | Refuse affected model provider live order | REQ-ALP-017, REQ-ALP-018 |

### 15.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Missing risk config | Config service | Refuse live order and mark config degraded | Yes |
| Live-control read fails | Live-control repository | Refuse live order because kill-switch state is unknown | Yes |
| Invalid market data | Venue adapter | Refuse slippage-dependent order | Yes |
| Alpaca reconciliation unavailable | Reconciliation port | Refuse Alpaca live order | Yes |
| Repository unavailable | DB | Refuse live order because limits cannot be checked | Yes |

### 15.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Safety | Refuse on uncertainty | Expected refusal results |
| Data Integrity | Risk checks persisted | Risk check repository |
| Testability | Sizing is deterministic | Pure Kelly/slippage functions |
| Auditability | Refusals visible | Risk decisions flow to execution/audit |

### 15.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Config service | Config snapshot | Limits and flags |
| Imports | Wallet service | Credential status | Missing/invalid credential refusals |
| Imports | Venue adapters | Reconciliation port | Alpaca account and broker state |
| Imports | Database layer | Position/order repositories | Exposure and P&L |
| Imports | Ingestion/venue | Staleness and market data | Risk checks |
| Exports to | Execution service | `RiskDecision` | Approved/refused orders |

### 15.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Kelly sizing uses model probability as calibrated enough for v1, with conservative cap. | Sizing may be too aggressive if probabilities are poorly calibrated. | ACCEPTED RISK |

---

## 16. Execution Service

**File:** `backend/app/services/execution_service.py`  
**Responsibility:** Convert risk-approved decisions into dry-run or live orders, persist order intents before submit, enforce idempotency/reservations, reconcile ambiguous states, and handle kill-switch cancellation.  
**Requirements Covered:** REQ-EXE-002, REQ-EXE-003, REQ-EXE-010, REQ-EXE-013, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-EXE-017, REQ-ALP-005, REQ-ALP-006, REQ-ALP-007, REQ-ALP-017, REQ-ALP-018, REQ-OBS-003  
**Dependencies:** Risk engine, venue ports, database layer, config service, audit service, wallet service, live-control repository, reconciliation port  
**Depended On By:** Worker scheduler, exit monitor, dashboard kill switch

### 16.1 Public Interface

#### `class ExecutionService`

- **Purpose:** Submit or simulate orders after risk approval.
- **Traces:** REQ-EXE-002, REQ-EXE-016, REQ-ALP-005, REQ-ALP-006
- **Methods:**
  - `execute_entry(decision: TradeDecision, risk: RiskDecision, config: ConfigSnapshot) -> ExecutionResult`
  - `execute_exit(position: Position, risk: RiskDecision, config: ConfigSnapshot) -> ExecutionResult`
  - `cancel_open_orders_for_kill_switch(environment: str, actor: ActorContext) -> KillSwitchState`
  - `reconcile_unknown_order(ref: VenueOrderRef) -> ReconciliationResult`
- **Raises/Errors:** Expected refusals return execution results; exceptions reserved for service bugs.
- **Side Effects:** Writes order intents/events, calls venue submit/cancel, writes audit events.

### 16.2 Internal Implementation Details

#### Live Submit Flow

- **What it does:** Safely submits a live order after persistence.
- **Why this approach:** Prevents duplicate live orders and preserves audit trail.
- **Complexity:** O(1) DB writes plus venue call.
- **Key steps:**
  1. Read current `KillSwitchState` outside the loop config snapshot; if active, return refusal before reservation.
  2. Create reservation.
  3. Build idempotency key.
  4. Persist order intent and audit event in one transaction.
  5. Resolve the live submitter from the venue and model provider, for example `polymarket_us:openai` or `alpaca:claude`.
  6. For Alpaca live orders, refresh pre-submit reconciliation and refuse if account ID, account status, buying power, open orders, or positions are stale or mismatched.
  7. Read current `KillSwitchState` again immediately before the venue call; if active, persist `KILL_SWITCH_BLOCKED`, release the reservation, and do not call the venue.
  8. Submit via venue adapter.
  9. Persist venue acknowledgement or ambiguous state.
  10. Release reservation only on terminal state or safe refusal.

#### Kill-Switch Cancel Flow

- **What it does:** Stops new live orders and attempts to cancel known open live orders.
- **Why this approach:** The kill switch must not depend on stale loop config or enabled venue flags.
- **Complexity:** O(n) over open live orders.
- **Key steps:**
  1. Commit live disabled and active kill-switch state in the control-plane table before returning dashboard success.
  2. Query open live orders from order repositories by environment across all model providers, venues, and account modes.
  3. For each known open venue order, call cancel/status through the venue adapter even if that venue is now disabled for new work.
  4. Persist `CANCEL_REQUESTED`, `CANCELED`, `NO_LONGER_OPEN`, `CANCEL_FAILED`, or `MANUAL_REVIEW_REQUIRED` events.
  5. Keep global live disabled until cancel state is terminal or manually acknowledged.

#### Dry-Run Flow

- **What it does:** Records simulated orders without calling venues.
- **Why this approach:** Global dry-run must cover Polymarket and Alpaca.
- **Complexity:** O(1).
- **Key steps:** Persist simulated order intent, simulated fill event, and audit event.

### 16.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `ExecutionResult` | Pydantic model | Submitted/simulated/refused outcome | Has order intent or refusal reason |
| `OrderReservation` | DB/domain model | Prevents conflicting entry/exit | Unique active reservation per model/instrument/side |
| `OrderEvent` | DB/domain model | Order lifecycle event | Append-only |
| `KillSwitchState` | DB/domain model | Current immediate live-control state | Fresh read before live venue submit |

### 16.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Duplicate idempotency key | Return existing order intent and do not resubmit | REQ-EXE-016 |
| 2 | Submit ambiguous | Mark `UNKNOWN_SUBMIT` and reconcile before retry | REQ-EXE-016 |
| 3 | Kill switch active during in-flight decision | Fresh control-plane read stops the decision before any live venue submit | REQ-EXE-014 |
| 4 | Venue disabled after order created | Allow cancel/reconcile for known open order | REQ-EXE-015 |
| 5 | Alpaca global dry-run enabled | Record simulated order only | REQ-ALP-005 |
| 6 | Alpaca live enabled with paper account mode | Submit to configured paper endpoint | REQ-ALP-007 |
| 7 | Kill switch activates after intent persistence but before venue submit | Persist blocked event, release reservation, and do not call venue | REQ-EXE-014, REQ-EXE-016 |
| 8 | Alpaca reconciliation changes after risk approval | Refuse before venue submit and persist mismatch/refusal event | REQ-ALP-017, REQ-ALP-018 |
| 9 | Kill switch cancel requested while venue flag is disabled | Cancel known open orders despite disabled-new-work flag | REQ-EXE-015 |

### 16.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| DB write fails before submit | Database | Do not call venue | Yes |
| Live-control read fails before submit | Live-control repository | Refuse live submit because kill-switch state is unknown | Yes |
| Alpaca pre-submit reconciliation fails | Reconciliation port | Refuse Alpaca live submit | Yes |
| Venue submit failure | Adapter result | Persist failure/refusal event | Yes |
| Ambiguous submit | Adapter result | Persist unknown and reconcile | Yes |
| Audit write fails | Audit service | Fail sensitive action before submit where possible | Yes |

### 16.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Data Integrity | Persist intent before submit | Transactional order-intent flow |
| Concurrency | No conflicting orders | Reservations and idempotency |
| Safety | Kill switch immediate | Fresh control-plane state checked before submit and cancel flow enumerates open orders from repositories |
| Observability | Every order event visible | Audit/order event persistence |

### 16.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Risk engine | Risk decisions | Approved size/refusals |
| Imports | Venue adapters | Order/reconciliation ports | Submit/cancel/state |
| Imports | Database layer | Order/live-control repositories | Intents/events/reservations/open orders/kill state |
| Exports to | Dashboard | Execution results | Status and audit |

### 16.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Venue client order IDs can be mapped back to local idempotency keys. | Reconciliation may require fallback matching by instrument/time/side/size. | DESIGN ASSUMPTION |

---

## 17. Exit Monitor

**File:** `backend/app/services/exit_monitor.py`  
**Responsibility:** Monitor open positions for profit target, volume spike, stale thesis, and venue-specific exit triggers, then route approved exits through risk and execution.  
**Requirements Covered:** REQ-EXT-001, REQ-EXT-002, REQ-EXT-003, REQ-EXT-004, REQ-EXT-005, REQ-EXT-006, REQ-EXE-016, REQ-ALP-008  
**Dependencies:** Database repositories, risk engine, execution service, venue market data, config service  
**Depended On By:** Worker scheduler, dashboard

### 17.1 Public Interface

#### `class ExitMonitor`

- **Purpose:** Evaluate and execute exits for open positions.
- **Traces:** REQ-EXT-001, REQ-EXT-006
- **Methods:**
  - `evaluate_positions(config: ConfigSnapshot, loop_run_id: str) -> list[ExitDecision]`
  - `execute_exit(decision: ExitDecision, config: ConfigSnapshot) -> ExecutionResult`
- **Raises/Errors:** Expected no-exit outcomes return neutral decisions.
- **Side Effects:** Writes exit decisions and may call execution service.

### 17.2 Internal Implementation Details

#### Exit Evaluation

- **What it does:** Checks configured triggers against current market data and position age.
- **Why this approach:** Exits are explicit decisions, not hidden execution side effects.
- **Complexity:** O(n) over open positions.
- **Key steps:**
  1. Load open positions by provider/venue.
  2. Fetch current market data.
  3. Check profit target, volume spike, stale thesis.
  4. For Alpaca, enforce sell-to-close only.
  5. Route approved exit through risk and execution.

### 17.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `ExitDecision` | Pydantic model | Exit trigger and intended action | References position and trigger |
| `ExitTrigger` | Domain model | Trigger type/threshold/observed value | Supported trigger type |

### 17.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Dry-run mode enabled | Record simulated exit only | REQ-EXT-005 |
| 2 | Alpaca sell-to-close exceeds reconciled quantity | Refuse exit order | REQ-ALP-008 |
| 3 | Position already has active reservation | Skip and retry next loop | REQ-EXE-016 |
| 4 | Market data stale | Do not execute exit except kill-switch cancel flow | REQ-EXT-006 |

### 17.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Market data unavailable | Venue adapter | Mark exit evaluation deferred | Yes |
| Execution refusal | Execution service | Persist refusal with trigger context | Yes |
| DB unavailable | Repository | Mark monitor degraded | Yes |

### 17.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Safety | Exits use same risk/execution path | Route through risk and execution |
| Concurrency | Avoid entry/exit conflict | Reservations |
| Auditability | Exit reasons persisted | Exit decisions and audit events |

### 17.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Risk engine | `evaluate_exit()` | Risk decisions |
| Imports | Execution service | `execute_exit()` | Exit orders |
| Imports | Venue adapters | Market data | Trigger evaluation |

### 17.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Exit trigger defaults will be seeded in config and tuned later through dashboard. | Initial exits may be conservative. | DESIGN ASSUMPTION |

---

## 18. Notification Service

**File:** `backend/app/services/notification_service.py`  
**Responsibility:** Build daily digest and large-movement alerts, enforce deduplication/cooldowns, and send through SES.  
**Requirements Covered:** REQ-NOT-001, REQ-NOT-002, REQ-NOT-003, REQ-NOT-004, REQ-NOT-005, REQ-NOT-006, REQ-NOT-007  
**Dependencies:** SES adapter, config service, database repositories, comparison service, retry policy config  
**Depended On By:** Worker scheduler, dashboard

### 18.1 Public Interface

#### `class NotificationService`

- **Purpose:** Generate and deliver configured notifications.
- **Traces:** REQ-NOT-001, REQ-NOT-003, REQ-NOT-004
- **Methods:**
  - `send_daily_digest(config: ConfigSnapshot, run_id: str) -> NotificationResult`
  - `evaluate_large_movement_alerts(config: ConfigSnapshot) -> list[NotificationResult]`
  - `record_delivery(result: EmailDeliveryResult, alert_key: str) -> None`
  - `retry_due_deliveries(config: ConfigSnapshot, run_id: str) -> list[NotificationResult]`
- **Raises/Errors:** Expected SES failures return notification results.
- **Side Effects:** Sends emails, writes delivery attempts and cooldown state.

### 18.2 Internal Implementation Details

#### Alert Deduplication

- **What it does:** Prevents repeated alerts for the same market/model/cooldown window.
- **Why this approach:** Keeps notifications useful.
- **Complexity:** O(1) unique key lookup per alert.
- **Key steps:**
  1. Build alert key from environment, venue, model provider, instrument, alert type, threshold, cooldown window.
  2. Check delivery/cooldown table.
  3. Send only if not already sent in window.
  4. Persist attempt result.

#### SES Retry Flow

- **What it does:** Retries failed digest or alert deliveries when their persisted retry time is due.
- **Why this approach:** SES failures should survive process restarts and deploys.
- **Complexity:** O(n) over due retry attempts.
- **Key steps:**
  1. Load due notification delivery attempts where `next_attempt_at <= now`.
  2. Stop retrying exhausted attempts and mark dashboard status degraded.
  3. Rebuild email content from stored notification payload or snapshot reference.
  4. Send through SES.
  5. Persist success or calculate the next attempt using the configured `RetryPolicy`.

### 18.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `DigestEmail` | Pydantic model | Daily summary | Has recipients and required sections |
| `AlertEmail` | Pydantic model | Large movement alert | Has alert key |
| `NotificationResult` | Pydantic model | Sent/skipped/failed result | Failure has reason |
| `NotificationDeliveryAttempt` | DB/domain model | SES payload reference, attempt count, last error, next attempt time, exhausted flag | One active retry row per notification key |
| `RetryPolicy` | Config model | Max attempts, base delay, max delay, jitter, retryable SES error codes | Positive delays and attempts |

### 18.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Allowlisted user has no email | Skip user and mark notification config incomplete | REQ-NOT-001 |
| 2 | Alert inside cooldown | Skip and record cooldown skip | REQ-NOT-005 |
| 3 | SES throttles send | Persist failure and retry with backoff | REQ-NOT-007 |
| 4 | Metric unavailable for digest | Show unavailable, not zero | REQ-NOT-002 |
| 5 | Retry attempts exhausted | Stop retrying and show exhausted delivery status | REQ-NOT-007 |

### 18.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| SES failure | SES adapter | Persist failed attempt, retry metadata, and `next_attempt_at` if retryable | Yes |
| Missing recipients | Config | Mark incomplete and skip send | Yes |
| DB failure | Repository | Mark notification worker degraded | Yes |

### 18.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Usability | Avoid alert noise | Cooldown/dedup keys |
| Auditability | Delivery attempts retained | Notification repository |
| Reliability | Delivery retry survives restart | Persisted retry state and scheduler due-retry job |
| Security | Recipients from allowlist config | Config-driven recipient mapping |

### 18.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | SES adapter | `send_email()` | Email messages |
| Imports | Comparison service | Metrics | Digest content |
| Imports | Database | Delivery/cooldown repositories | Attempts and state |

### 18.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Daily digest at 07:00 UTC is acceptable after 06:00 UTC full ingestion. | Schedule may need dashboard tuning. | HLD DEFAULT |

---

## 19. Comparison Service

**File:** `backend/app/services/comparison_service.py`  
**Responsibility:** Calculate Claude vs OpenAI performance across Polymarket and Alpaca for dashboard and digest use.  
**Requirements Covered:** REQ-CMP-001, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004, REQ-UI-011, REQ-NOT-002  
**Dependencies:** Database repositories, config service  
**Depended On By:** Dashboard API, notification service

### 19.1 Public Interface

#### `class ComparisonService`

- **Purpose:** Produce comparison metrics by model, venue, instrument type, and window.
- **Traces:** REQ-CMP-001, REQ-CMP-002, REQ-CMP-003
- **Methods:**
  - `calculate_metrics(filter: ComparisonFilter) -> list[ComparisonMetric]`
  - `get_dashboard_summary(environment: str, window: MetricWindow) -> ComparisonSummary`
  - `refresh_metric_snapshots(environment: str) -> None`
- **Raises/Errors:** Expected missing data returns unavailable metrics.
- **Side Effects:** Optionally writes metric snapshots.

### 19.2 Internal Implementation Details

#### Metric Calculation

- **What it does:** Applies HLD formulas consistently.
- **Why this approach:** Makes model/venue comparison reproducible.
- **Complexity:** O(n) over selected orders/positions/scores.
- **Key steps:**
  1. Load filled/simulated-filled trades and open positions for window.
  2. Mark open positions using latest available venue data.
  3. Calculate realized, unrealized, net P&L, win rate, drawdown, model cost, exposure, trade count, return-to-risk.
  4. Return unavailable marker when denominator/data is insufficient.

### 19.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `ComparisonFilter` | Pydantic model | Environment/model/venue/window filters | Window required |
| `ComparisonSummary` | Pydantic model | Dashboard-ready metric groups | Missing metrics marked unavailable |
| `MetricWindow` | Enum | all-time, daily, trailing 7, trailing 30 | Supported value only |

### 19.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | No closed trades | Win rate unavailable, not zero | REQ-CMP-004 |
| 2 | Drawdown is zero | Return-to-risk unavailable | REQ-CMP-004 |
| 3 | Fees unavailable | Metric caveat set | REQ-CMP-003 |
| 4 | Alpaca mark stale | Unrealized P&L unavailable for affected symbol | REQ-CMP-004 |

### 19.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Missing data | Repositories | Return unavailable metric | Yes |
| DB unavailable | Database | Dashboard metric section degraded | Yes |
| Invalid filter | API | Return validation error | Yes |

### 19.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Accuracy | Metrics use documented formulas | Centralized calculation service |
| Performance | Dashboard reads bounded | Snapshot refresh and indexed queries |
| Transparency | Missing data not zeroed | Unavailable marker and caveats |

### 19.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Database layer | Orders/positions/scores | Metric inputs |
| Exports to | Dashboard API | Summary methods | Comparison data |
| Exports to | Notification service | Digest metrics | Daily summary |

### 19.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Sharpe-like metric is represented as return-to-risk in v1. | Later may add true Sharpe with regular return series. | DESIGN CHOICE |

### 19.9 Venue Portfolio Reconciliation

**File:** `backend/app/services/venue_portfolio_service.py`
**Responsibility:** Poll authenticated Polymarket US and Alpaca account APIs, normalize confirmed balances, positions, fills, and P&L, persist sanitized snapshots, and return a deduplicated dashboard read model.
**Requirements Covered:** REQ-DB-008, REQ-UI-013, REQ-CMP-005

`ProviderBackedVenuePortfolioSource.fetch_accounts(environment)` reads each venue and model-provider credential pair. Polymarket uses account identity, balances, decimal positions, fully paginated cleared-trade activity, and position resolutions. Alpaca uses account, open-position, `FILL` activity, and account portfolio-history endpoints. Alpaca realized P&L is the venue-reported total P&L less current venue-reported unrealized P&L; it is not reconstructed from a bounded local fill window. The source never returns or persists keys or secrets.

`VenuePortfolioService.refresh(environment)` runs independently from the trading tick every 60 seconds. Each account reconciliation uses one database transaction. Confirmed fills are serialized by deterministic fill ID and upserted by environment, venue, account reference, and venue trade ID before immutable account and position snapshots are committed. Failed refresh records do not replace the last confirmed values.

`VenuePortfolioService.summary(environment)` groups shared credentials by resolved venue account reference, maps credential-scoped refresh failures back to the last successful account, sums each account once, separates Polymarket US and Alpaca, exposes provider-account attribution, and returns unavailable values as null. History carries the last confirmed value for accounts that refresh in adjacent minute buckets. Freshness is based only on successful venue snapshots. Internal order intents, submitted orders, and simulations are not inputs to this read model. Realized and unrealized P&L use fixed-precision decimals; fees are included when supplied by the venue.

---

## 20. Worker Scheduler

**File:** `backend/app/workers/scheduler.py`  
**Responsibility:** Run ingestion, trading, exit, notification, comparison, and health loops with locks, heartbeats, and config snapshots.  
**Requirements Covered:** REQ-STR-001, REQ-STR-002, REQ-STR-003, REQ-STR-007, REQ-STR-008, REQ-DAT-001, REQ-DAT-002, REQ-DAT-008, REQ-LLM-001, REQ-LLM-004, REQ-LLM-005, REQ-EXE-003, REQ-EXE-013, REQ-EXE-014, REQ-EXE-017, REQ-EXT-001, REQ-EXT-006, REQ-NOT-001, REQ-NOT-007, REQ-CMP-001, REQ-CMP-004, REQ-OBS-006, REQ-UI-007  
**Dependencies:** Config service, database job repositories, retry repositories, ingestion service, scoring service, strategy engine, risk engine, execution service, exit monitor, notification service, comparison service, live-control repository  
**Depended On By:** Backend app lifecycle, dashboard health

### 20.1 Public Interface

#### `class WorkerScheduler`

- **Purpose:** Own background loop execution in the v1 backend process.
- **Traces:** REQ-STR-001, REQ-DAT-001, REQ-NOT-001
- **Methods:**
  - `start() -> None`
  - `stop() -> None`
  - `run_once(job_type: JobType, environment: str) -> JobRunResult`
  - `run_trading_loop(environment: str, run_id: str | None = None) -> TradingLoopResult`
  - `run_due_retries(environment: str, run_id: str | None = None) -> list[JobRunResult]`
  - `heartbeat(job_run_id: str) -> None`
- **Raises/Errors:** Job failures return `JobRunResult`; startup bugs raise.
- **Side Effects:** Runs background jobs and writes job status/heartbeat.

### 20.2 Internal Implementation Details

#### Job Run Flow

- **What it does:** Ensures one active run per job/environment/venue where required.
- **Why this approach:** Prevents overlapping trading and ingestion loops.
- **Complexity:** O(1) lock plus job-specific work.
- **Key steps:**
  1. Acquire Postgres advisory lock.
  2. Create `job_runs` row.
  3. Resolve the scheduler config owner and read one active database config snapshot.
  4. Run job with heartbeat.
  5. Mark success, failure, skipped, or abandoned.

#### Trading Loop Flow

- **What it does:** Runs the approved 60-second default trading sequence for all enabled venues and both model providers.
- **Why this approach:** The sequence is testable end to end and preserves deterministic filters before LLM spend.
- **Complexity:** O(v * m * c) where v is enabled venues, m is model providers, and c is filtered candidates.
- **Key steps:**
  1. Acquire the `trading` job lock and create a `job_runs` row.
  2. Resolve the scheduler config owner and read one active database config snapshot; normal dashboard changes apply on the next loop.
  3. Read current `KillSwitchState`; if active, skip new live decisions and call execution kill-switch cancellation.
  4. For each enabled venue, load the latest snapshots and run deterministic filters before any LLM call.
  5. Pass eligible candidates to the scoring service for Claude and OpenAI with provider-specific budgets and loop deadline.
  6. Persist scoring outcomes, including `DEFERRED`, `DEFERRED_RATE_LIMITED`, and `DEFERRED_BUDGET_EXHAUSTED`.
  7. Generate and persist strategy signals.
  8. Apply consensus and persist trade decisions.
  9. Between decision batches, read current `KillSwitchState`; if active, stop new live submissions and trigger cancel flow.
  10. Evaluate risk for each decision, then submit to execution for dry-run simulation or live venue submission.
  11. Aggregate candidates, scoring outcomes, signals, decisions, risk refusals, execution results, deferrals, errors, and elapsed time in `TradingLoopResult`.

#### Job-Specific Contracts

| Job | Trigger | Required Calls | Result Fields | REQ Trace |
|-----|---------|----------------|---------------|-----------|
| `full_ingestion` | Daily 06:00 UTC | `run_full_snapshot()` per enabled venue | object keys, checkpoint, retry state | REQ-DAT-001, REQ-DAT-008 |
| `incremental_ingestion` | Configured interval | `run_incremental_snapshot()` per enabled venue | object keys, checkpoint, retry state | REQ-DAT-002, REQ-DAT-008 |
| `trading` | Default every 60 seconds | filters, scoring, strategy, risk, execution | candidates, decisions, refusals, executions, deferrals | REQ-STR-001, REQ-STR-003, REQ-EXE-013 |
| `exit` | Configured interval | `evaluate_positions()` and `execute_exit()` | exit decisions and execution results | REQ-EXT-001, REQ-EXT-006 |
| `notification` | Digest schedule and alert checks | digest, alert evaluation, SES send | sent, skipped, failed, retry state | REQ-NOT-001, REQ-NOT-007 |
| `comparison` | Configured interval and dashboard refresh | metric refresh | refreshed windows and unavailable metrics | REQ-CMP-001, REQ-CMP-004 |
| `due_retries` | Configured retry poll interval | ingestion retry and notification retry dispatch | attempted, success, exhausted | REQ-DAT-008, REQ-NOT-007 |

### 20.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `JobRunResult` | Pydantic model | Job status | Has started/finished/error status |
| `TradingLoopResult` | Pydantic model | Trading-loop aggregate | Carries config version, run ID, counts, refusal reasons, execution IDs |
| `JobType` | Enum | full ingestion, incremental ingestion, trading, exit, notification, comparison, due retries | Supported value only |
| `RetryState` | DB/domain model | Due retry attempts for ingestion and SES | Has next attempt and exhausted status |

### 20.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Prior heartbeat current | Skip overlapping run | REQ-OBS-006 |
| 2 | Prior heartbeat stale | Mark abandoned and take lock | REQ-OBS-006 |
| 3 | Config changes mid-loop | Current loop keeps original snapshot, except kill-switch control-plane reads bypass the snapshot | REQ-UI-007, REQ-EXE-014 |
| 4 | Trading loop exceeds interval | Record overrun and defer remaining candidates | REQ-STR-001 |
| 5 | LLM budget or deadline prevents scoring | Record deferred outcome and continue other provider/candidates | REQ-LLM-004, REQ-LLM-005 |
| 6 | Retry row is due | Dispatch retry if attempts remain; mark exhausted otherwise | REQ-DAT-008, REQ-NOT-007 |
| 7 | Multi-user app has saved user config and no explicit scheduler owner | Scheduler selects the latest active allowlisted user-owned config row from the database before shared fallback | REQ-UI-007 |

### 20.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Job raises unexpected error | Service bug | Mark failed and dashboard degraded | Yes |
| DB lock unavailable | Database | Skip or fail safe depending on job type | Yes |
| Live-control read fails in trading loop | Database | Stop live submissions and mark loop degraded | Yes |
| Retry dispatch fails | Retry repository/service | Persist attempt failure and next retry state | Yes |
| Shutdown requested | App lifecycle | Stop after current safe boundary | Yes |

### 20.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Concurrency | No overlapping unsafe jobs | Advisory locks and job rows |
| Observability | Worker health visible | Heartbeats and run status |
| Safety | Kill switch is immediate | Trading loop checks live-control state between batches and execution checks again before submit |
| Reliability | Retries survive restarts | Due retry job reads persisted retry state |
| Maintainability | Future ECS worker split | Job boundaries map to future services |

### 20.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Config service | Config snapshots | Runtime settings |
| Imports | Core services | Job-specific methods | Job results |
| Imports | Database layer | Job, retry, and live-control repositories | Locks, retries, kill-switch state |
| Exports to | Dashboard API | Job status repository | Health indicators |

### 20.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | One backend ECS task is enough for v1 worker load. | HLD split path moves jobs to separate ECS services. | APPROVED HLD |

---

## 21. Backend App and API Routers

**File:** `backend/app/main.py`, `backend/app/api/`  
**Responsibility:** Bootstrap FastAPI, wire dependencies, expose authenticated dashboard APIs, and keep read/write paths separated from worker loops.  
**Requirements Covered:** REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010, REQ-UI-011, REQ-UI-013, REQ-CMP-005, REQ-DB-008, REQ-VEN-002, REQ-VEN-003, REQ-VEN-006, REQ-WAL-002, REQ-WAL-005, REQ-STR-002, REQ-STR-009, REQ-LLM-006, REQ-EXE-003, REQ-EXE-007, REQ-EXE-011, REQ-EXE-012, REQ-EXE-014, REQ-EXE-016, REQ-ALP-007, REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012, REQ-ALP-013, REQ-ALP-014, REQ-NOT-001, REQ-NOT-003, REQ-NOT-004, REQ-NOT-005, REQ-NOT-006, REQ-OBS-004, REQ-OBS-005, REQ-OBS-006
**Dependencies:** Auth service, config service, audit service, wallet service, comparison service, worker repositories, order/position repositories, notification service, execution service  
**Depended On By:** Next.js dashboard, local development, CI smoke tests

### 21.1 Public Interface

#### `create_app(settings: AppSettings) -> FastAPI`

- **Purpose:** Create the backend app with routers, middleware, lifecycle hooks, and worker startup.
- **Traces:** REQ-UI-001, REQ-OBS-006
- **Side Effects:** Starts worker scheduler when enabled, configures logging, creates dependency container.

#### API routers

| Router | Representative Endpoints | Purpose | REQ Trace |
|--------|--------------------------|---------|-----------|
| `health.py` | `GET /health`, `GET /api/health` | Liveness/readiness and degraded component status | REQ-OBS-005, REQ-OBS-006 |
| `dashboard.py` | `GET /api/dashboard/summary` | Combined overview for venues, models, loops, notifications | REQ-UI-004 |
| `dashboard.py` | `GET /api/portfolio` | Venue-confirmed account value, P&L, holdings, fills, and freshness | REQ-UI-013, REQ-CMP-005 |
| `config.py` | `GET /api/config/current`, `PUT /api/config` | Versioned config read/update | REQ-UI-005, REQ-UI-006, REQ-UI-007 |
| `dashboard.py` | `GET /api/preferences`, `PUT /api/preferences` | Per-user dashboard display preferences | REQ-UI-004, REQ-OBS-004 |
| `live_control.py` | `POST /api/live-mode`, `POST /api/kill-switch` | Dry-run/live toggle and immediate kill switch | REQ-EXE-003, REQ-EXE-014, REQ-UI-008 |
| `models.py` | `GET /api/models/{provider}/summary` | Claude/OpenAI positions, decisions, budgets, P&L | REQ-UI-010 |
| `orders.py` | `GET /api/orders`, `GET /api/orders/{id}` | Order events, refusals, fills, cancels, failures | REQ-EXE-016 |
| `wallets.py` | `GET /api/wallets/status`, `POST /api/wallets/polymarket` | Safe credential status and Polymarket wallet generation | REQ-WAL-005 |
| `comparison.py` | `GET /api/comparison` | Cross-model and cross-venue metrics | REQ-UI-011 |
| `notifications.py` | `GET /api/notifications/settings`, `PUT /api/notifications/settings` | Digest and alert settings | REQ-NOT-006 |
| `audit.py` | `GET /api/audit-events` | Recent audit events | REQ-OBS-005 |

#### Endpoint contracts

All `/api/*` endpoints require a valid FastAPI authorization dependency. Mutation endpoints also require CSRF validation through the Next.js server-side proxy, trusted origin validation, and an audit event.

| Method | Endpoint | Request Schema | Response Schema | Status Codes | REQ Trace |
|--------|----------|----------------|-----------------|--------------|-----------|
| `GET` | `/api/dashboard/summary` | `DashboardSummaryQuery` | `DashboardSummaryResponse` | 200 with `degraded_sections`, 401, 403, 503 | REQ-UI-004 |
| `GET` | `/api/portfolio` | Authenticated environment context | `VenuePortfolioResponse` | 200 with unavailable or stale account states, 401, 403, 503 | REQ-UI-013, REQ-CMP-005 |
| `GET` | `/api/preferences` | `DashboardPreferencesQuery` | `DashboardPreferencesResponse` | 200, 401, 403, 503 | REQ-UI-004 |
| `PUT` | `/api/preferences` | `DashboardPreferencesRequest` | `DashboardPreferencesResponse` | 200, 401, 403, 422, 503 | REQ-UI-004, REQ-OBS-004 |
| `GET` | `/api/config/current` | `ConfigReadQuery` | `ConfigSnapshotResponse` | 200, 401, 403, 503 | REQ-UI-005 |
| `PUT` | `/api/config` | `ConfigUpdateRequest` | `ConfigUpdateResponse` | 200, 401, 403, 409, 422, 503 | REQ-UI-005, REQ-UI-006, REQ-UI-007 |
| `POST` | `/api/live-mode` | `LiveModeRequest` | `LiveModeResponse` | 200, 401, 403, 409, 422, 503 | REQ-EXE-003, REQ-UI-006 |
| `POST` | `/api/kill-switch` | `KillSwitchRequest` | `KillSwitchResponse` | 202, 401, 403, 422, 503 | REQ-EXE-014, REQ-UI-008 |
| `POST` | `/api/kill-switch/acknowledge` | `KillSwitchAcknowledgeRequest` | `KillSwitchResponse` | 200, 401, 403, 409, 422, 503 | REQ-EXE-015, REQ-OBS-004 |
| `GET` | `/api/models/{provider}/summary` | `ModelSummaryQuery` | `ModelProviderSummaryResponse` | 200 with `degraded_sections`, 401, 403, 404, 503 | REQ-UI-010 |
| `GET` | `/api/orders` | `OrderEventQuery` | `PaginatedResponse[OrderEventResponse]` | 200, 401, 403, 422, 503 | REQ-EXE-016 |
| `GET` | `/api/wallets/status` | `WalletStatusQuery` | `WalletStatusResponse` | 200, 401, 403, 422, 503 | REQ-WAL-005 |
| `POST` | `/api/wallets/polymarket` | `WalletGenerationRequest` | `WalletGenerationResponse` | 201, 401, 403, 409, 422, 503 | REQ-WAL-002, REQ-WAL-005 |
| `GET` | `/api/comparison` | `ComparisonQuery` | `ComparisonSummaryResponse` | 200 with `degraded_sections`, 401, 403, 422, 503 | REQ-UI-011 |
| `PUT` | `/api/notifications/settings` | `NotificationSettingsRequest` | `NotificationSettingsResponse` | 200, 401, 403, 409, 422, 503 | REQ-NOT-006 |
| `GET` | `/api/audit-events` | `AuditEventQuery` | `PaginatedResponse[AuditEventResponse]` | 200, 401, 403, 422, 503 | REQ-OBS-005 |

#### Allowed config patch paths

`ConfigUpdateRequest` accepts only allowlisted patch paths. Unknown paths return 422 and do not write audit events.

| Config Path | Validation | REQ Trace |
|-------------|------------|-----------|
| `default_selected_venue` | Supported venue enum; default remains Polymarket US if absent | REQ-VEN-002 |
| `venues.{venue}.enabled` | Boolean; venue must be supported | REQ-VEN-003, REQ-VEN-006 |
| `trading_loop_interval_seconds` | Integer at or above safe minimum | REQ-STR-002 |
| `strategies.{strategy}.enabled` | Boolean; known strategy only | REQ-STR-009 |
| `strategies.{strategy}.settings.*` | Strategy-specific schema | REQ-STR-009 |
| `llm.{provider}.budget_usd` | Positive decimal | REQ-LLM-006 |
| `llm.{provider}.settings.*` | Provider-specific schema | REQ-LLM-006 |
| `risk.polymarket.max_position_usd` | Positive decimal | REQ-EXE-007 |
| `risk.polymarket.max_daily_loss_usd` | Positive decimal | REQ-EXE-007 |
| `risk.polymarket.max_open_positions` | Positive integer | REQ-EXE-007 |
| `risk.polymarket.market_order_slippage_threshold` | Decimal 0 to 1 | REQ-EXE-011, REQ-EXE-012 |
| `risk.alpaca.max_position_usd` | Positive decimal | REQ-ALP-009, REQ-ALP-014 |
| `risk.alpaca.max_daily_loss_usd` | Positive decimal | REQ-ALP-010, REQ-ALP-014 |
| `risk.alpaca.max_open_positions` | Positive integer | REQ-ALP-011, REQ-ALP-014 |
| `risk.alpaca.max_portfolio_allocation_per_symbol` | Decimal 0 to 1 | REQ-ALP-012, REQ-ALP-014 |
| `risk.alpaca.market_order_slippage_threshold` | Decimal 0 to 1 | REQ-ALP-013, REQ-ALP-014 |
| `alpaca.account_mode` | `paper` or `live` | REQ-ALP-007, REQ-ALP-014 |
| `alpaca.symbol_universe` | Non-empty stock/ETF symbols only | REQ-ALP-001, REQ-ALP-014 |
| `notifications.recipients` | GitHub usernames mapped to email addresses | REQ-NOT-001, REQ-NOT-006 |
| `notifications.thresholds.*` | Positive movement/drawdown values | REQ-NOT-003, REQ-NOT-004, REQ-NOT-006 |
| `notifications.cooldown_seconds` | Positive integer | REQ-NOT-005, REQ-NOT-006 |
| `notifications.digest_schedule_utc` | Valid daily UTC time | REQ-NOT-001, REQ-NOT-006 |

#### API schema field contracts

Expected component-level degradation returns HTTP 200 with `degraded_sections` when the request itself is valid and at least one section can be served. HTTP 503 is used when the endpoint cannot produce a safe response, such as database unavailability for a required read or write. All error responses use `ErrorEnvelope`.

| Schema | Required Fields | Optional Fields | Notes |
|--------|-----------------|-----------------|-------|
| `ErrorEnvelope` | `error_code`, `message`, `correlation_id` | `field_errors`, `retry_after_seconds`, `current_version` | Used for 4xx/5xx expected errors |
| `DegradedSection` | `section`, `status`, `error_code`, `message`, `last_success_at` | `retry_after_seconds` | `status` is `degraded`, `down`, or `unknown` |
| `DashboardSummaryQuery` | `environment` | `window`, `include_sections` | `window` defaults to current trading day |
| `DashboardSummaryResponse` | `environment`, `generated_at`, `health`, `kill_switch`, `venues`, `models`, `notifications`, `preferences`, `degraded_sections` | `comparison_snapshot` | Secret fields forbidden; preferences are loaded by authenticated username and environment |
| `DashboardPreferencesRequest` | `settings` | none | Settings include theme, IANA time zone, and AWS monthly infrastructure cost fallback |
| `DashboardPreferencesResponse` | `environment`, `username`, `settings`, `updatedAt` | `auditEventId` | Row is scoped to authenticated username and environment |
| `ConfigReadQuery` | `environment` | none | Environment must be local/dev/prod |
| `ConfigSnapshotResponse` | `environment`, `version`, `effective_at`, `settings`, `updated_by`, `updated_at`, `username`, `config_owner` | `validation_warnings` | Settings contain only allowlisted config paths |
| `ConfigPatchOperation` | `op`, `path`, `value` | none | `op` is `replace`, `add`, or `remove`; `path` must be allowlisted |
| `ConfigUpdateRequest` | `environment`, `expected_version`, `patches`, `reason` | none | Empty patch list rejected |
| `ConfigUpdateResponse` | `environment`, `previous_version`, `new_version`, `audit_event_id`, `applies_on_next_loop` | `warnings` | `applies_on_next_loop` is true except kill switch |
| `LiveModeRequest` | `environment`, `target_live_enabled`, `expected_version`, `reason` | none | Mutation audited; live target still subject to venue/risk checks |
| `LiveModeResponse` | `environment`, `live_enabled`, `config_version`, `audit_event_id`, `applies_on_next_loop` | `warnings` | Returns 409 on stale expected version |
| `KillSwitchRequest` | `environment`, `reason` | `cancel_timeout_seconds` | Always audited |
| `KillSwitchAcknowledgeRequest` | `environment`, `order_ids`, `reason` | none | Requires manual-review-capable user |
| `KillSwitchResponse` | `active`, `activated_at`, `activated_by`, `reason`, `live_disabled`, `cancel_summary`, `open_order_states`, `degraded_venues`, `manual_review_required`, `last_updated_at` | `acknowledged_order_ids` | Returned with 202 while cancel work remains |
| `ModelSummaryQuery` | `environment`, `provider` | `venue`, `window` | Provider is `claude` or `openai` |
| `ModelProviderSummaryResponse` | `environment`, `provider`, `budget`, `positions`, `decisions`, `orders`, `pnl`, `refusals`, `degraded_sections` | none | Sections grouped by Polymarket and Alpaca |
| `OrderEventQuery` | `environment` | `provider`, `venue`, `state`, `cursor`, `limit` | `limit` capped at 100 |
| `OrderEventResponse` | `order_id`, `event_id`, `environment`, `venue`, `provider`, `state`, `reason_code`, `created_at`, `correlation_id` | `venue_order_id`, `filled_size`, `price`, `error_summary` | Append-only order event view |
| `WalletStatusQuery` | `environment` | `venue`, `provider` | No private key request field exists |
| `WalletStatusResponse` | `environment`, `credentials`, `generated_at` | `degraded_sections` | Each credential has public ID, health, and secret ref only |
| `WalletGenerationRequest` | `environment`, `venue`, `provider`, `reason` | none | Polymarket only; Alpaca account generation refused |
| `WalletGenerationResponse` | `environment`, `venue`, `provider`, `public_identifier`, `secret_ref`, `audit_event_id` | `next_steps` | Private key never returned |
| `ComparisonQuery` | `environment`, `window` | `provider`, `venue`, `instrument_type` | Supported windows: all-time, daily, trailing 7, trailing 30 |
| `ComparisonSummaryResponse` | `environment`, `window`, `metrics`, `generated_at`, `degraded_sections` | `caveats` | Unavailable metrics are explicit |
| `NotificationSettingsRequest` | `environment`, `expected_version`, `settings`, `reason` | none | Recipients must map allowlisted usernames to emails |
| `NotificationSettingsResponse` | `environment`, `config_version`, `audit_event_id`, `settings` | `warnings` | Applies on next notification loop |
| `AuditEventQuery` | `environment` | `actor`, `event_type`, `cursor`, `limit` | `limit` capped at 100 |
| `AuditEventResponse` | `event_id`, `environment`, `event_type`, `actor`, `created_at`, `ip_address`, `correlation_id`, `summary` | `old_value_redacted`, `new_value_redacted` | Secret values redacted |
| `PaginatedResponse[T]` | `items`, `next_cursor`, `limit` | none | Stable cursor ordering |

### 21.2 Internal Implementation Details

#### Authenticated Write Flow

- **What it does:** Applies authorized mutations with audit and config versioning.
- **Why this approach:** Dashboard changes must be attributable and apply on the next loop.
- **Complexity:** O(1) per mutation plus validation.
- **Key steps:**
  1. Validate signed session token through `AuthService`.
  2. Validate username allowlist and CSRF/origin headers.
  3. Validate request with Pydantic schema.
  4. Use config service, preference service, or live-control service to perform the mutation.
  5. Persist audit event with actor, old value, new value, IP address, environment, and correlation ID.
  6. Return the new config version or live-control state.

#### Dashboard Read Flow

- **What it does:** Aggregates bounded status views without blocking worker loops.
- **Why this approach:** API response times should stay predictable while workers run in process.
- **Complexity:** O(page size) with indexed repository reads.
- **Key steps:** Resolve auth, read user-scoped config and preferences by actor/environment, read repositories, map to response schemas, include degraded/unavailable markers instead of failing whole summary when one section is unavailable.

### 21.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `DashboardSummaryResponse` | API schema | Overview status, model summaries, health, kill switch | Never contains secrets |
| `DashboardPreferencesResponse` | API schema | User display settings and cost fallback | Scoped to authenticated username and environment |
| `ConfigUpdateRequest` | API schema | Expected version and patch operations | Requires expected active version |
| `LiveModeRequest` | API schema | Global dry-run/live target state | Actor must be authorized |
| `KillSwitchRequest` | API schema | Environment and reason | Reason required |
| `KillSwitchResponse` | API schema | Active state plus cancel progress | Shows unresolved and manual-review orders |
| `ModelProviderSummaryResponse` | API schema | Provider-specific status | Provider is `claude` or `openai` |
| `PaginatedQuery` | API schema | Pagination and filters | Limit has max bound |

`KillSwitchResponse` fields are `active`, `activated_at`, `activated_by`, `reason`, `live_disabled`, `cancel_summary`, `open_order_states`, `degraded_venues`, `manual_review_required`, and `last_updated_at`. `cancel_summary` includes total open orders, attempted cancels, terminal cancels, failed cancels, no-longer-open orders, manual-review orders, and per-venue counts. `open_order_states` includes local order ID, venue order ID, venue, model provider, cancel state, next retry time, and last error summary.

### 21.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Config update has stale expected version | Reject with conflict and current version | REQ-UI-007 |
| 2 | Audit write fails for config/live/kill mutation | Reject mutation before returning success | REQ-UI-006, REQ-OBS-004 |
| 3 | Dashboard asks for private key or secret value | Schema has no field and router refuses secret access | REQ-WAL-005 |
| 4 | Kill switch request arrives while workers are mid-loop | Persist live disabled and kill switch active before response | REQ-EXE-014 |
| 5 | One dashboard summary section fails | Return degraded section with error code, not a blank dashboard | REQ-OBS-006 |
| 6 | Unauthenticated or unallowlisted user calls API | Return 401 or 403 before service call | REQ-UI-002, REQ-UI-003 |
| 7 | Kill switch cancel attempts are still pending | Return 202 with cancel progress and unresolved orders | REQ-EXE-015, REQ-UI-008 |
| 8 | Two authenticated users save different dashboard preferences | Each preferences, summary, and economics response uses the actor's own database row | REQ-UI-004 |

### 21.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Auth token invalid | Auth service | 401 and no mutation | Yes |
| Username denied | Auth service/config | 403 and no mutation | Yes |
| Validation failure | Pydantic/config service | 422 or 409 with field errors | Yes |
| Repository unavailable | Database | Return degraded read or block mutation | Yes |

### 21.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Security | API cannot trust frontend headers | Signed token validation and allowlist dependency |
| Auditability | Sensitive writes are attributable | Shared mutation wrapper requires audit event |
| Performance | Dashboard reads are bounded | Pagination, indexed repository queries, degraded sections |
| Maintainability | Future worker split | API calls services through interfaces, not worker internals |

### 21.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Auth service | `require_user()` | Actor context |
| Imports | Core services | Config, wallet, comparison, notification, execution | Status and mutations |
| Imports | Database layer | Repositories | Read models and audit data |
| Exports to | Frontend API client | JSON REST endpoints | Dashboard data |

### 21.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | REST endpoints are enough for v1 dashboard status, without websockets. | Dashboard refresh is polling-based. | DESIGN CHOICE |

---

## 22. Frontend App, Auth UI, and Dashboard

**File:** `frontend/`  
**Responsibility:** Provide the Next.js React dashboard, GitHub OAuth flow, configuration editor, model comparison views, and operational controls.  
**Requirements Covered:** REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010, REQ-UI-011, REQ-UI-012, REQ-UI-013, REQ-CMP-005, REQ-ALP-014, REQ-NOT-006, REQ-OBS-005
**Dependencies:** Backend API routers, GitHub OAuth app, signed session secret, browser fetch API  
**Depended On By:** Operators, local testing, Playwright tests

### 22.1 Public Interface

#### Routes

| Route | Purpose | REQ Trace |
|-------|---------|-----------|
| `/login` | GitHub OAuth sign-in entry | REQ-UI-002 |
| `/dashboard` | Combined overview with actual venue portfolio and targeted scanner blocker recommendations | REQ-UI-004, REQ-UI-012, REQ-UI-013, REQ-CMP-005 |
| `/dashboard/models/claude` | Claude-specific positions, decisions, budget, P&L | REQ-UI-010 |
| `/dashboard/models/openai` | OpenAI-specific positions, decisions, budget, P&L | REQ-UI-010 |
| `/dashboard/comparison` | Claude vs OpenAI across Polymarket and Alpaca | REQ-UI-011 |
| `/dashboard/config` | Runtime config editor | REQ-UI-005, REQ-ALP-014, REQ-NOT-006 |
| `/dashboard/audit` | Audit events and health indicators | REQ-OBS-005 |
| `/dashboard/system` | Worker, ingestion, wallet, venue, notification, kill-switch state | REQ-UI-004, REQ-UI-008 |

#### Frontend modules

- `frontend/lib/api.ts`: Browser-safe typed API client that calls same-origin Next.js backend-for-frontend routes.
- `frontend/lib/server/backend-token.ts`: Server-only backend token creation. This module imports `server-only` and never ships to the browser bundle.
- `frontend/app/dashboard-api/[...path]/route.ts`: Next.js route handler that validates the web session, mints a short-lived FastAPI bearer token server-side, forwards requests to FastAPI, and strips hop-by-hop headers.
- `frontend/lib/session.ts`: Browser-safe session helpers. It does not contain signing secrets or backend token minting logic.
- `frontend/components/dashboard/`: Overview, model, order, position, config, comparison, audit, wallet, and notification components.

### 22.2 Internal Implementation Details

#### OAuth and Session Flow

- **What it does:** Authenticates via GitHub and sends signed session proof to FastAPI.
- **Why this approach:** Next.js owns OAuth UX while FastAPI still validates authorization.
- **Complexity:** O(1) per request.
- **Key steps:**
  1. User signs in through GitHub OAuth.
  2. Next.js stores secure session cookie.
  3. Browser code calls same-origin `/dashboard-api/*` route handlers.
  4. Server-only Next.js route handler verifies the web session and mints a short-lived FastAPI bearer token.
  5. Route handler forwards the request to FastAPI with the bearer token and CSRF/origin context.
  6. FastAPI validates signature, expiration, audience, issuer, and allowlist.

The backend token signing secret is only available to Next.js server runtime and FastAPI. It is never exposed through `NEXT_PUBLIC_*`, client components, serialized props, logs, or browser storage.

#### Config Editing Flow

- **What it does:** Lets authorized users edit runtime config without process restart.
- **Why this approach:** User requested dashboard-controlled risk, venue, model, strategy, Alpaca, and notification settings.
- **Complexity:** O(number of edited fields).
- **Key steps:** Load current config/version, render validated controls, submit patch with expected version, show audit result, refresh dashboard state.

### 22.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `ApiClientResult<T>` | TypeScript type | Data or typed API error | Never throws for expected API errors |
| `BackendTokenClaims` | Server-only TypeScript type | Subject username, audience, issuer, expiration, nonce, scopes | Minted only in route handler |
| `DashboardViewModel` | TypeScript type | Aggregated UI state | Secrets absent |
| `ConfigFormState` | TypeScript type | Editable config sections | Carries config version |
| `MetricDisplayValue` | TypeScript type | Metric value, unavailable marker, caveat | Missing data is not rendered as zero |

### 22.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | GitHub user authenticates but is not allowlisted | Show access denied; do not call mutation endpoints | REQ-UI-003 |
| 2 | Config save conflict | Show current server version and require reload before resubmit | REQ-UI-007 |
| 3 | Kill switch API call fails | Keep visible degraded state and do not claim kill switch is active | REQ-UI-008 |
| 4 | Metric unavailable | Render unavailable with caveat, not zero | REQ-UI-011, REQ-CMP-004 |
| 5 | Wallet status includes only public ID | Render public identifier and health, never secret | REQ-UI-009 |
| 6 | Backend section degraded | Render degraded section with timestamp and retry affordance | REQ-OBS-005 |
| 7 | Backend token creation module imported by client component | Build/test fails because module is marked server-only | REQ-UI-002 |
| 8 | Scanner rejections point to configurable blockers | Show targeted config changes and save them through the audited per-user config flow | REQ-UI-012, REQ-UI-005, REQ-UI-006, REQ-UI-007 |
| 9 | A venue refresh fails or has never succeeded | Keep the last confirmed values with stale status, or show unavailable rather than zero | REQ-UI-013, REQ-CMP-005 |

### 22.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| OAuth callback failure | GitHub/auth | Show login error | Yes |
| Backend 401/403 | API client | Redirect to login or access denied | Yes |
| Backend 409 | Config API | Show conflict and reload control | Yes |
| Network timeout | API client | Show stale/degraded status | Yes |
| BFF proxy receives mutation without CSRF context | Route handler rejects before FastAPI call | Yes |

### 22.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Usability | Operational dashboard should be scan-friendly | Dense tables, tabs by model/provider, clear status states |
| Security | Session cookies are protected | HttpOnly, Secure, SameSite cookie settings |
| Security | Backend token secret is server-only | Browser calls Next.js BFF route; server-only module mints FastAPI token |
| Reliability | UI handles degraded sections | Typed API errors and unavailable states |
| Testability | Critical flows covered | Playwright tests for auth gates, config save, kill switch, comparison view |

### 22.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Backend API | REST endpoints | Dashboard state and mutations |
| Imports | GitHub OAuth | OAuth callback | User identity |
| Exports to | User | Browser UI | Operational controls |

### 22.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Polling every 10 seconds is enough for cycle status; venue portfolio refreshes every 60 seconds. | Later may add websocket/SSE for faster updates. | DESIGN CHOICE |

---

## 23. Observability and Health

**File:** `backend/app/observability.py`, `backend/app/services/health_service.py`, `infra/cloudformation/observability.yaml`  
**Responsibility:** Provide structured logs, correlation IDs, component health, CloudWatch log wiring, and dashboard-visible degraded states.  
**Requirements Covered:** REQ-OBS-001, REQ-OBS-002, REQ-OBS-003, REQ-OBS-004, REQ-OBS-005, REQ-OBS-006, REQ-DB-007, REQ-DEP-002, REQ-WAL-003  
**Dependencies:** Audit service, worker repositories, config service, database repositories, CloudWatch log groups  
**Depended On By:** Backend app, dashboard API, CloudFormation, runbooks

### 23.1 Public Interface

#### `configure_logging(settings: AppSettings) -> None`

- **Purpose:** Configure JSON logs for local and AWS environments.
- **Traces:** REQ-OBS-001, REQ-OBS-002
- **Side Effects:** Sets logging format and redaction filters.

#### `class HealthService`

- **Purpose:** Build API and dashboard health summaries.
- **Traces:** REQ-OBS-005, REQ-OBS-006
- **Methods:**
  - `get_component_health(environment: str) -> ComponentHealthSummary`
  - `record_worker_failure(job_run_id: str, error: ErrorSummary) -> None`
  - `build_dashboard_health(environment: str) -> DashboardHealthResponse`

### 23.2 Internal Implementation Details

#### Correlation Flow

- **What it does:** Carries a correlation ID through API calls, workers, LLM requests, venue calls, audit events, and order events.
- **Why this approach:** Live-trading debugging needs one traceable path per decision.
- **Complexity:** O(1).
- **Key steps:** Read incoming header or generate ID, store in request context, pass to service calls, include in audit/order/job rows and JSON logs.

#### Health Aggregation

- **What it does:** Converts component failures into dashboard state.
- **Why this approach:** Operators need degraded status without reading logs first.
- **Complexity:** O(number of components).
- **Key steps:** Read latest job runs, ingestion staleness, DB connectivity, notification delivery, credential health, venue health, and live-control state.

#### Log Events and Metric Filters

- **What it does:** Emits stable JSON event names that CloudWatch metric filters and alarms can use.
- **Why this approach:** The HLD metric contract should be testable and visible without a separate metrics system.
- **Complexity:** O(1) per emitted event.

| Event Name | Required Fields | CloudWatch Metric / Alarm | REQ Trace |
|------------|-----------------|---------------------------|-----------|
| `worker.heartbeat` | environment, job_type, job_run_id, heartbeat_age_seconds | `WorkerHeartbeatAge`, alarm on stale heartbeat | REQ-OBS-006 |
| `worker.failed` | environment, job_type, job_run_id, error_code | `WorkerFailureCount`, alarm on failures | REQ-OBS-006 |
| `trading.loop_completed` | environment, job_run_id, duration_ms, candidate_count, decision_count, execution_count, status | `TradingLoopDuration`, alarm when duration exceeds configured interval | REQ-OBS-001 |
| `trading.loop_skipped` | environment, job_run_id, skipped_reason, prior_job_run_id | `TradingLoopSkippedCount`, dashboard skipped-loop count | REQ-OBS-006 |
| `ingestion.completed` | environment, venue, snapshot_type, object_count, checkpoint, checkpoint_age_seconds | `IngestionSuccessCount`, dashboard freshness | REQ-OBS-001 |
| `ingestion.failed` | environment, venue, snapshot_type, error_code, next_attempt_at | `IngestionFailureCount`, alarm on repeated failures | REQ-OBS-006 |
| `ingestion.checkpoint_age` | environment, venue, snapshot_type, checkpoint_age_seconds | `IngestionCheckpointAge`, alarm when age exceeds threshold | REQ-OBS-001 |
| `market_data.stale` | environment, venue, instrument_id, age_seconds, threshold_seconds | `MarketDataStaleCount`, alarm on stale live dependency | REQ-OBS-001 |
| `venue.api_error` | environment, venue, operation, error_code, retryable | `VenueApiErrorCount`, alarm on error rate | REQ-OBS-001 |
| `venue.api_timeout` | environment, venue, operation, timeout_seconds | `VenueTimeoutCount`, alarm on timeout rate | REQ-OBS-001 |
| `llm.scoring_failed` | environment, model_provider, prompt_version, error_code | `LlmProviderErrorCount`, alarm on provider failures | REQ-OBS-001 |
| `llm.timeout` | environment, model_provider, prompt_version, timeout_ms | `LlmTimeoutCount`, alarm on timeout rate | REQ-OBS-001 |
| `llm.rate_limited` | environment, model_provider, retry_after_seconds | `LlmRateLimitCount`, dashboard degraded state | REQ-OBS-001 |
| `llm.budget_status` | environment, model_provider, budget_remaining_usd, budget_spent_usd, budget_window | `LlmBudgetRemaining`, alarm when near zero | REQ-OBS-001 |
| `order.lifecycle` | environment, venue, model_provider, local_order_id, order_state | `OrderSubmittedCount`, `OrderFillCount`, `OrderCancelCount`, `OrderUnknownCount`, `OrderFailureCount` | REQ-OBS-003 |
| `order.refused` | environment, venue, model_provider, reason_code | `OrderRefusalCount`, dashboard refusal breakdown | REQ-OBS-003 |
| `notification.delivery` | environment, notification_type, status, retry_count | `SesDeliverySuccessCount`, `SesDeliveryFailureCount`, alarm on repeated failures | REQ-OBS-001 |
| `alpaca.market_data_age` | environment, symbol, age_seconds, threshold_seconds | `AlpacaMarketDataAge`, alarm on stale symbol data | REQ-OBS-001 |
| `alpaca.rate_limited` | environment, operation, symbol, retry_after_seconds | `AlpacaRateLimitCount`, dashboard degraded state | REQ-OBS-001 |
| `alpaca.api_timeout` | environment, operation, symbol, timeout_seconds | `AlpacaTimeoutCount`, alarm on timeout rate | REQ-OBS-001 |
| `alpaca.buying_power_age` | environment, model_provider, account_mode, buying_power_age_seconds | `AlpacaBuyingPowerAge`, alarm when stale | REQ-OBS-001 |
| `alpaca.reconciliation_mismatch` | environment, model_provider, account_mode, mismatch_type | `AlpacaMismatchCount`, alarm on unresolved mismatch | REQ-OBS-001 |
| `alpaca.order_rejected` | environment, model_provider, account_mode, symbol, rejection_reason | `AlpacaRejectedOrderCount`, dashboard rejected-order reasons | REQ-OBS-003 |
| `comparison.refreshed` | environment, model_provider, venue, window, metric_count, unavailable_count, freshness_age_seconds | `ComparisonFreshnessAge`, dashboard freshness | REQ-OBS-005 |
| `kill_switch.activated` | environment, actor, open_order_count | `KillSwitchActivatedCount`, high-priority alert | REQ-OBS-004 |

### 23.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `LogEvent` | JSON log shape | Timestamp, level, event, environment, correlation ID | Secrets redacted |
| `ComponentHealth` | Domain/API model | Component state and message | State is ok/degraded/down/unknown |
| `DashboardHealthResponse` | API schema | Health groups for UI | Includes last updated timestamp |
| `CloudWatchMetricFilter` | Infrastructure model | Event name to metric mapping | Namespace includes environment |
| `AlarmDefinition` | Infrastructure model | Metric, threshold, period, severity | Alarm action environment-scoped |

### 23.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Incoming request has no correlation ID | Generate one and include in response/logs | REQ-OBS-001 |
| 2 | Postgres health check fails | Mark DB down and block live order status | REQ-DB-007 |
| 3 | Worker failure is recorded | Dashboard shows degraded job state | REQ-OBS-006 |
| 4 | Log payload includes secret-like key | Redaction filter removes value | REQ-WAL-003 |
| 5 | CloudWatch unavailable | App keeps local stdout logging and health marks log sink degraded | REQ-OBS-002 |
| 6 | Metric filter misses event because field is absent | Contract test fails for required log schema | REQ-OBS-001 |

### 23.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Health repository unavailable | DB | Return degraded health response | Yes |
| Log serialization failure | Logger | Fall back to plain error log with correlation ID | No |
| Audit event query fails | Audit repository | Audit dashboard section degraded | Yes |

### 23.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Debuggability | Decisions trace across services | Correlation ID in logs and persisted rows |
| Security | Logs do not leak secrets | Redaction filter and API schemas without secret values |
| Operations | Health visible in app and AWS | Dashboard health plus CloudWatch logs |
| Reliability | Alarms map to documented failure modes | Metric filters for worker, ingestion, venue, LLM, orders, SES, Alpaca, comparison |

### 23.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Worker repositories | Latest job run state | Health status |
| Imports | Audit service | Recent audit events | Dashboard audit |
| Exports to | CloudWatch | stdout logs | JSON events |
| Exports to | Dashboard API | Health response | Component state |

### 23.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | CloudWatch logs plus dashboard health are sufficient for v1, without Prometheus. | Later may add metrics dashboards. | DESIGN CHOICE |

---

## 24. CloudFormation Infrastructure

**File:** `infra/cloudformation/`  
**Responsibility:** Define AWS resources for development and production in `us-east-1`: ECS Fargate, ECR, RDS Postgres, S3, Secrets Manager, CloudWatch, SES, IAM, networking, and load balancing.  
**Requirements Covered:** REQ-DEP-002, REQ-DEP-006, REQ-DEP-010, REQ-WAL-003, REQ-DAT-003, REQ-DAT-006, REQ-DAT-007, REQ-NOT-001, REQ-OBS-002, REQ-DB-001, REQ-DB-002, REQ-DB-003  
**Dependencies:** GitHub Actions deploy workflow, Docker images, AWS account, SES identity verification  
**Depended On By:** CI/CD, production deployment, development deployment

### 24.1 Public Interface

#### Templates and parameters

| File | Purpose | REQ Trace |
|------|---------|-----------|
| `network.yaml` | VPC, subnets, security groups, ALB | REQ-DEP-002 |
| `data.yaml` | RDS Postgres, S3 buckets, KMS keys | REQ-DB-001, REQ-DAT-003 |
| `secrets.yaml` | Secrets Manager paths and IAM access | REQ-WAL-003 |
| `compute.yaml` | ECR repositories, ECS cluster, task definition, service | REQ-DEP-002, REQ-DEP-006 |
| `observability.yaml` | CloudWatch log groups and alarms | REQ-OBS-002 |
| `ses.yaml` | SES identity references and sending permissions | REQ-NOT-001 |
| `parameters/dev.json` | Development stack parameters | REQ-DEP-010 |
| `parameters/prod.json` | Production stack parameters | REQ-DEP-010 |

### 24.2 Internal Implementation Details

#### ECS Shape

- **What it does:** Runs frontend and backend as separate containers in one ECS task and one ECS service.
- **Why this approach:** Matches the approved v1 deployment while preserving a future split path.
- **Complexity:** One service deployment per environment.
- **Key steps:** Pull images from ECR, inject non-secret config as env vars, read secrets from Secrets Manager, route ALB traffic to frontend and backend target paths.

#### Environment Separation

- **What it does:** Creates separate development and production resources.
- **Why this approach:** Branch-based deploys should not share data, secrets, buckets, or wallets.
- **Complexity:** Two stack parameter sets.
- **Key steps:** Prefix all resource names with environment, use separate KMS keys/buckets/RDS/secrets/log groups, and restrict IAM by environment.

### 24.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `StackParameters` | JSON parameter set | Environment, domain, image tags, DB sizing, SES identity | Environment is dev or prod |
| `SecretPath` | Naming convention | `/codex-poly-bot/{environment}/{venue}/{model_provider}/{secret_name}` | Environment and provider required |
| `S3KeyPolicy` | Lifecycle config | Raw and normalized retention rules | Raw 365 days, normalized 730 days |

### 24.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Production stack tries to use development secret path | CloudFormation/IAM policy blocks access | REQ-DEP-010, REQ-WAL-003 |
| 2 | S3 bucket accidentally made public | Public access block and bucket policy deny public access | REQ-DEP-002 |
| 3 | RDS unavailable to ECS task | Health check fails and dashboard marks DB down | REQ-DB-007 |
| 4 | SES identity not verified | Stack exposes incomplete notification status; sends fail safely | REQ-NOT-001 |
| 5 | Lifecycle rules omitted | Template validation/test fails before deploy | REQ-DAT-006, REQ-DAT-007 |

### 24.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| CloudFormation update fails | AWS | Roll back stack update and fail workflow | Yes |
| ECS task fails health check | ECS/ALB | Keep old task during rolling deploy where possible | Yes |
| Secret missing | Secrets Manager | App starts degraded; live orders blocked | Yes |

### 24.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Security | Secrets and data encrypted | KMS for RDS, S3, Secrets Manager |
| Isolation | Dev and prod do not share resources | Separate stacks and IAM scopes |
| Operations | Logs available in AWS | CloudWatch log groups per container/environment |
| Cost Control | v1 avoids extra worker services | One ECS service and task definition |

### 24.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | GitHub Actions | Image tags and stack parameters | Deployment inputs |
| Exports to | ECS | Task definitions | Runtime environment |
| Exports to | Application | Secrets, DB URL, bucket names | Bootstrap config |

### 24.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | SES sender identity will be verified outside the app before production alerts are enabled. | Notifications remain degraded until verified. | OPERATIONAL ASSUMPTION |

---

## 25. GitHub Actions CI/CD

**File:** `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`  
**Responsibility:** Run tests, build images, push to ECR, deploy CloudFormation and ECS updates from `develop` and `main`.  
**Requirements Covered:** REQ-DEP-003, REQ-DEP-004, REQ-DEP-005, REQ-DEP-006, REQ-DEP-010, REQ-OBS-002  
**Dependencies:** CloudFormation templates, AWS OIDC roles, Dockerfiles, backend/frontend test suites  
**Depended On By:** Development and production deployments

### 25.1 Public Interface

#### Workflows

| Workflow | Trigger | Purpose | REQ Trace |
|----------|---------|---------|-----------|
| `ci.yml` | Pull request and push | Backend tests, frontend tests, lint/type checks, migration check | REQ-DEP-005 |
| `deploy.yml` | Push to `develop` or `main` | Build, push ECR images, deploy target environment | REQ-DEP-003, REQ-DEP-004, REQ-DEP-006 |

### 25.2 Internal Implementation Details

#### Deployment Flow

- **What it does:** Converts branch merges into environment-specific deployments.
- **Why this approach:** User requested automatic `develop` to dev and `main` to prod deployment.
- **Complexity:** O(number of images plus stack updates).
- **Key steps:**
  1. Determine environment strictly from `github.ref`.
  2. Run CI gates.
  3. Build backend and frontend container images.
  4. Authenticate to AWS through OIDC role scoped to the target environment.
  5. Push images to ECR with commit SHA tags.
  6. Deploy or update CloudFormation stack.
  7. Validate migrations against the migration safety policy.
  8. For production, create an RDS snapshot or restore point before migrations.
  9. Run database migrations as a controlled ECS one-off task.
  10. Update ECS service to new task definition and wait for stability.

#### Migration Safety Policy

- **What it does:** Keeps automatic branch deploys compatible with database changes.
- **Why this approach:** Production deploys are automatic on `main`, so schema changes must be safe without manual timing.
- **Complexity:** O(number of migration files).
- **Rules:**
  1. Automatic deploys allow backward-compatible expand migrations: additive tables, additive nullable columns, additive indexes, new enum-like lookup rows, and non-breaking views.
  2. Contract migrations that drop columns, rename columns, tighten nullability, change types, or delete data are rejected by CI unless split into a later deploy after code no longer depends on the old shape.
  3. Production migration jobs create a pre-migration RDS snapshot or restore point and write the identifier to the deploy summary.
  4. Migration files must include downgrade guidance even when automatic downgrade is unsafe.
  5. Rollback after a migration prefers rolling application tasks back to the prior image when the schema is backward compatible. If schema is not backward compatible, the runbook uses the RDS restore point and marks the deployment for manual recovery.

### 25.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `EnvironmentMap` | Workflow mapping | `develop -> dev`, `main -> prod` | Cannot be overridden by user input |
| `ImageTagSet` | Workflow output | Backend and frontend commit SHA tags | SHA tag immutable |
| `DeploySummary` | Workflow summary | Stack, service, images, migration status | Written on every deploy |
| `MigrationPlan` | CI check output | Migration files, compatibility result, restore point ID | Required before deploy |

### 25.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Tests fail | Stop before image build/deploy | REQ-DEP-005 |
| 2 | Workflow triggered from non-deploy branch | Run CI only; do not deploy | REQ-DEP-003, REQ-DEP-004 |
| 3 | Migration fails | Stop deployment or roll back ECS update before new tasks serve traffic | REQ-DEP-005 |
| 4 | Concurrent deploys to same environment | Concurrency group cancels or queues older run | REQ-DEP-010 |
| 5 | AWS OIDC role mismatch | Workflow fails before accessing target AWS resources | REQ-DEP-010 |
| 6 | Migration is destructive or contract-phase | CI rejects automatic deploy and instructs expand/contract split | REQ-DEP-004, REQ-DEP-005 |
| 7 | Production migration succeeds but new tasks fail health check | Roll back ECS image; keep schema because migration must be backward compatible | REQ-DEP-004 |

### 25.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| ECR push failure | AWS/Docker | Fail workflow before deploy | Yes |
| CloudFormation failure | AWS | Fail workflow and preserve rollback status | Yes |
| ECS stability timeout | ECS | Fail workflow and keep previous task health visible | Yes |
| RDS snapshot creation fails in production | AWS | Stop before migration | Yes |

### 25.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Safety | Broken code should not auto-deploy | Tests and migration checks before deploy |
| Safety | Schema rollback is controlled | Backward-compatible migrations, production restore point, expand/contract policy |
| Traceability | Deploys tie to commits | Immutable SHA image tags and workflow summary |
| Isolation | Dev/prod roles separate | Branch-derived environment and OIDC role scopes |

### 25.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Dockerfiles | Build contexts | Container images |
| Imports | CloudFormation | Templates and parameters | Stack updates |
| Exports to | ECR/ECS | Images and task definitions | Runtime deployment |

### 25.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Production deploy on `main` is automatic with no manual approval gate. | Main branch protections must carry the review burden. | USER APPROVED |

---

## 26. Local Development and Codex Web Setup

**File:** `docker-compose.yml`, `.env.example`, `backend/.env.example`, `frontend/.env.example`, `scripts/setup_codex.sh`, `AGENTS.md`  
**Responsibility:** Make the project runnable locally and testable in Codex web without production trading secrets.  
**Requirements Covered:** REQ-DEP-001, REQ-DEP-005, REQ-DEP-007, REQ-DEP-008, REQ-DEP-009, REQ-WAL-004, REQ-EXE-001, REQ-VEN-003  
**Dependencies:** Docker, local Postgres, backend app, frontend app, pytest, Playwright  
**Depended On By:** Developers, Codex web, CI

### 26.1 Public Interface

#### Commands and files

| Interface | Purpose | REQ Trace |
|-----------|---------|-----------|
| `docker compose up` | Run local Postgres, backend, and frontend | REQ-DEP-001 |
| `scripts/setup_codex.sh` | Install dependencies and seed safe defaults | REQ-DEP-008, REQ-DEP-009 |
| `.env.example` files | Document required local variables without secrets | REQ-DEP-007 |
| `make test` or equivalent script | Run backend and frontend tests | REQ-DEP-005 |
| `make dev` or equivalent script | Start local dev servers | REQ-DEP-001 |

### 26.2 Internal Implementation Details

#### Local Safety Defaults

- **What it does:** Ensures local and Codex environments cannot accidentally trade live.
- **Why this approach:** Tests and cloud coding sessions should not need production secrets.
- **Complexity:** O(1) config seed.
- **Key steps:**
  1. Seed `LIVE_ENABLED=false`.
  2. Seed all venue enabled flags as false.
  3. Use local `.env` only for optional developer credentials.
  4. Use mocked or file-backed AWS adapters by default for local tests.
  5. Require explicit local env changes before any real external API call.

### 26.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `LocalEnv` | `.env` variables | DB URL, auth secrets, optional API credentials | Gitignored |
| `CodexSetupProfile` | Script mode | Dependency install and mock config | No production secrets |
| `SeedConfig` | Bootstrap data | Dry-run and disabled venues | Safe by default |

### 26.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | `.env` is missing | App starts with clear setup error or mock defaults where safe | REQ-DEP-007 |
| 2 | Codex web lacks trading secrets | Tests still install and run with mocked adapters | REQ-DEP-009 |
| 3 | Developer tries local live trading with venue disabled | Live order refused | REQ-VEN-003, REQ-EXE-001 |
| 4 | `.env` contains production-looking secret path in Codex profile | Setup script warns and refuses live profile | REQ-DEP-009 |

### 26.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Docker service fails | Docker Compose | Surface failing service and logs | Yes |
| Dependency install fails | Setup script | Stop with command and environment context | Yes |
| Local DB migration fails | Alembic | Stop app startup and show migration error | Yes |

### 26.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Safety | No accidental live trading | Dry-run and venue-disabled defaults |
| Developer Experience | Local setup is repeatable | Compose, examples, setup script |
| Security | Secrets stay out of git | `.gitignore`, examples without values, Codex no prod secret path |

### 26.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Backend/frontend | Package managers | Dependencies |
| Imports | Docker | Compose services | Local runtime |
| Exports to | Codex web | Setup script and AGENTS guidance | Safe development environment |

### 26.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Local tests can use mocked AWS/venue/LLM adapters by default. | Real adapter tests need separate opt-in credentials. | DESIGN CHOICE |

---

## 27. Documentation and Runbooks

**File:** `docs/`  
**Responsibility:** Document setup, deployment, source references, live enablement, wallet/account setup, operations, and rollback.  
**Requirements Covered:** REQ-DEP-001, REQ-DEP-002, REQ-DEP-003, REQ-DEP-004, REQ-DEP-007, REQ-DEP-008, REQ-DEP-009, REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-004, REQ-WAL-006, REQ-EXE-001, REQ-EXE-014, REQ-EXE-017, REQ-OBS-005  
**Dependencies:** Requirements, HLD, LLD, CloudFormation templates, CI/CD workflows  
**Depended On By:** Developers, operators, Codex web sessions

### 27.1 Public Interface

#### Documents

| File | Purpose | REQ Trace |
|------|---------|-----------|
| `docs/local-development.md` | Local Docker and `.env` setup | REQ-DEP-001, REQ-DEP-007 |
| `docs/codex-web.md` | Codex web setup with safe defaults | REQ-DEP-008, REQ-DEP-009 |
| `docs/deployment.md` | AWS stack and GitHub Actions deployment | REQ-DEP-002, REQ-DEP-003, REQ-DEP-004 |
| `docs/wallets-and-accounts.md` | Polymarket wallet and Alpaca account setup | REQ-WAL-001, REQ-WAL-002 |
| `docs/live-trading-checklist.md` | Steps before disabling dry-run | REQ-EXE-001, REQ-EXE-017 |
| `docs/operations-runbook.md` | Kill switch, degraded health, retry, rollback, schema recovery | REQ-EXE-014, REQ-OBS-005, REQ-DEP-004 |
| `docs/source-references.md` | Prior art and official API references used | REQ-DEP-008 |

### 27.2 Internal Implementation Details

#### Live Enablement Checklist

- **What it does:** Documents the human checks before live mode.
- **Why this approach:** Live trading should require clear operational readiness even though the dashboard toggle is simple.
- **Complexity:** O(number of readiness checks).
- **Key steps:** Verify environment, wallets/accounts, venue flags, Alpaca account uniqueness, risk limits, dry-run results, SES, dashboard auth, kill switch, and current config version.

#### Source Reference Policy

- **What it does:** Records where design ideas and external API behavior came from.
- **Why this approach:** User asked to avoid blind dependency on source repos but cite useful sources.
- **Complexity:** O(number of references).
- **Key steps:** Link `pmbot.md`, any reviewed public repos, and official Polymarket, Alpaca, OpenAI, Anthropic, AWS, and Next.js/FastAPI docs used during implementation.

#### Deployment Rollback Runbook

- **What it does:** Defines the response path for bad automatic deploys.
- **Why this approach:** Automatic production deploys require a documented way to recover from application or schema issues.
- **Complexity:** O(number of affected resources).
- **Key steps:**
  1. Identify commit SHA, image tags, CloudFormation change set, ECS task definition, migration revision, and production RDS restore point from the deploy summary.
  2. If migration is backward compatible, roll ECS service back to the prior task definition/image and keep the expanded schema.
  3. If a schema change cannot safely serve the prior app, stop live mode, keep kill switch active, restore RDS from the recorded restore point, and redeploy the prior known-good task definition.
  4. Record an audit/operations event with actor, environment, rollback reason, affected image tags, and restore point.
  5. Re-run health checks, dashboard smoke tests, and live-trading refusal checks before clearing degraded state.

### 27.3 Data Structures

| Structure | Type | Description | Invariants |
|-----------|------|-------------|------------|
| `RunbookStep` | Markdown pattern | Symptom, check, action, rollback | Action avoids secret disclosure |
| `SourceReference` | Markdown table row | Source, URL/path, idea used, caveat | Distinguishes official docs from prior art |
| `LiveChecklistItem` | Markdown checkbox | Readiness item and owner | All required before live |

### 27.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|----------|-------------------|-----------|
| 1 | Developer follows docs in Codex web | Docs do not require production secrets | REQ-DEP-009 |
| 2 | Operator needs rollback after bad deploy | Runbook points to prior ECS task/image and CloudFormation rollback | REQ-DEP-004 |
| 3 | Live mode requested before wallet/account setup | Checklist blocks operational approval; app still refuses missing credentials | REQ-WAL-006 |
| 4 | Kill switch activated | Runbook shows dashboard and API verification steps | REQ-EXE-014 |
| 5 | Bad deploy includes schema migration | Runbook distinguishes backward-compatible app rollback from RDS restore | REQ-DEP-004 |

### 27.5 Error Handling

| Error Condition | Source | Handling Strategy | User-Visible? |
|----------------|--------|-------------------|---------------|
| Docs and config defaults diverge | CI docs check or review | Update docs with config change | Yes |
| Source link changes | Documentation review | Mark source unavailable and keep local design rationale | Yes |

### 27.6 Non-Functional Requirements

| NFR | Requirement | How Addressed |
|-----|-------------|---------------|
| Maintainability | Operators need current procedures | Runbooks live with code |
| Auditability | Source ideas documented | Source reference table |
| Safety | Live mode has readiness checklist | Required operational document |

### 27.7 Dependencies & Integration Points

| Direction | Module | Interface Used | Data Exchanged |
|-----------|--------|----------------|----------------|
| Imports | Requirements/design docs | REQ and DD IDs | Traceable docs |
| Imports | CI/CD and infra | Workflow/template names | Deployment steps |
| Exports to | Developers/operators | Markdown docs | Setup and runbooks |

### 27.8 Open Questions / Assumptions

| # | Question/Assumption | Impact if Wrong | Status |
|---|---------------------|-----------------|--------|
| 1 | Markdown docs in repo are enough for v1 operational procedures. | Later may move to a hosted runbook/wiki. | DESIGN CHOICE |
