# Task List

## Task Defaults

| Field | Default |
|-------|---------|
| Story size | One story per component or tightly related component group |
| Story format | As a [role], I want [goal], so that [benefit]. |
| Estimates | T-shirt sizes |
| Labels | `codex-poly-bot`, `spec-driven-dev`, phase label |

---

### TASK-001: Scaffold Local Development and Safe Defaults

**Story:** As a developer, I want a local monorepo scaffold with safe default configuration, so that I can run and test the bot without live trading risk.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 1 - Foundation and safety kernel  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-1-foundation`  
**Dependencies:** None

**Requirements Covered:**
- REQ-DEP-001
- REQ-DEP-007
- REQ-DEP-008
- REQ-DEP-009
- REQ-EXE-001
- REQ-VEN-002
- REQ-VEN-003
- REQ-EXE-012
- REQ-ALP-013

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-001-01 | When a developer runs the local setup, the system shall create backend, frontend, infra, docs, and scripts structure under `codex-poly-bot`. |
| AC-001-02 | When default config is seeded, the system shall set `default_selected_venue=polymarket_us`, `LIVE_ENABLED=false`, and all venue enabled flags to false. |
| AC-001-03 | When local `.env.example` files are generated, the system shall document required variables without containing secret values. |
| AC-001-04 | If Codex web lacks production trading secrets, then dependency installation and tests shall still run with safe mocked defaults. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-002: Implement Domain Models and Validation

**Story:** As a backend developer, I want typed domain models for venues, instruments, scores, decisions, orders, positions, config, and audit records, so that later services share the same validation rules.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 1 - Foundation and safety kernel  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-1-foundation`  
**Dependencies:** TASK-001

**Requirements Covered:**
- REQ-VEN-001
- REQ-ALP-001
- REQ-ALP-002
- REQ-DB-004
- REQ-DB-005
- REQ-LLM-003
- REQ-STR-007
- REQ-EXE-008
- REQ-EXE-016
- REQ-EXT-001
- REQ-CMP-001
- REQ-CMP-003
- REQ-OBS-001

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-002-01 | When a domain object is created, the system shall validate required venue, environment, model provider, instrument, money, probability, and timestamp fields. |
| AC-002-02 | If an Alpaca instrument is not a stock or ETF, then the system shall reject it for v1 trading use. |
| AC-002-03 | When an order, position, score, or decision model is serialized, the system shall preserve REQ traceable fields needed for persistence and audit. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-003: Build Postgres Schemas, Migrations, and Repositories

**Story:** As a backend developer, I want Postgres schemas, migrations, and repositories for shared, Claude, and OpenAI data, so that trading state is persisted before any live action.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 1 - Foundation and safety kernel  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-1-foundation`  
**Dependencies:** TASK-002

**Requirements Covered:**
- REQ-DB-001
- REQ-DB-002
- REQ-DB-003
- REQ-DB-004
- REQ-DB-005
- REQ-DB-006
- REQ-DB-007
- REQ-ALP-016
- REQ-ALP-017
- REQ-ALP-018
- REQ-EXE-016
- REQ-OBS-003
- REQ-OBS-004

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-003-01 | When migrations run, the system shall create shared, Claude, and OpenAI schemas in the configured Postgres database. |
| AC-003-02 | When a trade decision or position transition is recorded, the system shall persist all required fields in the correct schema. |
| AC-003-03 | If Postgres is unavailable during a live-order path, then the system shall block live order placement and surface degraded status. |
| AC-003-04 | When audit, trade, and position records are created, the system shall retain them indefinitely unless a later archive policy is configured. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-004: Implement Audit Service and Observability Foundation

**Story:** As an operator, I want audit records and structured logs for sensitive actions and system health, so that I can trace trading and configuration behavior.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 1 - Foundation and safety kernel  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-1-foundation`  
**Dependencies:** TASK-003

**Requirements Covered:**
- REQ-OBS-001
- REQ-OBS-002
- REQ-OBS-003
- REQ-OBS-004
- REQ-OBS-005
- REQ-OBS-006
- REQ-UI-006
- REQ-EXE-016
- REQ-DB-006

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-004-01 | When a live order is refused, submitted, filled, canceled, or failed, the system shall produce an audit event. |
| AC-004-02 | When a dashboard user changes configuration, toggles live mode, or activates the kill switch, the system shall produce an audit event with actor, environment, timestamp, and IP address. |
| AC-004-03 | If a background worker fails, then the system shall record the failure and make degraded status available to dashboard reads. |
| AC-004-04 | When the app runs in AWS, the system shall send structured application logs to CloudWatch. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-005: Implement Versioned Config Service and Safe Runtime Settings

**Story:** As an operator, I want runtime configuration stored in Postgres with validation and audit, so that dashboard changes apply safely on the next trading loop.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 1 - Foundation and safety kernel  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-1-foundation`  
**Dependencies:** TASK-003, TASK-004

**Requirements Covered:**
- REQ-VEN-002
- REQ-VEN-003
- REQ-VEN-006
- REQ-ALP-007
- REQ-ALP-009
- REQ-ALP-010
- REQ-ALP-011
- REQ-ALP-012
- REQ-ALP-013
- REQ-ALP-014
- REQ-LLM-006
- REQ-LLM-007
- REQ-STR-002
- REQ-STR-009
- REQ-EXE-001
- REQ-EXE-003
- REQ-EXE-007
- REQ-EXE-012
- REQ-NOT-006
- REQ-UI-005
- REQ-UI-006
- REQ-UI-007
- REQ-DEP-010

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-005-01 | When default configuration is seeded, the system shall use Polymarket US as the selected venue while leaving all venues disabled. |
| AC-005-02 | When an authorized config change is saved, the system shall create a new config version and audit the old and new values. |
| AC-005-03 | If a config update has a stale expected version, then the system shall reject the update with a conflict. |
| AC-005-04 | When a loop starts, the system shall use one config snapshot until that loop finishes. |
| AC-005-05 | When default risk configuration is seeded, the system shall set Polymarket max position `25.00`, max daily loss `50.00`, max open positions `5`, market-order slippage threshold `0.02`, and trading loop interval `60` seconds. |
| AC-005-06 | When default Alpaca configuration is seeded, the system shall set max position `100.00`, max daily loss `100.00`, max open positions `5`, max symbol allocation `0.10`, and market-order slippage threshold `0.005`. |
| AC-005-07 | When multiple dashboard users are allowed, the system shall keep user-owned config versions separate from shared config versions. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-006: Implement Auth Service and API Trust Boundary

**Story:** As an operator, I want GitHub OAuth and username allowlist authorization enforced by the backend, so that only approved users can operate the bot.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 1 - Foundation and safety kernel  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-1-foundation`  
**Dependencies:** TASK-005

**Requirements Covered:**
- REQ-UI-002
- REQ-UI-003
- REQ-UI-006
- REQ-UI-008
- REQ-OBS-004

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-006-01 | When a dashboard API request is received, the system shall validate the signed session token before calling protected services. |
| AC-006-02 | If the authenticated GitHub username is not on the allowlist, then the system shall deny access. |
| AC-006-03 | If a mutation request has an invalid origin or CSRF context, then the system shall reject the request before any state change. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-007: Establish CI Baseline and Test Harness

**Story:** As a developer, I want CI and local test commands in place before feature work expands, so that every later component has a reliable verification path.

**Priority:** P0  
**Estimate:** M  
**Phase:** Phase 1 - Foundation and safety kernel  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-1-foundation`  
**Dependencies:** TASK-006

**Requirements Covered:**
- REQ-DEP-001
- REQ-DEP-005
- REQ-DEP-007
- REQ-DEP-008
- REQ-DEP-009
- REQ-OBS-001

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-007-01 | When CI runs, the system shall execute backend tests before any build or deploy job. |
| AC-007-02 | When local test commands run without production secrets, the system shall use mocked adapters and safe defaults. |
| AC-007-03 | If dependency installation fails, then the setup script shall stop with a clear error message. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-008: Define Venue Ports and Polymarket Adapter Contracts

**Story:** As a backend developer, I want venue interfaces and Polymarket adapter contracts, so that market data and order execution are isolated from trading logic.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 2 - Adapter contracts and credential boundaries  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-2-adapters`  
**Dependencies:** TASK-002, TASK-005, TASK-007

