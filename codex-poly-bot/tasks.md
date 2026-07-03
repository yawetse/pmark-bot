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
**Dependencies:** TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021, TASK-022, TASK-023, TASK-024, TASK-025, TASK-026, TASK-027, TASK-028, TASK-029, TASK-030, TASK-031

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