**Requirements Covered:**
- REQ-VEN-001
- REQ-VEN-003
- REQ-VEN-004
- REQ-VEN-005
- REQ-DAT-001
- REQ-DAT-002
- REQ-DAT-005
- REQ-EXE-010
- REQ-EXE-011
- REQ-EXE-013
- REQ-EXE-015
- REQ-EXE-016
- REQ-EXT-006
- REQ-OBS-001

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-008-01 | When a Polymarket venue is disabled, the system shall refuse scan, score, and new trade work before calling the adapter. |
| AC-008-02 | When a live Polymarket order is submitted, the system shall use the official SDK or documented API client boundary. |
| AC-008-03 | If a venue configuration is unsupported, then the adapter contract shall return a refusal reason that can be persisted. |
| AC-008-04 | When a venue is disabled after an order exists, the system shall still allow cancel, status, and reconciliation calls for known open orders. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-009: Define Alpaca Adapter and Reconciliation Contracts

**Story:** As a backend developer, I want Alpaca account, market data, position, order, and reconciliation contracts, so that stock and ETF trading can be controlled safely.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 2 - Adapter contracts and credential boundaries  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-2-adapters`  
**Dependencies:** TASK-002, TASK-003, TASK-005, TASK-008

**Requirements Covered:**
- REQ-ALP-001
- REQ-ALP-002
- REQ-ALP-003
- REQ-ALP-004
- REQ-ALP-008
- REQ-ALP-015
- REQ-ALP-016
- REQ-ALP-017
- REQ-ALP-018
- REQ-DAT-001
- REQ-DAT-002
- REQ-EXE-010
- REQ-EXE-011
- REQ-EXE-016

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-009-01 | When Alpaca credentials are validated, the system shall resolve and persist the broker account identifier without storing secrets in Postgres. |
| AC-009-02 | If two model providers resolve to the same Alpaca account identifier in the same environment and account mode, then the system shall block Alpaca live trading for the duplicated account. |
| AC-009-03 | If Alpaca market data is stale, rate-limited, unavailable, or outside trading hours, then the system shall block affected live orders and record the reason. |
| AC-009-04 | When Alpaca reconciliation runs, the system shall compare account ID, account status, buying power, positions, and open orders against Postgres. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-010: Implement AWS Adapter Contracts for S3, Secrets, and SES

**Story:** As a backend developer, I want AWS adapter contracts for storage, secrets, and email, so that services can run locally with mocks and in AWS with managed services.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 2 - Adapter contracts and credential boundaries  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-2-adapters`  
**Dependencies:** TASK-002, TASK-007

**Requirements Covered:**
- REQ-DAT-003
- REQ-DAT-004
- REQ-DAT-006
- REQ-DAT-007
- REQ-DAT-008
- REQ-WAL-003
- REQ-WAL-007
- REQ-NOT-001
- REQ-NOT-003
- REQ-NOT-004
- REQ-NOT-007
- REQ-DEP-002
- REQ-OBS-002

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-010-01 | When a snapshot is stored, the system shall write raw and normalized objects using environment, venue, snapshot type, and UTC date partitions. |
| AC-010-02 | If an S3 write succeeds but metadata persistence fails, then the system shall allow deterministic retry without duplicate logical ingestion. |
| AC-010-03 | When credentials are rotated, the secrets adapter shall use the updated secret on the next credential refresh. |
| AC-010-04 | If SES delivery fails, then the email adapter shall return retryable failure metadata without losing the delivery attempt. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-011: Implement Wallet Service and Wallet CLI

**Story:** As an operator, I want wallet and credential setup tools, so that each environment, venue, and model provider has separate trading credentials.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 2 - Adapter contracts and credential boundaries  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-2-adapters`  
**Dependencies:** TASK-005, TASK-009, TASK-010

**Requirements Covered:**
- REQ-WAL-001
- REQ-WAL-002
- REQ-WAL-003
- REQ-WAL-004
- REQ-WAL-005
- REQ-WAL-006
- REQ-WAL-007
- REQ-ALP-004
- REQ-ALP-016
- REQ-DEP-007

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-011-01 | When a user runs the wallet CLI for Polymarket, the system shall generate wallet material for the requested environment, venue, and model provider. |
| AC-011-02 | In deployed environments, the system shall store private keys and API credentials only in AWS Secrets Manager. |
| AC-011-03 | In local development, the system shall read private keys and API credentials from gitignored `.env` files. |
| AC-011-04 | If a live order lacks a wallet or brokerage credential, then the system shall refuse the order and record the refusal reason. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-012: Implement LLM Ports and Provider Adapter Contracts

**Story:** As a backend developer, I want provider-neutral LLM scoring contracts for OpenAI and Claude, so that both models can evaluate the same candidates with separate budgets.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 2 - Adapter contracts and credential boundaries  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-2-adapters`  
**Dependencies:** TASK-002, TASK-005, TASK-007

**Requirements Covered:**
- REQ-LLM-001
- REQ-LLM-002
- REQ-LLM-003
- REQ-LLM-004
- REQ-LLM-005
- REQ-OBS-001

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-012-01 | When a candidate is scored, the system shall call each eligible model provider through the same scoring interface. |
| AC-012-02 | When a provider returns a scoring result, the system shall record provider, prompt version, input summary, thesis, confidence, estimated probability, and cost estimate. |
| AC-012-03 | If a provider call times out or returns invalid output, then the system shall persist a scoring failure and block live orders for that provider and market in the current loop. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-013: Implement Ingestion Service and Staleness Checks

**Story:** As an operator, I want full and incremental ingestion jobs with checkpoints and staleness status, so that trading decisions use current replayable market data.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 3 - Core dry-run trading engine  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-3-trading-core`  
**Dependencies:** TASK-008, TASK-009, TASK-010

**Requirements Covered:**
- REQ-DAT-001
- REQ-DAT-002
- REQ-DAT-003
- REQ-DAT-004
- REQ-DAT-005
- REQ-DAT-006
- REQ-DAT-007
- REQ-DAT-008
- REQ-ALP-015
- REQ-OBS-001
- REQ-OBS-006

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-013-01 | When the daily full-ingestion schedule reaches 06:00 UTC, the system shall download and store a full snapshot for enabled venues. |
| AC-013-02 | When the incremental interval elapses, the system shall download only changed data since the prior checkpoint. |
| AC-013-03 | If ingestion fails, then the system shall record the error, preserve the last successful checkpoint, and retry according to policy. |
| AC-013-04 | If market data is stale beyond a configured threshold, then the system shall block live orders that depend on that data. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-014: Implement Scoring Service and Budget Ledger

**Story:** As an operator, I want eligible markets scored by OpenAI and Claude with budget controls, so that model comparison does not overspend or trade on failed scoring.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 3 - Core dry-run trading engine  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-3-trading-core`  
**Dependencies:** TASK-012, TASK-013

**Requirements Covered:**
- REQ-LLM-001
- REQ-LLM-002
- REQ-LLM-003
- REQ-LLM-004
- REQ-LLM-005
- REQ-LLM-006
- REQ-LLM-007
- REQ-STR-003
- REQ-OBS-001

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-014-01 | When the trading loop has eligible candidates, the system shall score them with both Claude and OpenAI subject to provider budgets. |
| AC-014-02 | If a model budget is exhausted, then the system shall stop sending new requests to that model and continue other eligible models. |
| AC-014-03 | When scoring settings change, the system shall apply the new settings on the next trading loop. |
| AC-014-04 | If LLM scoring fails for a market, then the system shall block live orders for that model and market in the current loop. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-015: Implement Strategy Engine and Strategy Modules

**Story:** As an operator, I want deterministic filters and strategy signals for Polymarket and Alpaca candidates, so that the bot creates traceable trade decisions.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 3 - Core dry-run trading engine  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-3-trading-core`  
**Dependencies:** TASK-013, TASK-014

**Requirements Covered:**
- REQ-STR-001
- REQ-STR-002
- REQ-STR-003
- REQ-STR-004
- REQ-STR-005
- REQ-STR-006
- REQ-STR-007
- REQ-STR-008
- REQ-STR-009
- REQ-ALP-001
- REQ-ALP-002
- REQ-ALP-015

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-015-01 | When the trading loop runs, the system shall scan enabled venues and apply deterministic filters before LLM scoring. |
| AC-015-02 | When arbitrage, convergence, whale-copy, or Alpaca stock strategies produce signals, the system shall persist each signal before creating an execution decision. |
| AC-015-03 | If strategy signals disagree for the same model and market, then the system shall apply the configured consensus rule before creating an order. |
| AC-015-04 | When a strategy is disabled through configuration, the system shall exclude it from consensus on the next trading loop. |
| AC-015-05 | When related-market price dislocation exceeds configured thresholds, the arbitrage strategy shall emit a traceable strategy signal. |
| AC-015-06 | When market price diverges from a model estimate enough to meet convergence settings, the convergence strategy shall emit a traceable strategy signal. |
| AC-015-07 | When a configured target wallet action is observed after the configured delay, the whale-copy strategy shall emit a traceable strategy signal or a neutral stale-data signal. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-016: Implement Risk Engine and Live Refusal Matrix

**Story:** As an operator, I want shared and venue-specific risk checks before execution, so that unsafe or uncertain orders are refused and recorded.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 3 - Core dry-run trading engine  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-3-trading-core`  
**Dependencies:** TASK-003, TASK-005, TASK-009, TASK-014, TASK-015

**Requirements Covered:**
- REQ-VEN-003
- REQ-VEN-005
- REQ-WAL-006
- REQ-LLM-005
- REQ-DAT-005
- REQ-EXE-001
- REQ-EXE-002
- REQ-EXE-004
- REQ-EXE-005
- REQ-EXE-006
- REQ-EXE-007
- REQ-EXE-008
- REQ-EXE-009
- REQ-EXE-011
- REQ-EXE-012
- REQ-EXE-013
- REQ-EXE-014
- REQ-EXE-017
- REQ-ALP-002
- REQ-ALP-008
- REQ-ALP-009
- REQ-ALP-010
- REQ-ALP-011
- REQ-ALP-012
- REQ-ALP-013
- REQ-ALP-015
- REQ-ALP-017
- REQ-ALP-018

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-016-01 | When global dry-run is enabled, the risk engine shall approve only the simulated execution path. |
| AC-016-02 | If a live-order blocker exists, then the risk engine shall refuse the order with a stable reason code. |
| AC-016-03 | When sizing an order, the system shall calculate a Kelly-based size and cap it by configured risk limits. |
| AC-016-04 | If estimated market-order slippage exceeds the configured threshold, then the system shall block the order. |
| AC-016-05 | If Alpaca reconciliation is stale or mismatched, then the system shall block Alpaca live orders for the affected model provider. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-017: Implement Execution Service and Order Lifecycle

**Story:** As an operator, I want dry-run and live execution paths with idempotency, kill switch support, and order event persistence, so that orders are traceable and duplicate submissions are avoided.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 3 - Core dry-run trading engine  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-3-trading-core`  
**Dependencies:** TASK-011, TASK-016

**Requirements Covered:**
- REQ-EXE-002
- REQ-EXE-003
- REQ-EXE-010
- REQ-EXE-013
- REQ-EXE-014
- REQ-EXE-015
- REQ-EXE-016
- REQ-EXE-017
- REQ-ALP-005
- REQ-ALP-006
- REQ-ALP-007
- REQ-ALP-017
- REQ-ALP-018
- REQ-OBS-003

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-017-01 | While dry-run mode is enabled, the system shall record simulated orders without calling any venue submit endpoint. |
| AC-017-02 | When a live order is approved, the system shall persist the order intent and audit event before submitting to the venue. |
| AC-017-03 | If venue submit state is ambiguous, then the system shall persist unknown state and reconcile before any retry. |
| AC-017-04 | When the kill switch is activated, the system shall disable live trading and attempt to cancel open orders for enabled live venues. |
| AC-017-05 | When a live entry order is approved, the system shall submit through the venue account mapped to the order's model provider. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-018: Implement Exit Monitor

**Story:** As an operator, I want open positions monitored for exit triggers, so that dry-run and live exits follow the same risk and execution rules.

**Priority:** P0  
**Estimate:** M  
**Phase:** Phase 3 - Core dry-run trading engine  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-3-trading-core`  
**Dependencies:** TASK-016, TASK-017

**Requirements Covered:**
- REQ-EXT-001
- REQ-EXT-002
- REQ-EXT-003
- REQ-EXT-004
- REQ-EXT-005
- REQ-EXT-006
- REQ-EXE-016
- REQ-ALP-008

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-018-01 | When a position reaches the configured profit target, the system shall create an exit decision. |
| AC-018-02 | When a configured volume spike or stale-thesis threshold is reached, the system shall create an exit decision. |
| AC-018-03 | While dry-run mode is enabled, the exit monitor shall record simulated exits without submitting orders. |
| AC-018-04 | While live mode is enabled, the exit monitor shall route approved exits through risk and execution. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-019: Implement Comparison Service

**Story:** As an operator, I want model and venue performance metrics, so that I can compare Claude and OpenAI across Polymarket and Alpaca.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 3 - Core dry-run trading engine  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-3-trading-core`  
**Dependencies:** TASK-003, TASK-014, TASK-017

**Requirements Covered:**
- REQ-CMP-001
- REQ-CMP-002
- REQ-CMP-003
- REQ-CMP-004
- REQ-UI-011
- REQ-NOT-002

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-019-01 | When comparison metrics are requested, the system shall calculate metrics by model provider, venue, environment, and instrument type. |
| AC-019-02 | When comparison views are built, the system shall include realized P&L, unrealized P&L, win rate, drawdown, model cost, open exposure, trade count, and return-to-risk. |
| AC-019-03 | If a metric cannot be calculated because data is missing or insufficient, then the system shall show the metric as unavailable rather than zero. |
| AC-019-04 | When comparison metrics are calculated, the system shall use the documented formulas from the approved HLD and preserve unavailable-state caveats. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-020: Implement Worker Scheduler and Notification Skeleton

**Story:** As an operator, I want background jobs with locks, heartbeats, and a notification placeholder, so that the dry-run trading loop can run safely before full notification delivery exists.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 3 - Core dry-run trading engine  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-3-trading-core`  
**Dependencies:** TASK-013, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019

**Requirements Covered:**
- REQ-STR-001
- REQ-STR-002
- REQ-STR-003
- REQ-STR-007
- REQ-STR-008
- REQ-DAT-001
- REQ-DAT-002
- REQ-DAT-008
- REQ-LLM-001
- REQ-LLM-004
- REQ-LLM-005
- REQ-EXE-003
- REQ-EXE-013
- REQ-EXE-014
- REQ-EXE-017
- REQ-EXT-001
- REQ-EXT-006
- REQ-NOT-001
- REQ-NOT-007
- REQ-CMP-001
- REQ-CMP-004
- REQ-OBS-006
- REQ-UI-007

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-020-01 | When the trading loop interval elapses, the scheduler shall run one locked trading loop using one config snapshot. |
| AC-020-02 | If a prior job heartbeat is current, then the scheduler shall skip the overlapping run and record skipped status. |
| AC-020-03 | When the kill switch is active, the scheduler shall stop new live decisions and trigger cancel flow. |
| AC-020-04 | When notification delivery is not fully configured, the notification skeleton shall record no-op job status without blocking the trading loop. |
| AC-020-05 | When no explicit runtime config owner is configured in a multi-user deployment, the scheduler shall resolve the latest active allowlisted user-owned config from the database before falling back to shared config. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-021: Implement FastAPI App and Dashboard API Routers

**Story:** As a dashboard user, I want authenticated API endpoints for status, configuration, wallet status, orders, comparison, notifications, audit, live mode, and kill switch, so that the UI can operate the bot safely.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 4 - Backend API and dashboard  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-4-dashboard-api`  
**Dependencies:** TASK-006, TASK-020

**Requirements Covered:**
- REQ-UI-001
- REQ-UI-002
- REQ-UI-003
- REQ-UI-004
- REQ-UI-005
- REQ-UI-006
- REQ-UI-007
- REQ-UI-008
- REQ-UI-009
- REQ-UI-010
- REQ-UI-011
- REQ-WAL-002
- REQ-WAL-005
- REQ-EXE-003
- REQ-EXE-014
- REQ-EXE-016
- REQ-ALP-014
- REQ-NOT-006
- REQ-OBS-004
- REQ-OBS-005
- REQ-OBS-006

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-021-01 | When an authenticated allowlisted user calls dashboard APIs, the system shall return status, config, wallet, order, model, comparison, notification, and audit responses without secret values. |
| AC-021-02 | When an authorized user changes configuration, the system shall audit actor, old value, new value, timestamp, environment, and IP address. |
| AC-021-03 | If an API request is unauthenticated or unallowlisted, then the system shall return 401 or 403 before calling protected services. |
| AC-021-04 | When the kill switch endpoint is called, the system shall persist live disabled and expose cancel progress in the response. |
| AC-021-05 | When an authenticated user reads or saves display preferences, the API shall use the database row scoped to that username and environment. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-022: Implement Next.js Auth and Server-Side Backend Token Boundary

**Story:** As a dashboard user, I want GitHub OAuth login with a server-side backend token proxy, so that the browser never receives backend signing secrets.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 4 - Backend API and dashboard  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-4-dashboard-api`  
**Dependencies:** TASK-006, TASK-021

**Requirements Covered:**
- REQ-UI-001
- REQ-UI-002
- REQ-UI-003
- REQ-UI-006
- REQ-OBS-004

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-022-01 | When a user signs in, the dashboard shall require GitHub OAuth before protected views load. |
| AC-022-02 | If the GitHub username is not allowlisted, then the dashboard shall show access denied and avoid protected mutation calls. |
| AC-022-03 | When browser code calls backend data, the system shall route through a Next.js server-side proxy that mints the FastAPI token server-side only. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-023: Implement Dashboard Status and Configuration Controls

**Story:** As an operator, I want dashboard status and configuration controls, so that I can inspect system state and change runtime settings safely.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 4 - Backend API and dashboard  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-4-dashboard-api`  
**Dependencies:** TASK-021, TASK-022

**Requirements Covered:**
- REQ-UI-004
- REQ-UI-005
- REQ-UI-006
- REQ-UI-007
- REQ-UI-009
- REQ-ALP-014
- REQ-UI-012
- REQ-NOT-006
- REQ-STR-009
- REQ-LLM-006
- REQ-EXE-007
- REQ-OBS-005

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-023-01 | When an authorized user opens the dashboard status view, the system shall show venue, wallet, ingestion, trading loop, notification, audit, and health status. |
| AC-023-02 | When an authorized user saves config, the dashboard shall submit only allowlisted config paths and show the new config version. |
| AC-023-03 | When wallet status is shown, the dashboard shall display public identifiers and health without displaying private keys or API secrets. |
| AC-023-04 | If a config save conflicts with a newer version, the dashboard shall show the current server version and require reload before resubmission. |
| AC-023-05 | When multiple users use the dashboard, summary and economics views shall load each actor's saved database preferences. |
| AC-023-06 | When scanner rejections point to configurable blockers, the dashboard shall show targeted config changes and save them through the same audited per-user config flow as manual settings. |
| AC-023-07 | When a recommendation updates an integer-only cap and market data spans venues, the dashboard shall submit an integer value and show the candidate count for each venue. |
| AC-023-08 | When scanner candidate details are deferred from the default dashboard summary, the dashboard shall show the latest persisted accepted and rejected totals and the leading venue-specific rejection reason. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-024: Implement Dashboard Analytics and Operations Views

**Story:** As an operator, I want model analytics and operations views, so that I can compare Claude and OpenAI and manage kill-switch outcomes from the dashboard.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 4 - Backend API and dashboard  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-4-dashboard-api`  
**Dependencies:** TASK-019, TASK-021, TASK-022

**Requirements Covered:**
- REQ-UI-008
- REQ-UI-010
- REQ-UI-011
- REQ-CMP-002
- REQ-CMP-003
- REQ-CMP-004
- REQ-EXE-014
- REQ-EXE-015
- REQ-EXE-016
- REQ-OBS-005

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-024-01 | When an authorized user opens a model view, the dashboard shall show provider-specific positions, decisions, budgets, and P&L for Claude or OpenAI. |
| AC-024-02 | When comparison metrics are unavailable, the dashboard shall show unavailable state and caveats rather than zero. |
| AC-024-03 | When the kill switch is active, the dashboard shall show open-order cancel progress, degraded venue status, and manual-review state. |
| AC-024-04 | When order events are displayed, the dashboard shall show refused, submitted, filled, canceled, failed, and unknown states from persisted events. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-025: Implement Polymarket Dry-Run Integration

**Story:** As an operator, I want Polymarket external reads validated in dry-run mode, so that Polymarket market data can be tested before live order submission is enabled.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 5 - External integration and notification logic  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-5-integrations`  
**Dependencies:** TASK-008, TASK-017, TASK-023

**Requirements Covered:**
- REQ-VEN-001
- REQ-VEN-004
- REQ-VEN-005
- REQ-DAT-001
- REQ-DAT-002
- REQ-DAT-005
- REQ-EXE-016
- REQ-EXE-017

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-025-01 | When dry-run mode is enabled and Polymarket is configured, the system shall use official Polymarket read APIs where configured and shall not submit live orders. |
| AC-025-02 | If Polymarket venue configuration is unsupported for the current environment, then the system shall block live order eligibility and record the refusal reason. |
| AC-025-03 | If Polymarket market data is stale beyond the configured threshold, then the system shall block dependent live orders and persist the refusal event. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-026: Implement Alpaca Dry-Run Integration

**Story:** As an operator, I want Alpaca account and market data integration validated in dry-run mode, so that stock and ETF trading can be tested before live account submission is enabled.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 5 - External integration and notification logic  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-5-integrations`  
**Dependencies:** TASK-009, TASK-017, TASK-023

**Requirements Covered:**
- REQ-ALP-003
- REQ-ALP-004
- REQ-ALP-005
- REQ-ALP-006
- REQ-ALP-007
- REQ-ALP-015
- REQ-ALP-016
- REQ-ALP-017
- REQ-ALP-018
- REQ-DAT-001
- REQ-DAT-002
- REQ-DAT-005
- REQ-EXE-016
- REQ-EXE-017

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-026-01 | When dry-run mode is enabled and Alpaca is configured, the system shall read account and market data without submitting orders to Alpaca paper or live endpoints. |
| AC-026-02 | When Alpaca account mode is configured, the system shall validate account ID, account status, positions, open orders, and buying power before live eligibility. |
| AC-026-03 | If Alpaca data is unavailable, stale, rate-limited, or outside trading hours, then the system shall block affected live orders and record the reason. |
| AC-026-04 | If Alpaca reconciliation detects an unresolved mismatch, then the system shall block live orders for the affected model provider. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-027: Implement External LLM Providers and Cost Controls

**Story:** As an operator, I want real OpenAI and Claude provider integrations with budget enforcement, so that model comparison can run against live model APIs without cost overruns.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 5 - External integration and notification logic  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-5-integrations`  
**Dependencies:** TASK-012, TASK-014, TASK-023

**Requirements Covered:**
- REQ-LLM-001
- REQ-LLM-002
- REQ-LLM-003
- REQ-LLM-004
- REQ-LLM-005
- REQ-LLM-006
- REQ-LLM-007
- REQ-OBS-001

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-027-01 | When configured provider credentials are present, the system shall send eligible scoring requests to both OpenAI and Claude through provider adapters. |
| AC-027-02 | If a provider budget is exhausted, then the system shall stop sending requests to that provider and continue other providers. |
| AC-027-03 | When provider cost is returned or estimated, the system shall reconcile budget ledger entries and emit structured cost status. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-028: Implement Notification Service and SES Delivery Flow

**Story:** As an operator, I want daily digest and large-movement alerts with cooldowns and retries, so that I receive useful trading updates without alert noise.

**Priority:** P0  
**Estimate:** L  
**Phase:** Phase 5 - External integration and notification logic  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-5-integrations`  
**Dependencies:** TASK-010, TASK-019, TASK-020, TASK-023

**Requirements Covered:**
- REQ-NOT-001
- REQ-NOT-002
- REQ-NOT-003
- REQ-NOT-004
- REQ-NOT-005
- REQ-NOT-006
- REQ-NOT-007
- REQ-OBS-001

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-028-01 | When the digest schedule is reached, the system shall send a daily digest through SES to configured allowlisted recipients. |
| AC-028-02 | When position P&L or daily P&L crosses configured thresholds, the system shall send a large-movement alert subject to cooldown. |
| AC-028-03 | If SES delivery fails, then the system shall record the failure and retry according to configured retry policy. |
| AC-028-04 | When notification settings change in the dashboard, the system shall apply recipients, thresholds, schedules, and cooldowns on the next notification loop. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-029: Implement CloudFormation Infrastructure

**Story:** As an operator, I want AWS infrastructure defined in CloudFormation, so that development and production can run in isolated AWS environments.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 6 - AWS deployment and CI/CD  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-6-aws-cicd`  
**Dependencies:** TASK-010, TASK-025, TASK-026, TASK-027, TASK-028

**Requirements Covered:**
- REQ-DEP-002
- REQ-DEP-006
- REQ-DEP-010
- REQ-WAL-003
- REQ-DAT-003
- REQ-DAT-006
- REQ-DAT-007
- REQ-NOT-001
- REQ-OBS-002
- REQ-DB-001
- REQ-DB-002
- REQ-DB-003

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-029-01 | When CloudFormation deploys, the system shall create ECS Fargate, RDS Postgres, S3, Secrets Manager, CloudWatch, SES, IAM, and ECR resources in `us-east-1`. |
| AC-029-02 | When development and production stacks are created, the deployment shall maintain separate resources, secrets, wallets, and configuration. |
| AC-029-03 | When S3 buckets are created, the infrastructure shall retain raw snapshots for 365 days and normalized snapshots for 730 days. |
| AC-029-04 | If a task attempts to read another environment's secret path, IAM shall deny access. |
| AC-029-05 | When ECS starts the backend with `DATABASE_URL`, the runtime shall use the packaged `psycopg` driver for SQLAlchemy Postgres sessions. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-030: Implement GitHub Actions CI/CD and Migration Safety

**Story:** As an operator, I want branch-based CI/CD with tests, image builds, ECR publish, ECS deploy, and migration safety, so that merges deploy predictable environments.

**Priority:** P0  
**Estimate:** XL  
**Phase:** Phase 6 - AWS deployment and CI/CD  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-6-aws-cicd`  
**Dependencies:** TASK-007, TASK-029

**Requirements Covered:**
- REQ-DEP-003
- REQ-DEP-004
- REQ-DEP-005
- REQ-DEP-006
- REQ-DEP-010
- REQ-OBS-002

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-030-01 | When code is merged to `develop`, GitHub Actions shall deploy the application to the development environment. |
| AC-030-02 | When code is merged to `main`, GitHub Actions shall deploy the application to production automatically. |
| AC-030-03 | When CI runs, the pipeline shall run tests before building or deploying containers. |
| AC-030-04 | If a migration is destructive or contract-phase, then CI shall reject the automatic deploy and require an expand/contract split. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests
- [x] Code annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-031: Write Documentation, Source References, and Runbooks

**Story:** As a developer and operator, I want setup docs, deployment docs, source references, live checklist, and operational runbooks, so that the system can be tested, deployed, and recovered safely.

**Priority:** P1  
**Estimate:** L  
**Phase:** Phase 7 - Production readiness and runbooks  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-7-readiness`  
**Dependencies:** TASK-023, TASK-024, TASK-029, TASK-030

**Requirements Covered:**
- REQ-DEP-001
- REQ-DEP-002
- REQ-DEP-003
- REQ-DEP-004
- REQ-DEP-007
- REQ-DEP-008
- REQ-DEP-009
- REQ-WAL-001
- REQ-WAL-002
- REQ-WAL-003
- REQ-WAL-004
- REQ-WAL-006
- REQ-EXE-001
- REQ-EXE-014
- REQ-EXE-017
- REQ-OBS-005

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-031-01 | When a developer follows local development docs, the system shall run locally with Docker and gitignored `.env` files. |
| AC-031-02 | When Codex web setup docs are followed, the environment shall install dependencies and run tests without production trading secrets. |
| AC-031-03 | When an operator prepares live trading, the live checklist shall require wallet/account setup, dry-run verification, venue flags, risk limits, auth, SES, and kill-switch checks. |
| AC-031-04 | If a bad deploy occurs, the operations runbook shall define ECS rollback and RDS restore-point guidance. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests or docs checks
- [x] Code or docs annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-032: Complete Traceability and Release Readiness Verification

**Story:** As a project owner, I want final traceability and readiness checks, so that every requirement is tied to tests, implementation, and operational guidance before live enablement.

**Priority:** P1  
**Estimate:** M  
**Phase:** Phase 7 - Production readiness and runbooks  
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-7-readiness`  
**Dependencies:** TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021, TASK-022, TASK-023, TASK-024, TASK-025, TASK-026, TASK-027, TASK-028, TASK-029, TASK-030, TASK-031, TASK-033

**Requirements Covered:**
- REQ-DEP-005
- REQ-OBS-001
- REQ-OBS-003
- REQ-OBS-004
- REQ-OBS-005
- REQ-OBS-006

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-032-01 | When traceability verification runs, the system shall show every REQ ID covered by at least one test and one implementation trace. |
| AC-032-02 | If a requirement lacks a test, implementation trace, or approved design mapping, then the system shall fail readiness verification. |
| AC-032-03 | When release readiness is reviewed, the system shall show audit, health, deployment, and live-trading safety checks as passing or explicitly deferred. |

**Definition of Done:**
- [x] All acceptance criteria passing as automated tests or traceability checks
- [x] Code or docs annotated with REQ-* traceability
- [x] No regressions in existing tests

---

### TASK-033: Add Venue-Confirmed Portfolio Performance

**Story:** As an operator, I want the main dashboard to show my actual Polymarket US and Alpaca holdings, fills, account value, and P&L by model account, so that I can see whether confirmed trades are making money.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 4 - Backend API and dashboard
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-4-dashboard`
**Dependencies:** TASK-003, TASK-008, TASK-009, TASK-020, TASK-021, TASK-024

**Requirements Covered:**
- REQ-DB-008
- REQ-UI-013
- REQ-CMP-005

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-033-01 | When venue portfolio reconciliation runs, the system shall persist sanitized balances, positions, and confirmed fills by environment, venue, provider, and account reference. |
| AC-033-02 | When the main dashboard loads, the system shall show actual account value, cash, available-to-trade balance, realized P&L, unrealized P&L, open holdings, and recent confirmed fills for each Polymarket US and Alpaca model-provider account. |
| AC-033-03 | When multiple model credentials resolve to one venue account, the system shall count the account once and retain OpenAI and Claude attribution. |
| AC-033-04 | If venue data is missing or a refresh fails, then the dashboard shall show unavailable or stale status without replacing missing money values with zero. |
| AC-033-05 | When portfolio totals are calculated, the system shall exclude submitted, unfilled, and simulated orders and keep AI and AWS costs in separate economics views. |
| AC-033-06 | When an account provides buying power, the dashboard shall use it as available to trade; otherwise it shall use venue-confirmed cash, and if neither value exists it shall show unavailable rather than zero. |

**Definition of Done:**
- [x] Portfolio, migration, API, and frontend contract tests pass
- [x] Code and design artifacts include REQ-* traceability
- [x] Development and production deployment health checks pass

---

### TASK-034: Remove Dashboard I/O Timeout Feedback Loop

**Story:** As an operator, I want dashboard reads and scanner persistence to stay responsive during scheduled ticks, so that status remains available without creating additional database load.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 7 - Production reliability
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-7-readiness`
**Dependencies:** TASK-023, TASK-029, TASK-030

**Requirements Covered:**
- REQ-DB-009
- REQ-UI-014
- REQ-DEP-011

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-034-01 | When a scanner run persists hundreds of candidates, the system shall commit the run and candidates in one transaction and roll back the complete batch on failure. |
| AC-034-02 | If realtime WebSocket setup fails, then dashboard polling shall keep at most one snapshot request active and retry after bounded backoff. |
| AC-034-03 | When the dashboard reads market data, the backend shall load only the latest indexed row for each enabled venue and reuse snapshot state instead of repeating schedule queries. |
| AC-034-04 | When CloudFormation deploys RDS, the database shall use gp3 storage. |

**Definition of Done:**
- [ ] Backend, frontend, migration, and infrastructure tests pass
- [ ] Code and design artifacts include REQ-* traceability
- [ ] Development and production deployments pass live latency and health checks

---

### TASK-035: Deliver Event-Driven Dashboard Updates

**Story:** As an operator, I want live dashboard and portfolio changes delivered after committed state changes, so that the browser stays current without recurring database reads for every connected user.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 7 - Production reliability
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `phase-7-readiness`
**Dependencies:** TASK-005, TASK-033, TASK-034

**Requirements Covered:**
- REQ-DB-010
- REQ-UI-014
- REQ-UI-015

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-035-01 | When a dashboard-relevant Postgres transaction commits, the database shall publish a coalescible environment invalidation and scope user-owned config or preference invalidations to that username. |
| AC-035-02 | When an authorized WebSocket connects, the backend shall send one complete snapshot and shall not rebuild it again until a matching invalidation arrives. |
| AC-035-03 | While no dashboard state changes, the backend shall send lightweight heartbeats that do not query dashboard repositories. |
| AC-035-04 | When venue-confirmed portfolio data changes, the WebSocket snapshot shall update the main dashboard without a separate portfolio polling interval. |
| AC-035-05 | If the WebSocket or Postgres listener is unavailable, the browser shall use single-flight polling and retry the WebSocket with bounded backoff. |

**Definition of Done:**
- [x] Event broker, migration, WebSocket, and frontend recovery tests pass
- [x] Full backend and frontend checks pass
- [x] Code and design artifacts include REQ-* traceability

---

### TASK-036: Replace the Dashboard Primary Information Architecture

**Story:** As an operator, I want five clear dashboard destinations, so that I can reach the current decision, activity, performance, settings, and help without searching an overflow menu.

**Priority:** P0
**Estimate:** M
**Phase:** Phase 8 - Dashboard information architecture redesign
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `dashboard-redesign`
**Dependencies:** TASK-023, TASK-035

**Requirements Covered:** REQ-UI-016, REQ-UI-024

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-036-01 | While an authenticated user is in the dashboard, the primary navigation shall show Overview, Activity, Performance, Settings, and Help without a More menu. |
| AC-036-02 | At a 390 CSS-pixel viewport, all five destinations shall remain labeled and usable without page-level horizontal overflow. |
| AC-036-03 | When a user opens an existing specialist route directly, the route shall remain available and the primary navigation shall not report a false active destination. |
| AC-036-04 | When a keyboard user moves through the header, each destination shall expose visible focus and current-page state. |

**Definition of Done:**
- [x] Navigation tests, typecheck, and responsive browser checks pass
- [x] Legacy route links and direct URLs remain valid
- [x] Design handoff assets and implementation use the same route labels

---

### TASK-037: Implement the Data-Derived Overview

**Story:** As an operator, I want one current dashboard state, so that I can see whether a live trade happened, an action is required, or the system is clear.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 8 - Dashboard information architecture redesign
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `dashboard-redesign`
**Dependencies:** TASK-036

**Requirements Covered:** REQ-UI-017, REQ-UI-018, REQ-UI-019, REQ-UI-025, REQ-UI-026

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-037-01 | When the latest tick placed a non-simulated order, Overview shall render only the live-trade primary state. |
| AC-037-02 | If no latest real order exists and an actionable pipeline, setup, notification, or critical degradation blocker exists, then Overview shall render the attention state with at most three relevant recommendations. |
| AC-037-03 | If no live order or blocker exists, then Overview shall render the all-clear state without recommendations. |
| AC-037-04 | Below the primary state, Overview shall show four runtime facts, one latest result, and contextual route links without detailed records or forms. |
| AC-037-05 | Before a recommendation is applied, the dashboard shall confirm exact current and proposed values and shall expose one audited undo action after success. |

**Definition of Done:**
- [x] State precedence and recommendation tests pass
- [x] No prototype state selector is present in production code
- [x] Degraded information is consolidated and last valid data remains visible

---

### TASK-038: Implement Focused Activity and Performance Pages

**Story:** As an operator, I want activity and confirmed financial results on focused pages, so that Overview does not repeat operational or portfolio records.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 8 - Dashboard information architecture redesign
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `dashboard-redesign`
**Dependencies:** TASK-036

**Requirements Covered:** REQ-UI-013, REQ-UI-020, REQ-UI-021, REQ-CMP-004, REQ-CMP-005

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-038-01 | When Activity loads, it shall show the latest funnel, update time, and recent check log from persisted or realtime operations data. |
| AC-038-02 | When Performance loads, it shall show confirmed aggregate metrics, a per-account equity, cash, and available-to-trade table, and a by-market summary without counting simulated or unfilled orders. |
| AC-038-03 | When authoritative closed-trade outcomes are missing, Performance shall show Win rate as unavailable and shall not infer wins from raw fills. |
| AC-038-04 | When a financial metric is missing or stale, Performance shall show unavailable or stale status rather than a fabricated zero. |
| AC-038-05 | When Activity or Performance renders, it shall expose the contextual links assigned to that page while retained direct routes remain valid. |

**Definition of Done:**
- [x] Route, component, API contract, and no-duplication tests pass
- [x] Win rate remains unavailable without confirmed closed outcomes, and trade counts use venue-confirmed fills
- [x] Desktop and mobile browser checks match the handoff hierarchy

---

### TASK-040: Implement Focused Settings and Help Pages

**Story:** As an operator, I want common settings and operating help to be concise, so that I can make a routine change or understand the process without reading the full system reference.

**Priority:** P0
**Estimate:** M
**Phase:** Phase 8 - Dashboard information architecture redesign
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `dashboard-redesign`
**Dependencies:** TASK-036

**Requirements Covered:** REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-022, REQ-UI-023, REQ-NOT-006

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-040-01 | When Settings loads, common controls shall use the documented selected-venue config paths and plain-language labels while advanced settings remain available on demand. |
| AC-040-02 | When a common setting is saved, the existing typed validation, version conflict, audit, and next-loop behavior shall remain active. |
| AC-040-03 | When Settings renders real-money controls or the emergency-stop link, those controls shall be visually distinct from routine settings. |
| AC-040-04 | When Help loads without backend data, it shall still show Collect prices, Find candidates, Score, Simulate or submit, and Monitor exits in order, common questions, and a link to Overview. |
| AC-040-05 | When Settings renders, it shall expose the contextual What-if and Operations links assigned to the page while retained direct routes remain valid. |

**Definition of Done:**
- [x] Common settings path, type, validation, and conflict tests pass
- [x] Full advanced config capability remains available without dominating the initial page
- [x] Help static rendering and contextual route tests pass

---

### TASK-039: Verify and Release the Dashboard IA Redesign

**Story:** As the product owner, I want the redesigned dashboard verified in development and production, so that the GitHub issue closes with evidence instead of an unverified code change.

**Priority:** P0
**Estimate:** M
**Phase:** Phase 8 - Dashboard information architecture redesign
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `dashboard-redesign`, `release`
**Dependencies:** TASK-036, TASK-037, TASK-038, TASK-040

**Requirements Covered:** REQ-UI-016, REQ-UI-017, REQ-UI-018, REQ-UI-019, REQ-UI-020, REQ-UI-021, REQ-UI-022, REQ-UI-023, REQ-UI-024, REQ-UI-025, REQ-UI-026, REQ-DEP-002, REQ-DEP-003, REQ-DEP-004, REQ-DEP-005, REQ-DEP-006

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-039-01 | Before merge, the repository shall pass frontend typecheck, dashboard tests including all mapped contextual links and direct routes, accessibility audit, browser checks, infrastructure validation, deployment script tests, and required backend regression tests. |
| AC-039-02 | When the branch is ready, GitHub issue #194 shall link the implementation pull request and record test evidence. |
| AC-039-03 | When the change merges to `develop`, the development deployment shall complete and the HTTPS dashboard and ECS service shall pass health and browser verification. |
| AC-039-04 | When development evidence passes, the promotion pull request shall merge to `main`, production shall deploy, and production health and dashboard browser evidence shall pass. |

**Definition of Done:**
- [x] Traceability matrix maps every redesign requirement to code and evidence
- [x] Development and production deployment evidence is attached to issue #194
- [x] Issue #194 is closed only after the production requirement audit passes

---

### TASK-041: Add Funding Domain, Config, Calendar, and Return Math

**Story:** As an operator, I want validated funding schedules and deterministic calculations, so that recurring expectations and adjusted returns use one safe contract.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`
**Dependencies:** TASK-005, TASK-033

**Requirements Covered:** REQ-FND-005, REQ-FND-006, REQ-FND-007, REQ-FND-011, REQ-FND-012, REQ-FND-019, REQ-FND-020

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-041-01 | When the default config loads, the system shall include an empty funding schedule list, direct transfers disabled, funding emergency stop inactive, and both direct-transfer limits set to `0.00`. |
| AC-041-02 | When an authorized operator saves funding settings, the system shall validate one complete funding object, reject duplicate or incomplete schedules and direct Polymarket mode, create one owner-specific config version, and audit username, complete old and new values, environment, timestamp, and IP address. |
| AC-041-03 | When weekly or monthly due time is calculated, the system shall use 09:00 `America/New_York`, handle daylight saving, use month end for a missing day, and move weekends or federal holidays forward. |
| AC-041-04 | When a funding occurrence key is built twice from the same normalized inputs, the system shall return the same key; when any identity input changes, it shall return a different key. |
| AC-041-05 | When completed cash flows occur inside a valid period, the system shall calculate adjusted P&L and Modified Dietz with fixed precision; if the denominator is non-positive or boundary snapshots are stale, percentage return shall be unavailable. |
| AC-041-06 | When a low-balance gap is calculated, the system shall use `max(0, target - confirmed buying power)` and keep zero-limit handling as a refusal rather than a zero occurrence. |

**Definition of Done:**
- [ ] Funding domain and config tests pass
- [ ] Calendar, idempotency, amount, and return-math tests pass
- [ ] Code annotations trace to each mapped REQ-FND ID

---

### TASK-042: Add Funding Persistence and Concurrency Controls

**Story:** As an operator, I want funding activity and occurrences stored with database constraints, so that retries, concurrent workers, and restarts cannot duplicate cash flows or transfer attempts.

**Priority:** P0
**Estimate:** XL
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`, `database`
**Dependencies:** TASK-003, TASK-041

**Requirements Covered:** REQ-FND-002, REQ-FND-003, REQ-FND-004, REQ-FND-007, REQ-FND-008, REQ-FND-009, REQ-FND-014, REQ-FND-015, REQ-FND-016, REQ-FND-017

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-042-01 | When migrations run, the system shall create cash-flow, occurrence, sync-state, and funding-alert outbox tables with required foreign keys, checks, unique constraints, partial pending-slot uniqueness, and query indexes. |
| AC-042-02 | When the same venue transaction is upserted through multiple provider credentials, the system shall store one cash flow, merge provider attribution, reject stale state regressions, and retain no raw payload. |
| AC-042-03 | When the same deterministic occurrence is materialized concurrently, the system shall store one occurrence and return the persisted record. |
| AC-042-04 | When reconciliation matches a cash flow or changes an occurrence state concurrently, compare-and-set operations shall preserve one match and shall not regress a terminal state. |
| AC-042-05 | When a direct occurrence is claimed, one short account-scoped transaction shall recheck current controls, reserve the pending slot and monthly amount, set the request fingerprint and `post_attempted_at` only when null, and commit before any network call. |
| AC-042-06 | When a failure or recovery transition is enqueued more than once, the system shall retain one logical outbox event while allowing bounded delivery retries. |
| AC-042-07 | When funding records age, the application shall not delete them unless a later archive policy is configured. |

**Definition of Done:**
- [ ] Migration and repository tests pass on in-memory and Postgres-backed paths where supported
- [ ] Concurrency, compare-and-set, and one-claim tests pass
- [ ] Schema contains no raw bank, credential, account-number, routing-number, or relationship-ID columns

---

### TASK-043: Reconcile Bounded Venue Funding Activity

**Story:** As an operator, I want venue-confirmed deposits and withdrawals normalized with coverage state, so that funding history is accurate and an API outage cannot create a false missing alert.

**Priority:** P0
**Estimate:** XL
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`, `venue-adapters`
**Dependencies:** TASK-033, TASK-042

**Requirements Covered:** REQ-FND-001, REQ-FND-002, REQ-FND-003, REQ-FND-004, REQ-FND-008, REQ-FND-020

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-043-01 | When Alpaca account activity is read, the system shall paginate CSD, CSW, and supported TRANS records, treat CSD and CSW as completed, normalize date-only activity at 09:00 Eastern, and persist only allowlisted fields. |
| AC-043-02 | When Polymarket US portfolio activity is read, the system shall normalize documented deposit and withdrawal activity and shall expose no funding-write method. |
| AC-043-03 | When a venue account has more history than one tick budget, the system shall sync the current head, persist its head and backfill cursors, continue historical backfill later, and keep each request bounded. |
| AC-043-04 | When current-head pagination reaches the previous head transaction, the system shall advance `coverage_through_at`; if it fails or remains incomplete, it shall not claim current coverage. |
| AC-043-05 | When the source contains an ambiguous transfer direction or a new bank field, the system shall skip or ignore the unsupported field with a safe warning and shall not store or log the raw payload. |
| AC-043-06 | When source code and schemas are inspected, they shall contain no Plaid integration, raw bank fields, or Polymarket funding-write path. |

**Definition of Done:**
- [ ] Alpaca and Polymarket mocked activity contract tests pass
- [ ] Pagination, watermark, deduplication, stale-regression, and privacy tests pass
- [ ] Existing venue portfolio regression tests pass

---

### TASK-044: Implement Funding Materialization, Reconciliation, Alerts, and Runtime Wiring

**Story:** As an operator, I want schedules evaluated and reconciled after portfolio refresh, so that expected deposits, missed deposits, and recovery alerts are dependable across restarts.

**Priority:** P0
**Estimate:** XL
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`, `scheduler`
**Dependencies:** TASK-020, TASK-028, TASK-041, TASK-042, TASK-043

**Requirements Covered:** REQ-FND-005, REQ-FND-006, REQ-FND-007, REQ-FND-008, REQ-FND-009, REQ-FND-016, REQ-FND-017, REQ-FND-018

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-044-01 | When the funding runtime tick starts, it shall acquire a session-scoped nonblocking environment lock, skip overlap, avoid a long database transaction across network calls, and release the lock in `finally`. |
| AC-044-02 | When a weekly or monthly occurrence is due, the system shall materialize it once even after worker downtime or a failed portfolio refresh. |
| AC-044-03 | When a confirmed account crosses below its configured target, the system shall create one low-balance episode and shall not rearm it until a later fresh snapshot is at or above target. |
| AC-044-04 | When a completed cash flow is available, the system shall match it one-to-one by account, direction, effective window, and expected amount or claimed submitted amount within `0.01`. |
| AC-044-05 | If the matching deadline passes without a cash flow, the system shall mark missing only after successful activity coverage extends past the deadline and shall enqueue one failure alert. |
| AC-044-06 | If a late completed cash flow matches a missing occurrence, the system shall mark matched and enqueue one recovery alert. |
| AC-044-07 | When startup finds a reserved occurrence with `post_attempted_at`, it shall move the occurrence to unknown and reconcile only. |
| AC-044-08 | When one account refresh fails, the system shall continue other accounts, run fixed cadences, gate low balance on freshness, and record safe funding counts and coverage in heartbeat metadata. |
| AC-044-09 | While the kill switch or funding emergency stop is active, the runtime shall continue read-only activity reconciliation, missing detection, and recovery alerts. |

**Definition of Done:**
- [ ] Materialization, episode, matching, deadline, alert, and restart tests pass
- [ ] Scheduler lock, failure-isolation, freshness, and heartbeat integration tests pass
- [ ] SES tests prove one logical transition with bounded transport retry

---

### TASK-045: Implement Disabled-by-Default Alpaca Direct Funding

**Story:** As an operator, I want direct incoming Alpaca ACH support behind strict controls, so that it can be enabled later without storing bank data or risking duplicate transfers.

**Priority:** P0
**Estimate:** XL
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`, `alpaca`, `safety`
**Dependencies:** TASK-010, TASK-042, TASK-044

**Requirements Covered:** REQ-FND-006, REQ-FND-013, REQ-FND-014, REQ-FND-015, REQ-FND-016, REQ-FND-017, REQ-FND-018, REQ-FND-020

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-045-01 | When direct funding is disabled, either limit is zero, or the amount is non-positive, the system shall persist a refusal before calling the adapter. |
| AC-045-02 | When the global kill switch or funding emergency stop is active, the system shall refuse before the adapter call while leaving read reconciliation active. |
| AC-045-03 | When Broker credentials, account ID, or approved relationship ID are missing, persistence is unavailable, or the current provider account does not match the occurrence and secret-resolved Broker account, the system shall refuse before the adapter call. |
| AC-045-04 | When a fixed weekly or monthly amount exceeds a per-transfer or remaining monthly cap, the system shall refuse the full transfer; when a low-balance refill fits positive caps only after reduction, it shall submit the capped amount and retain both expected and submitted values. |
| AC-045-05 | When another reserved, submitted, or unknown transfer exists for the account, the system shall refuse a second pending transfer. |
| AC-045-06 | When the originating schedule was removed, disabled, changed, moved to another owner, or resolves to another account, the system shall refuse the occurrence before claim. |
| AC-045-07 | When a claim succeeds, the committed `post_attempted_at` shall permit at most one Broker API POST; a retry shall return or reconcile persisted state without another POST. |
| AC-045-08 | If the Broker response is ambiguous, the system shall retain the pending slot and monthly reservation, find candidates conservatively from the account transfer list, and remain unknown for zero or multiple candidates. |
| AC-045-09 | If Alpaca rejects, returns, or fails the transfer, the system shall persist a terminal status, release the failed reservation, alert once, and never auto-retry. |
| AC-045-10 | When direct funding is configured for Polymarket or Plaid fields are supplied, validation shall reject the configuration because neither write path is supported. |
| AC-045-11 | When a direct occurrence has withdrawal or any non-deposit direction, the system shall refuse it before the adapter call because direct mode supports incoming Alpaca ACH only. |
| AC-045-12 | When an allowed direct request is submitted to the mocked adapter, it shall use `/v1/accounts/{account_id}/transfers`, incoming ACH direction, the exact claimed amount, and the secret-resolved relationship ID without persisting or logging the exact account or relationship identifier. |
| AC-045-13 | When monthly capacity is checked, the account total shall include reserved, submitted, unknown, and matched direct amounts by `reserved_at` in the current `America/New_York` month, exclude released terminal reservations, and start a new total after month rollover. |

**Definition of Done:**
- [ ] Mocked Broker API adapter tests pass with no real credentials or transfers
- [ ] Every refusal case asserts zero adapter calls
- [ ] One-POST, unknown reconciliation, terminal no-retry, account routing, and secret/log privacy tests pass

---

### TASK-046: Add Funding API and Cash-Flow-Adjusted Performance

**Story:** As an operator, I want sanitized funding history and cash-flow-adjusted results, so that I can distinguish strategy returns from money added or withdrawn.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`, `api`
**Dependencies:** TASK-021, TASK-041, TASK-042, TASK-044, TASK-045

**Requirements Covered:** REQ-FND-004, REQ-FND-010, REQ-FND-011, REQ-FND-012, REQ-FND-019

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-046-01 | When an authenticated user requests funding history, the API shall return bounded cash-flow and occurrence pages with independent stable cursors and the selected interval. |
| AC-046-02 | When boundary portfolio snapshots are fresh, the API shall return per-account and eligible aggregate beginning value, ending value, completed deposits, completed withdrawals, adjusted P&L, and Modified Dietz return. |
| AC-046-03 | If either boundary snapshot is missing or stale or the weighted denominator is non-positive, the API shall return an unavailable reason rather than zero. |
| AC-046-04 | When a capped low-balance transfer is shown, the API shall expose safe expected and submitted amounts and shall match its completed cash flow to the submitted amount. |
| AC-046-05 | When API responses are serialized, they shall exclude raw account references, Broker account and relationship IDs, credentials, request fingerprints, raw payloads, bank fields, and Plaid fields by schema. |
| AC-046-06 | If the request is unauthenticated, unallowlisted, invalid, or persistence cannot produce a safe response, the API shall return the existing 401, 403, 422, or 503 envelope. |

**Definition of Done:**
- [ ] Auth, interval, valuation, pagination, aggregate, and unavailable-state tests pass
- [ ] Response schema and log-boundary privacy tests pass
- [ ] Existing portfolio and dashboard API regression tests pass

---

### TASK-047: Add Funding History and Schedule Controls to the Dashboard

**Story:** As an operator, I want funding history in Performance and schedule controls in Settings, so that I can see deposits, missed expectations, and safe recurring-funding configuration in one place.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`, `frontend`
**Dependencies:** TASK-038, TASK-040, TASK-046

**Requirements Covered:** REQ-FND-005, REQ-FND-006, REQ-FND-010, REQ-FND-011, REQ-FND-012, REQ-FND-019, REQ-FND-020

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-047-01 | When Performance loads, the dashboard shall show sanitized funding history, expected and submitted amounts, matched or missing state, venue cash-flow status, direction, venue, provider, safe account label, timestamps, alert state, and cash-flow-adjusted results. |
| AC-047-02 | When adjusted percentage return is unavailable, the dashboard shall show the reason and shall not display a fabricated zero. |
| AC-047-03 | When Settings loads, the dashboard shall support complete weekly, monthly, and low-balance schedule edits plus direct enablement, zero-based limits, and funding emergency stop through one complete-object audited save. |
| AC-047-04 | While either direct limit is zero or required Broker readiness is incomplete, the dashboard shall state that direct transfers are blocked. |
| AC-047-05 | When funding guidance renders, it shall state that bank connections stay venue-managed, Plaid is not required, Polymarket is observe-only, and exact Broker references are provisioned outside the dashboard. |
| AC-047-06 | At desktop and 390-pixel widths, funding tables and controls shall be keyboard usable, avoid color-only state, respect reduced motion, and avoid page-level horizontal scrolling. |

**Definition of Done:**
- [ ] Frontend typecheck and funding behavior tests pass
- [ ] Settings version-conflict and complete-object save tests pass
- [ ] Desktop/mobile browser and accessibility checks pass

---

### TASK-048: Configure Funding Infrastructure and Runbooks

**Story:** As an operator, I want optional secret references and clear funding runbooks, so that deployment stays safe before direct transfers are provisioned.

**Priority:** P0
**Estimate:** M
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`, `infrastructure`, `documentation`
**Dependencies:** TASK-045, TASK-047

**Requirements Covered:** REQ-FND-002, REQ-FND-013, REQ-FND-014, REQ-FND-018, REQ-FND-020

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-048-01 | When CloudFormation deploys, optional environment-separated Alpaca Broker API, account, and relationship secret references shall exist without requiring values, and direct transfers shall default disabled with both limits `0.00`. |
| AC-048-02 | If Broker secret values are absent in local, development, or production configuration, startup and health shall remain available while direct submission stays blocked with a safe readiness state. |
| AC-048-03 | When infrastructure and deployment contracts are tested, CloudFormation validation, deployment shell syntax, environment isolation, missing-secret defaults, and zero-cap defaults shall pass. |
| AC-048-04 | When the infrastructure template and runtime are inspected, they shall contain no Plaid field, raw bank field, or Polymarket funding-write resource or permission. |
| AC-048-05 | Before release, the runbook shall document venue-managed bank setup, optional Broker entitlement and secret provisioning, schedule configuration, enabling and disabling direct mode, emergency stop, unknown-transfer review, alert recovery, rollback, and the rule that no real transfer is a deployment smoke test. |

**Definition of Done:**
- [ ] CloudFormation, shell, environment-isolation, and missing-secret tests pass
- [ ] Funding operations and rollback runbooks match the implemented controls
- [ ] No Polymarket write, Plaid, raw bank, or required Broker secret resource is present

---

### TASK-049: Verify and Release Recurring Funding

**Story:** As the product owner, I want recurring funding deployed with concrete evidence, so that production observes deposits safely without enabling an unverified bank-transfer path.

**Priority:** P0
**Estimate:** L
**Phase:** Phase 9 - Recurring funding and direct-transfer controls
**Labels:** `codex-poly-bot`, `spec-driven-dev`, `funding`, `release`
**Dependencies:** TASK-041, TASK-042, TASK-043, TASK-044, TASK-045, TASK-046, TASK-047, TASK-048

**Requirements Covered:** REQ-FND-001 through REQ-FND-020

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|-------|----------------|
| AC-049-01 | Before merge, the release shall create or identify a recurring-funding tracking issue and link the implementation pull request and local verification evidence. |
| AC-049-02 | Before merge, the branch shall rebase on current `develop` and the system shall pass funding tests, full backend regression, frontend typecheck and behavior tests, CloudFormation validation, deployment shell syntax, secret-boundary checks, and traceability verification. |
| AC-049-03 | When the feature merges to `develop`, development migrations, CloudFormation, ECS, HTTPS health, authenticated sanitized funding API, and browser checks shall pass, and the final GitHub Actions run URL and status shall be recorded. |
| AC-049-04 | Before development promotion, authenticated funding readback shall show direct transfers disabled and both limits `0.00`, and a CloudWatch adapter query shall show zero Broker POST events during the release window. |
| AC-049-05 | When development evidence passes, the promotion pull request shall merge to `main`; production migration, stack, ECS, HTTPS health, TLS, authenticated funding API, dashboard, SES, and ACM evidence shall pass, and the final GitHub Actions run URL and status shall be recorded. |
| AC-049-06 | Before the release is complete, production funding readback shall show direct transfers disabled and both limits `0.00`, CloudWatch shall show zero Broker POST events during the release window, and no real bank transfer shall have been used as a smoke test. |
| AC-049-07 | When release evidence is complete, the tracking issue shall contain requirement, test, pull request, deployment, funding-readback, and no-POST evidence before it is closed. |

**Definition of Done:**
- [ ] Every REQ-FND requirement maps to passing test and implementation evidence
- [ ] Development and production deployment evidence is attached to the named tracking issue
- [ ] Direct transfers remain disabled with zero limits and no real transfer is sent
