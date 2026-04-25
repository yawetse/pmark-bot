# claude-poly-bot — Low-Level Design

**Scope:** Per-module LLDs. Organized by batch per HLD module map.
**Traces to:** `requirements.md` + `design-hld.md`.

**Conventions applied across all LLDs:**
- Protocols for cross-module ports (`typing.Protocol`, `runtime_checkable`); plain async functions for internal helpers.
- `mypy --strict` passes; Pydantic v2 for all I/O-boundary data contracts; `Decimal` for money.
- Exceptions for errors; domain-specific exception types defined per module.
- Medium defensive depth: public functions validate preconditions; private functions trust.
- Tier 1 config fetched through `ConfigStore` port per use; Tier 2 at startup; Tier 3 module-level constants.

---

## Batch 1 — Core Domain (`domain/`)

8 modules. Pure logic, no I/O. Importable from everywhere.

**Dependency order within batch:** `models` → `clock` → `protocols` → `scoring`, `kelly`, `consensus`, `risk`, `thesis`.

---

### 1.1 `domain/models.py`

**File:** `python/claude_poly_bot/domain/models.py`
**Responsibility:** Pydantic v2 domain models and enums used across the whole system. Pure data contracts; no behavior.
**Requirements Covered:** REQ-BRN-006, REQ-BRN-007, REQ-SCAN-005, REQ-EXE-009, REQ-EXIT-009, REQ-DATA-007, REQ-CFG-001, REQ-LLM-001.
**Dependencies:** `pydantic`, `decimal.Decimal`, `datetime`, `enum`.
**Depended On By:** every other module in the package.

#### 1.1.1 Public Interface

**Enums:**

```python
class Bot(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"

class VenueName(str, Enum):
    POLYMARKET = "polymarket"
    ALPACA = "alpaca"

class Geo(str, Enum):
    US = "us"
    INTERNATIONAL = "international"

class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

class Verdict(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SKIP = "SKIP"

class CheckType(str, Enum):
    BASE_RATE = "base_rate"
    NEWS = "news"
    WHALE = "whale"               # Polymarket only
    UNUSUAL_VOLUME = "unusual_volume"  # Alpaca only
    DISPOSITION = "disposition"

class SubAgent(str, Enum):
    ARBITRAGE = "arbitrage"
    CONVERGENCE = "convergence"
    WHALE_COPY = "whale_copy"     # Polymarket
    FLOW_COPY = "flow_copy"       # Alpaca

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    LOST = "LOST"                 # container restart orphan

class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    ORPHANED = "ORPHANED"         # in DB, missing on venue
    ADOPTED = "ADOPTED"           # on venue, was missing in DB

class ExitReason(str, Enum):
    TARGET_HIT = "TARGET_HIT"
    VOLUME_EXIT = "VOLUME_EXIT"
    STALE_THESIS = "STALE_THESIS"
    STOP_LOSS = "STOP_LOSS"       # Alpaca only
    HORIZON_EXIT = "HORIZON_EXIT" # Alpaca only
    EOD_FLATTEN = "EOD_FLATTEN"   # Alpaca: 15:55 ET
    MARKET_RESOLVED = "MARKET_RESOLVED"  # Polymarket only
    MANUAL = "MANUAL"

class HaltReason(str, Enum):
    DAILY_DRAWDOWN = "DAILY_DRAWDOWN"
    LLM_SPEND_CAP = "LLM_SPEND_CAP"
    LLM_SUSTAINED_ERRORS = "LLM_SUSTAINED_ERRORS"
    OPERATOR_TOGGLE = "OPERATOR_TOGGLE"
```

**Money/price aliases:**

```python
Money = Annotated[Decimal, Field(ge=0, decimal_places=8, max_digits=24)]
Probability = Annotated[Decimal, Field(ge=0, le=1, decimal_places=8)]
Price = Annotated[Decimal, Field(ge=0, decimal_places=8)]
```

**Core models (Pydantic v2 `BaseModel`, frozen=True for immutability):**

- **`Market`** (base) — `venue: VenueName`, `external_id: str`, `name: str`, `geo: Geo | None`, `created_at: datetime`.
- **`PolymarketMarket(Market)`** — `question: str`, `resolution_rules: str`, `resolution_time: datetime`, `outcomes: list[str]`, `token_ids: dict[str, str]` (mapping outcome → CLOB token_id).
- **`AlpacaMarket(Market)`** — `ticker: str`, `sector: str | None`, `last_earnings_date: date | None`, `shares_outstanding: int | None`, `is_etf: bool`.
- **`Book`** — `venue: VenueName`, `market_id: str`, `bids: list[tuple[Price, int]]`, `asks: list[tuple[Price, int]]`, `midpoint: Price`, `timestamp: datetime`.
- **`PolymarketScoreFields`** (BaseModel) — `gap: Decimal`, `depth: Money`, `hours_to_resolution: Decimal`.
- **`AlpacaScoreFields`** (BaseModel) — `relative_volume: Decimal`, `price_momentum: Decimal`, `dollar_volume: Money`, `last_price: Price`.
- **`ScanScore`** — `market_id: str`, `venue: VenueName`, `fields: PolymarketScoreFields | AlpacaScoreFields` (discriminated union via venue field), `accepted: bool`, `rejection_reason: str | None`.
- **`CheckResult`** — `bot: Bot`, `venue: VenueName`, `market_id: str`, `check_type: CheckType`, `sub_agent: SubAgent | None`, `verdict: Verdict`, `confidence: Probability`, `p_win: Probability`, `rationale: str`, `model_id: str`, `tokens_in: int`, `tokens_out: int`, `tokens_cached: int`, `cost_usd: Money`, `latency_ms: int`, `web_search_used: bool`, `raw_response: dict`, `error: str | None`, `correlation_id: UUID` (= scan_correlation_id + bot).
- **`Thesis`** — `id: UUID`, `bot: Bot`, `venue: VenueName`, `market_id: str`, `verdict: Verdict`, `p_win: Probability`, `confidence: Probability`, `size_multiplier: Literal["FULL","HALF","SKIP"]` (from sub-agent consensus), `target_price: Price | None` (Alpaca only), `stop_price: Price | None` (Alpaca only), `horizon_hours: int | None` (Alpaca only), `check_results: list[CheckResult]`, `scan_correlation_id: UUID`, `decision_correlation_id: UUID` (= scan_correlation_id derived deterministically with bot, per DD-019), `created_at: datetime`.
- **`OrderSpec`** — `client_order_id: UUID`, `bot: Bot`, `venue: VenueName`, `market_id: str`, `side: Side`, `size: Money`, `limit_price: Price`, `ttl_seconds: int`, `thesis_id: UUID | None`, `is_entry: bool`, `parent_position_id: UUID | None` (for exits).
- **`Order`** — all of `OrderSpec` + `venue_order_id: str | None`, `status: OrderStatus`, `filled_size: Money`, `filled_avg_price: Price | None`, `submitted_at: datetime | None`, `last_checked_at: datetime`, `error: str | None`.
- **`Position`** — `id: UUID`, `bot: Bot`, `venue: VenueName`, `market_id: str`, `side: Side`, `size: Money`, `entry_price: Price`, `entry_order_id: UUID`, `exit_order_id: UUID | None`, `status: PositionStatus`, `opened_at: datetime`, `closed_at: datetime | None`, `exit_reason: ExitReason | None`, `realized_pnl: Money | None`, `thesis_id: UUID`, `target_price: Price | None`, `stop_price: Price | None`, `horizon_ends_at: datetime | None`.
- **`Trade`** — `id: UUID`, `position_id: UUID`, `order_id: UUID`, `bot: Bot`, `venue: VenueName`, `size: Money`, `price: Price`, `side: Side`, `filled_at: datetime`, `fees: Money`.
- **`Candidate`** — `scan_correlation_id: UUID`, `venue: VenueName`, `market_id: str`, `market_snapshot: PolymarketMarket | AlpacaMarket`, `book_snapshot: Book | None`, `scan_score: ScanScore`, `created_at: datetime`.
- **`CandidateClaim`** — `scan_correlation_id: UUID`, `bot: Bot`, `status: Literal["new","processing","done","error"]`, `decision_correlation_id: UUID`, `claimed_at: datetime | None`, `completed_at: datetime | None`, `error: str | None`.
- **`Balance`** — `bot: Bot`, `venue: VenueName`, `as_of: datetime`, `usdc: Money | None` (Polymarket), `matic: Money | None` (Polymarket), `equity: Money | None` (Alpaca), `buying_power: Money | None` (Alpaca), `day_trade_count: int | None` (Alpaca).
- **`BankrollSnapshot`** — `bot: Bot`, `venue: VenueName`, `as_of: datetime`, `starting_bankroll: Money`, `current_bankroll: Money`, `day_start_bankroll: Money`, `daily_pnl_realized: Money`, `daily_pnl_unrealized: Money`, `open_positions: int`.
- **`RiskHalt`** — `id: UUID`, `bot: Bot`, `venue: VenueName | None` (None = all venues for bot), `reason: HaltReason`, `triggered_at: datetime`, `resumes_at: datetime | None`, `metrics_snapshot: dict`.
- **`TargetWallet`** — `address: str`, `total_trades: int`, `win_rate: Probability`, `total_pnl: Money`, `refreshed_at: datetime`.
- **`ConfigValue`** — `bot: Bot | None` (None = global), `venue: VenueName | None`, `field: str`, `value: Any` (validated by schema), `updated_at: datetime`, `updated_by: str`.
- **`ConfigAudit`** — `id: UUID`, `bot: Bot | None`, `venue: VenueName | None`, `field: str`, `old_value: Any`, `new_value: Any`, `actor_email: str`, `changed_at: datetime`, `confirmation_checksum: str`.
- **`AuthEvent`** — `id: UUID`, `event: Literal["login_success","login_denied","logout"]`, `email: str | None`, `ip: str | None`, `user_agent: str | None`, `at: datetime`.
- **`MarketScanRun`** — `scan_correlation_id: UUID`, `venue: VenueName`, `started_at: datetime`, `ended_at: datetime`, `fetched: int`, `accepted: int`, `rejected: int`, `error: str | None`.

#### 1.1.2 Internal Implementation Details

- All models `frozen=True, strict=True, extra='forbid'` in `model_config`.
- `Decimal` fields serialize as JSON strings (never floats).
- Timestamps are timezone-aware `datetime` — naive datetimes are a validation error.
- `UUID` generated via `uuid.uuid4()` when not supplied; fields typed `UUID`.

#### 1.1.3 Data Structures

(Same as Public Interface — this module IS the data structures.)

#### 1.1.4 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | `Money` field receives a float | Validation error (strict mode) | REQ-EXE-001 (money precision) |
| 2 | Naive datetime assigned to timezone-aware field | ValidationError | DD-021 clock discipline |
| 3 | `Probability` outside [0, 1] | ValidationError | REQ-BRN-006 |
| 4 | `Thesis` has `venue=alpaca` but no `target_price`/`stop_price`/`horizon_hours` | ValidationError via model validator | REQ-BRN-007 |
| 5 | `OrderSpec` `is_entry=False` but `parent_position_id=None` | ValidationError | REQ-EXE-015 |
| 6 | `Order.status=FILLED` but `filled_avg_price=None` | ValidationError | Invariants |

#### 1.1.5 Error Handling

Raises: `pydantic.ValidationError` on any invalid model construction. Not a recoverable condition — indicates programmer error. Logged at ERROR; process continues (caller's responsibility to catch and handle).

#### 1.1.6 Non-Functional Requirements

| NFR | Requirement | Addressed by |
|---|---|---|
| Testability | Every model round-trips via `model_dump()` / `model_validate()` | Pydantic v2 guarantees |
| Data Integrity | No float money; strict mode; timezone awareness | Type aliases + model_config |
| Performance | Model validation overhead trivial at our volumes | N/A |

#### 1.1.7 Dependencies & Integration Points

Imports: stdlib (`enum`, `datetime`, `uuid`, `decimal`), `pydantic`. No other project imports.

---

### 1.2 `domain/clock.py`

**File:** `python/claude_poly_bot/domain/clock.py`
**Responsibility:** Clock port abstraction — every time-sensitive code path takes a `Clock`.
**Requirements Covered:** DD-021 (HLD), R19, every REQ using explicit time (REQ-RISK-001, REQ-EXIT-004, REQ-EXIT-006, REQ-EXIT-014, REQ-SCAN-001, REQ-EXIT-001).
**Dependencies:** stdlib only.

#### 1.2.1 Public Interface

```python
@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...          # timezone-aware UTC
    def et_now(self) -> datetime: ...       # timezone-aware America/New_York

class RealClock:
    def now(self) -> datetime: return datetime.now(timezone.utc)
    def et_now(self) -> datetime: return datetime.now(ZoneInfo("America/New_York"))

class FakeClock:
    def __init__(self, at: datetime): self._now = at.astimezone(timezone.utc)
    def now(self) -> datetime: return self._now
    def et_now(self) -> datetime: return self._now.astimezone(ZoneInfo("America/New_York"))
    def advance(self, delta: timedelta) -> None: self._now = self._now + delta
    def set(self, at: datetime) -> None: self._now = at.astimezone(timezone.utc)

# Pure helpers:
def utc_day_start(t: datetime) -> datetime
def next_utc_day(t: datetime) -> datetime
def is_us_equity_market_open(et_now: datetime, *, holidays: set[date]) -> bool
def eod_flatten_threshold(et_now: datetime) -> bool  # True if past 15:55 ET on trading day
```

#### 1.2.2 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | `FakeClock` receives naive datetime | ValueError — constructor asserts timezone | DD-021 |
| 2 | `utc_day_start(t)` where `t` is 00:00:00 UTC exactly | Returns `t` unchanged (idempotent) | REQ-RISK-001 |
| 3 | `is_us_equity_market_open` called 09:29:59 ET on a trading day | Returns `False` | REQ-ALPC-006 |
| 4 | `is_us_equity_market_open` called 16:00:00 ET exactly | Returns `False` (half-open interval `[09:30, 16:00)`) | REQ-ALPC-006 |
| 5 | Weekend/holiday | Returns `False` | REQ-ALPC-006 |
| 6 | `eod_flatten_threshold` at 15:54:59 ET | Returns `False` | REQ-EXIT-014 |
| 7 | `eod_flatten_threshold` at 15:55:00 ET on trading day | Returns `True` | REQ-EXIT-014 |

#### 1.2.3 Error Handling

Raises `ValueError` on naive datetime (defensive-depth: module boundary). Otherwise pure.

#### 1.2.4 Non-Functional Requirements

| NFR | Requirement | Addressed by |
|---|---|---|
| Testability | Time travel via `FakeClock.advance()` / `.set()` | Explicit port |
| Data Integrity | No naive datetimes ever | Constructor assertion |

#### 1.2.5 Dependencies

Imports: `datetime`, `zoneinfo`, `typing`.

---

### 1.3 `domain/protocols.py`

**File:** `python/claude_poly_bot/domain/protocols.py`
**Responsibility:** All cross-module port definitions (`typing.Protocol`). Defines the ports; adapters in `venues/`, `llm/`, `storage/`, `observability/`, `wallet/` implement.
**Requirements Covered:** REQ-VEN-001..008, REQ-LLM-001..010, REQ-CFG-001..013, REQ-OBS-*.
**Dependencies:** `domain/models.py`, `domain/clock.py`.

#### 1.3.1 Public Interface

**`Venue` Protocol** (REQ-VEN-001):

```python
@runtime_checkable
class Venue(Protocol):
    name: VenueName

    async def list_active_markets(self, *, geo: Geo | None = None) -> list[Market]: ...
    async def get_market_data(self, market_id: str) -> Market: ...
    async def get_book(self, market_id: str) -> Book: ...
    async def place_order(self, spec: OrderSpec) -> Order: ...
    async def cancel_order(self, client_order_id: UUID) -> Order: ...
    async def get_order(self, client_order_id: UUID) -> Order | None: ...
    async def get_positions(self, bot: Bot) -> list[Position]: ...
    async def get_balance(self, bot: Bot) -> Balance: ...
    async def subscribe_to_updates(self, market_ids: list[str]) -> AsyncIterator[BookUpdate]: ...
    async def is_market_open(self) -> bool: ...
    async def health_check(self) -> HealthStatus: ...
```

**`Strategist` Protocol** (REQ-LLM-001):

```python
@runtime_checkable
class Strategist(Protocol):
    bot: Bot

    async def evaluate(
        self,
        check_type: CheckType,
        venue: VenueName,
        market: Market,
        context: StrategistContext,
        *,
        sub_agent: SubAgent | None = None,
        web_search: bool = False,
        model_id: str | None = None,
    ) -> CheckResult: ...

class StrategistContext(BaseModel):
    book: Book | None
    scan_score: ScanScore
    target_wallets_hits: int | None = None      # Polymarket whale check input
    unusual_volume: Decimal | None = None        # Alpaca unusual_volume input
    recent_news: list[NewsSnippet] = []
    historical_analogs: list[str] = []
```

**Storage/Repo Protocols** (one per logical entity — partial list):

```python
class ConfigRepo(Protocol):
    async def get(self, bot: Bot | None, venue: VenueName | None, field: str) -> Any: ...
    async def get_all(self, *, bot: Bot | None = None, venue: VenueName | None = None) -> dict[str, Any]: ...
    async def set(self, bot: Bot | None, venue: VenueName | None, field: str, value: Any, *, actor_email: str) -> None: ...
    async def audit_log(self, *, since: datetime | None = None, limit: int = 100) -> list[ConfigAudit]: ...

class CandidateRepo(Protocol):
    async def publish(self, candidate: Candidate) -> None: ...
    async def claim_next(self, bot: Bot, *, limit: int = 1) -> list[tuple[Candidate, CandidateClaim]]: ...
    async def complete(self, scan_correlation_id: UUID, bot: Bot) -> None: ...
    async def fail(self, scan_correlation_id: UUID, bot: Bot, error: str) -> None: ...
    async def queue_depth(self, bot: Bot) -> int: ...

class PositionRepo(Protocol):
    async def create(self, position: Position) -> Position: ...
    async def get(self, id: UUID) -> Position | None: ...
    async def list_open(self, bot: Bot, venue: VenueName | None = None) -> list[Position]: ...
    async def transition(self, id: UUID, *, to: PositionStatus, **fields) -> Position: ...
    async def close(self, id: UUID, exit_reason: ExitReason, realized_pnl: Money, at: datetime) -> Position: ...

class OrderRepo(Protocol):
    async def insert_pending(self, spec: OrderSpec) -> Order: ...
    async def mark_submitted(self, client_order_id: UUID, venue_order_id: str, at: datetime) -> Order: ...
    async def update_status(self, client_order_id: UUID, **fields) -> Order: ...
    async def list_pending(self, bot: Bot) -> list[Order]: ...
    async def get(self, client_order_id: UUID) -> Order | None: ...

class DecisionRepo(Protocol):
    async def record(self, result: CheckResult) -> None: ...
    async def list_for_thesis(self, thesis_id: UUID) -> list[CheckResult]: ...
    async def list_for_candidate(self, scan_correlation_id: UUID, bot: Bot) -> list[CheckResult]: ...

class ThesisRepo(Protocol):
    async def save(self, thesis: Thesis) -> None: ...
    async def get(self, id: UUID) -> Thesis | None: ...

class TradeRepo(Protocol):
    async def record(self, trade: Trade) -> None: ...
    async def list_for_position(self, position_id: UUID) -> list[Trade]: ...

class TargetWalletRepo(Protocol):
    async def upsert_all(self, wallets: list[TargetWallet]) -> None: ...
    async def list_current(self) -> list[TargetWallet]: ...

class RiskHaltRepo(Protocol):
    async def is_halted(self, bot: Bot, venue: VenueName | None = None) -> RiskHalt | None: ...
    async def halt(self, bot: Bot, venue: VenueName | None, reason: HaltReason, resumes_at: datetime, metrics: dict) -> RiskHalt: ...
    async def lift_expired(self, now: datetime) -> int: ...

class AuditRepo(Protocol):
    async def record_config_change(self, audit: ConfigAudit) -> None: ...
    async def record_auth_event(self, event: AuthEvent) -> None: ...

class BankrollRepo(Protocol):
    async def snapshot(self, bot: Bot, venue: VenueName) -> BankrollSnapshot: ...
    async def reset_daily(self, at: datetime) -> None: ...     # called at 00:00 UTC
```

**Observability Protocols:**

```python
class AlertSink(Protocol):
    async def emit(self, alert_type: str, *, bot: Bot | None, venue: VenueName | None, message: str, details: dict) -> None: ...

class MetricsSink(Protocol):
    def incr(self, name: str, *, by: int = 1, tags: dict[str, str] = {}) -> None: ...
    def gauge(self, name: str, value: Decimal, *, tags: dict[str, str] = {}) -> None: ...
    def timing(self, name: str, ms: float, *, tags: dict[str, str] = {}) -> None: ...
```

**Secret/S3 Protocols:**

```python
class SecretStore(Protocol):
    async def get(self, name: str) -> str: ...

class S3Store(Protocol):
    async def put_parquet(self, key: str, body: bytes) -> None: ...
    async def get_parquet(self, key: str) -> bytes: ...
    async def list_prefix(self, prefix: str) -> list[str]: ...
```

#### 1.3.2 Edge Cases & Boundary Conditions

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | `Venue.place_order` called with `spec.is_entry=False` and `parent_position_id=None` | Adapter raises `InvalidOrderSpecError` (defensive-depth boundary) | REQ-EXE-015 |
| 2 | `CandidateRepo.claim_next` called when no candidates exist | Returns empty list | REQ-SCAN-005 |
| 3 | `RiskHaltRepo.is_halted` with `venue=None` | Returns halt that matches `venue IS NULL` (bot-wide) OR any venue-specific halt for that bot | REQ-RISK-004 |
| 4 | `OrderRepo.insert_pending` with duplicate `client_order_id` | Raises `DuplicateClientOrderIdError` | DD-020 idempotency |

#### 1.3.3 Error Handling

Each protocol defines its exception hierarchy in a sibling `exceptions.py`:
- `VenueError` → `VenueUnreachableError`, `InvalidOrderSpecError`, `OrderRejectedError`, `InsufficientBalanceError`
- `StrategistError` → `StrategistUnreachableError`, `MalformedResponseError`, `RateLimitExhaustedError`
- `RepoError` → `DuplicateClientOrderIdError`, `InvariantViolationError`

#### 1.3.4 Non-Functional Requirements

| NFR | Requirement | Addressed by |
|---|---|---|
| Testability | All ports runtime-checkable, mockable | `Protocol` with `@runtime_checkable` |
| Extensibility | New venue = new `Venue` impl; new LLM = new `Strategist` impl | Port-first design |
| Correctness | Exception taxonomy makes failure modes explicit | Per-protocol exception types |

---

### 1.4 `domain/scoring.py`

**File:** `python/claude_poly_bot/domain/scoring.py`
**Responsibility:** Pure scoring functions for scanner input. No I/O.
**Requirements Covered:** REQ-SCAN-002, REQ-SCAN-003, REQ-SCAN-010, REQ-SCAN-011.
**Dependencies:** `domain/models.py`.

#### 1.4.1 Public Interface

```python
def score_polymarket_market(
    market: PolymarketMarket,
    book: Book,
    *,
    estimated_probability: Probability,
    now: datetime,
) -> ScanScore: ...

def score_alpaca_instrument(
    market: AlpacaMarket,
    last_price: Price,
    volume_today: int,
    volume_20day_avg: Decimal,
    price_5day_return: Decimal,
    dollar_volume_today: Money,
) -> ScanScore: ...

class PolymarketFilters(BaseModel):
    min_gap: Decimal
    min_depth_usdc: Money
    min_hours_to_resolution: int
    max_hours_to_resolution: int

class AlpacaFilters(BaseModel):
    min_relative_volume: Decimal
    min_dollar_volume: Money
    price_range_low: Price
    price_range_high: Price

def apply_polymarket_filters(score: ScanScore, filters: PolymarketFilters) -> ScanScore: ...
def apply_alpaca_filters(score: ScanScore, filters: AlpacaFilters) -> ScanScore: ...
```

#### 1.4.2 Internal Implementation Details

**`score_polymarket_market`:**
- `gap = abs(estimated_probability - book.midpoint)`
- `depth = min(sum(size for _, size in book.bids[:10]), sum(size for _, size in book.asks[:10]))`  — only top-10 levels on each side
- `hours_to_resolution = (market.resolution_time - now).total_seconds() / 3600`

**`score_alpaca_instrument`:**
- `relative_volume = Decimal(volume_today) / volume_20day_avg`  — 1.5 is the threshold
- `price_momentum = price_5day_return`  — signed
- `dollar_volume = dollar_volume_today`  — absolute

**Filter semantics:** `apply_*_filters` mutates `score.accepted` and sets `rejection_reason` at the FIRST filter failure (short-circuit). Returns a new `ScanScore` (models are frozen).

#### 1.4.3 Data Structures

(Public `ScanScore`, `PolymarketFilters`, `AlpacaFilters`.)

#### 1.4.4 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Empty book (no bids or asks) | `depth = 0`; filter rejects with "insufficient_depth" | REQ-SCAN-003 |
| 2 | `resolution_time` is in the past | `hours_to_resolution < 0`; filter rejects | REQ-SCAN-003 |
| 3 | `volume_20day_avg = 0` | Returns `relative_volume = Decimal('Infinity')` — guard against ZeroDivisionError by returning high sentinel; filter accepts (unusual) | REQ-SCAN-010 |
| 4 | `gap == min_gap` exactly | Accepted (boundary inclusive on min side, exclusive on max side) | REQ-SCAN-003 |
| 5 | `hours_to_resolution == max_hours_to_resolution` exactly | Accepted (inclusive) | REQ-SCAN-003 |
| 6 | `dollar_volume < min_dollar_volume` by 1 cent | Rejected with "insufficient_dollar_volume" | REQ-SCAN-011 |
| 7 | `price = price_range_high` exactly | Accepted | REQ-SCAN-011 |

#### 1.4.5 Error Handling

All inputs pre-validated by Pydantic models. No exceptions raised under normal use. `ZeroDivisionError` handled by sentinel (see edge case 3).

#### 1.4.6 Non-Functional Requirements

| NFR | Requirement | Addressed by |
|---|---|---|
| Correctness | Scoring is deterministic given inputs | Pure functions |
| Performance | O(1) per market + O(book_depth) for depth sum | Top-10 cap on book levels |

---

### 1.5 `domain/kelly.py`

**File:** `python/claude_poly_bot/domain/kelly.py`
**Responsibility:** Kelly criterion position sizing — pure math.
**Requirements Covered:** REQ-EXE-001, REQ-EXE-002, REQ-EXE-003, REQ-EXE-004.
**Dependencies:** `domain/models.py`.

#### 1.5.1 Public Interface

```python
class SizingInput(BaseModel):
    p_win: Probability
    market_price: Price       # effective entry price, 0 < price < 1 for Polymarket; positive for Alpaca
    bankroll: Money
    max_fraction: Decimal     # default 0.25 (quarter-Kelly cap)
    consensus: Literal["FULL", "HALF", "SKIP"]
    min_trade_size: Money     # if resulting size < this, return size=0

class SizingOutput(BaseModel):
    f_star: Decimal           # Kelly fraction pre-cap, can be < 0
    f_applied: Decimal        # clamped to [0, max_fraction], multiplied by consensus factor
    position_size: Money      # f_applied * bankroll, rounded DOWN to venue tick size
    reason: Literal["OK", "NEGATIVE_EV", "INSUFFICIENT_CAPITAL", "CONSENSUS_SKIP"]

def kelly_size(input: SizingInput) -> SizingOutput: ...
```

#### 1.5.2 Internal Implementation Details

**Formula:**
- `b = (1 / market_price) - 1`  (payout ratio on win)
- `q = 1 - p_win`
- `f_star = (p_win * b - q) / b`
- If `consensus == "SKIP"`: return `position_size=0, reason="CONSENSUS_SKIP"`.
- If `f_star <= 0`: return `position_size=0, reason="NEGATIVE_EV"`.
- `consensus_factor = 1.0 if consensus=="FULL" else 0.5`
- `f_applied = min(f_star, max_fraction) * consensus_factor`
- `position_size = round_down(f_applied * bankroll, venue_tick_size)`  — tick size passed externally (see sizing in executor)
- If `position_size < min_trade_size`: return `position_size=0, reason="INSUFFICIENT_CAPITAL"`.

**`Decimal` math throughout.** `Decimal(1)/market_price` rather than `1/market_price`.

#### 1.5.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | `market_price = 0` | ZeroDivisionError; module validates inputs and raises `InvalidSizingInputError` upstream | REQ-EXE-001 |
| 2 | `market_price = 1.0` (or very close, e.g., 0.99) | `b` ~ 0; `f_star` ~ `-q/b` ≈ very large negative; returns NEGATIVE_EV | REQ-EXE-003 |
| 3 | `p_win = 1.0` with `market_price < 1` | Guaranteed-win scenario; `f_star = 1.0`; clamped to `max_fraction=0.25` | REQ-EXE-002 |
| 4 | `bankroll = 0` | Returns `INSUFFICIENT_CAPITAL` | HLD §5.2 insufficient-capital guard |
| 5 | `f_star` exactly equals `max_fraction` | No clamping; consensus factor applied as-is | REQ-EXE-002 |
| 6 | `consensus=HALF` and `f_star = max_fraction` | `f_applied = 0.5 * max_fraction` | REQ-EXE-004 |

#### 1.5.4 Error Handling

Raises `InvalidSizingInputError` on `market_price <= 0` or `> 1.0` (Polymarket). For Alpaca, `market_price` represents share price — upper bound varies by instrument; checked by caller.

#### 1.5.5 Non-Functional Requirements

| NFR | Requirement | Addressed by |
|---|---|---|
| Data Integrity | `Decimal` math; no float rounding | Type system |
| Correctness | Property tests (hypothesis): for any `f_star <= 0`, size=0 | Test harness |

---

### 1.6 `domain/consensus.py`

**File:** `python/claude_poly_bot/domain/consensus.py`
**Responsibility:** Vote aggregation — checks and sub-agents.
**Requirements Covered:** REQ-BRN-011, REQ-EXE-004.
**Dependencies:** `domain/models.py`.

#### 1.6.1 Public Interface

```python
class CheckConsensus(BaseModel):
    verdict: Verdict                     # majority; SKIP if no majority
    agreeing_count: int                  # how many agreed on the majority verdict
    total_count: int
    mean_confidence: Probability         # mean of agreeing checks' confidence
    mean_p_win: Probability              # mean of agreeing checks' p_win

def aggregate_check_results(results: list[CheckResult]) -> CheckConsensus: ...

class SubAgentConsensus(BaseModel):
    size_multiplier: Literal["FULL", "HALF", "SKIP"]
    verdict: Verdict                     # dominant non-SKIP verdict
    agreeing_count: int
    total_count: int

def aggregate_sub_agent_votes(votes: list[CheckResult]) -> SubAgentConsensus: ...
```

#### 1.6.2 Internal Implementation Details

**`aggregate_check_results`** (for the 4 checks — base_rate, news, whale/unusual_volume, disposition):
- Count verdicts: `buy_n, sell_n, skip_n`.
- If `buy_n >= 3`: verdict=BUY, agreeing = BUY-results.
- Elif `sell_n >= 3`: verdict=SELL, agreeing = SELL-results.
- Else: verdict=SKIP, mean_confidence=0, mean_p_win=0.5.
- Returns aggregating stats from agreeing results.

**`aggregate_sub_agent_votes`** (for the 3 sub-agents — arbitrage, convergence, whale_copy/flow_copy):
- Count non-SKIP verdicts.
- If ≥2 agree on same verdict (BUY or SELL): `FULL`, that verdict.
- If exactly 1 non-SKIP: `HALF`, that verdict.
- Else: `SKIP`.

#### 1.6.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | 2 checks BUY, 2 checks SELL | SKIP (no 3-of-4 majority) | REQ-BRN-011 |
| 2 | 3 BUY, 1 SKIP | BUY; confidence = mean of 3 BUYs | REQ-BRN-011 |
| 3 | All 4 SKIP | SKIP | REQ-BRN-011 |
| 4 | Sub-agent: 1 BUY, 1 SELL, 1 SKIP | SKIP (no 2-of-3 agreement on BUY or SELL) | REQ-EXE-004 |
| 5 | Sub-agent: 2 BUY, 1 SKIP | FULL, BUY | REQ-EXE-004 |
| 6 | Sub-agent: 1 BUY, 2 SKIP | HALF, BUY | REQ-EXE-004 |
| 7 | Sub-agent: 3 SKIP | SKIP | REQ-EXE-004 |
| 8 | Checks list size != 4 | ValueError — assertion at module boundary | REQ-BRN-001 |
| 9 | Sub-agent list size != 3 | ValueError | REQ-BRN-002 |

#### 1.6.4 Error Handling

Raises `ValueError` on wrong list sizes (defensive-depth at module boundary per DD convention). Also raises `ValueError` if `aggregate_check_results` receives duplicate `check_type` values (which would skew majority counting).

#### 1.6.5 Non-Functional Requirements

| NFR | Requirement | Addressed by |
|---|---|---|
| Correctness | Deterministic given inputs; vote counting is integer math | Pure functions |
| Testability | Hypothesis property tests: 3-of-4 always = majority; 0/0 split = SKIP | Test harness |
| Observability | Contradictory results (e.g., verdict=BUY with `p_win < 0.5`) logged at WARN before aggregation | Implementation note in `aggregate_check_results` |

---

### 1.7 `domain/risk.py`

**File:** `python/claude_poly_bot/domain/risk.py`
**Responsibility:** Pure risk predicates — evaluate pre-trade and ongoing risk.
**Requirements Covered:** REQ-RISK-001..011, REQ-ALPC-012 (PDT).
**Dependencies:** `domain/models.py`, `domain/clock.py`.

#### 1.7.1 Public Interface

```python
class PreTradeInput(BaseModel):
    bot: Bot
    venue: VenueName
    thesis: Thesis
    current_bankroll: Money
    day_start_bankroll: Money
    daily_pnl: Money
    open_positions_count: int
    available_capital: Money        # bankroll minus reserved for open positions
    config: RiskConfig              # Tier-1 config snapshot
    now: datetime
    account_equity: Money | None = None  # Alpaca only
    recent_day_trades: int | None = None # Alpaca only: trailing 5 business days
    llm_daily_spend: Money
    llm_consecutive_errors: int

class RiskConfig(BaseModel):
    max_position_pct: Decimal
    max_daily_loss_pct: Decimal
    max_open_positions: int
    llm_daily_spend_cap: Money
    min_trade_size: Money
    pdt_equity_threshold: Money = Money("25000")
    pdt_max_day_trades: int = 3

class PreTradeDecision(BaseModel):
    allow: bool
    reason: Literal[
        "OK",
        "RISK_HALT_ACTIVE",
        "MAX_OPEN_POSITIONS",
        "INSUFFICIENT_CAPITAL",
        "DAILY_DRAWDOWN",
        "LLM_SPEND_CAP",
        "LLM_SUSTAINED_ERRORS",
        "PDT_VIOLATION",
        "VERDICT_SKIP",
    ]
    details: dict = {}

# Note: LIVE_ENABLED gating is NOT a risk concern. PreTradeDecision.allow=True
# means the trade is permissible; whether the order is *real* (LIVE) or *simulated*
# (DRY_RUN) is determined at the executor boundary by the executor checking
# config.live_enabled for the (bot, venue) pair. This separation keeps risk
# evaluation and execution-mode gating orthogonal.

def evaluate_pre_trade(input: PreTradeInput, *, active_halt: RiskHalt | None) -> PreTradeDecision: ...

def is_daily_drawdown_breached(
    daily_pnl: Money, day_start_bankroll: Money, max_daily_loss_pct: Decimal
) -> bool: ...

def is_llm_spend_breached(llm_daily_spend: Money, cap: Money) -> bool: ...

def is_pdt_violation(
    account_equity: Money, recent_day_trades: int, threshold: Money, max_day_trades: int
) -> bool: ...

def cap_position_size(proposed: Money, bankroll: Money, max_pct: Decimal) -> Money: ...
```

#### 1.7.2 Internal Implementation Details

**`evaluate_pre_trade` check order (short-circuit on first failure):**
1. `active_halt is not None` → `allow=False, reason=RISK_HALT_ACTIVE`
2. `thesis.verdict == SKIP` → `allow=False, reason=VERDICT_SKIP` (not an error; the brain decided not to trade)
3. `open_positions_count >= config.max_open_positions` → `allow=False, reason=MAX_OPEN_POSITIONS`
4. `available_capital < config.min_trade_size` → `allow=False, reason=INSUFFICIENT_CAPITAL`
5. `is_llm_spend_breached(...)` → `allow=False, reason=LLM_SPEND_CAP`
6. `llm_consecutive_errors >= 5` → `allow=False, reason=LLM_SUSTAINED_ERRORS`
7. If `venue == alpaca`: `is_pdt_violation(...)` → `allow=False, reason=PDT_VIOLATION`
8. `is_daily_drawdown_breached(...)` → `allow=False, reason=DAILY_DRAWDOWN`
9. Otherwise `allow=True, reason=OK`.

**`is_daily_drawdown_breached`:** `daily_pnl / day_start_bankroll <= -max_daily_loss_pct` (signed; loss is negative). Uses `Decimal` comparison.

**`cap_position_size`:** `min(proposed, bankroll * max_pct)`, rounded to 8 decimal places.

#### 1.7.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | `day_start_bankroll = 0` | `is_daily_drawdown_breached` returns False (can't lose more than 0); caller handles as bankroll-empty case | REQ-RISK-002 |
| 2 | `open_positions = max_open` exactly | Rejected (>=, not >) | REQ-RISK-004 |
| 3 | `available_capital = min_trade_size` exactly | Allowed | REQ-RISK-005 |
| 4 | Alpaca account equity = $25,000 exactly, recent trades = 3 | No violation (equity at threshold) | REQ-ALPC-012 |
| 5 | Alpaca equity = $24,999, recent trades = 3 | Violation (would be 4th day trade) | REQ-ALPC-012 |
| 6 | `daily_pnl = -50% bankroll` exactly | Breached (`<=`) | REQ-RISK-002 |
| 7 | `llm_consecutive_errors = 5` exactly | Breached | REQ-BRN-015 |

#### 1.7.4 Non-Functional Requirements

| NFR | Requirement | Addressed by |
|---|---|---|
| Correctness | All comparisons explicit, short-circuit order defined | Implementation spec |
| Testability | Property tests on every predicate | Unit tests |

---

### 1.8 `domain/thesis.py`

**File:** `python/claude_poly_bot/domain/thesis.py`
**Responsibility:** Assemble a `Thesis` from check results + sub-agent votes + venue-specific extensions.
**Requirements Covered:** REQ-BRN-009, REQ-BRN-010, REQ-BRN-011, REQ-BRN-007 (Alpaca extensions).
**Dependencies:** `domain/models.py`, `domain/consensus.py`.

#### 1.8.1 Public Interface

```python
class ThesisInput(BaseModel):
    bot: Bot
    venue: VenueName
    market_id: str
    check_results: list[CheckResult]      # 4 results, one per check
    sub_agent_results: list[CheckResult]  # 3 results, one per sub-agent
    scan_correlation_id: UUID
    confidence_threshold: Probability     # from config, default 0.75
    # Alpaca-only: LLM-produced target/stop/horizon (from the sub-agent calls' raw_response)
    target_price: Price | None = None
    stop_price: Price | None = None
    horizon_hours: int | None = None

class ThesisOutcome(BaseModel):
    thesis: Thesis | None
    decision: Literal["PRODUCED", "BELOW_CONFIDENCE", "NO_CHECK_CONSENSUS", "SUB_AGENT_SKIP"]
    check_consensus: CheckConsensus
    sub_agent_consensus: SubAgentConsensus

def generate_thesis(input: ThesisInput, *, now: datetime) -> ThesisOutcome: ...
```

#### 1.8.2 Internal Implementation Details

0. **Pre-validate inputs** (defensive-depth at module boundary):
   - `len(check_results) == 4` else `ValueError`.
   - `len(sub_agent_results) == 3` else `ValueError`.
   - `len(set(r.check_type for r in check_results)) == 4` (no duplicates) else `ValueError`.
   - The 4 distinct check_types must equal the venue's expected set (Polymarket: `{base_rate, news, whale, disposition}`; Alpaca: `{base_rate, news, unusual_volume, disposition}`) else `ValueError`.
   - `len(set(r.sub_agent for r in sub_agent_results)) == 3` (no duplicates) else `ValueError`.
1. Call `aggregate_check_results(check_results)` → `CheckConsensus`.
2. Call `aggregate_sub_agent_votes(sub_agent_results)` → `SubAgentConsensus`.
3. If `check_consensus.verdict == SKIP`: return `decision="NO_CHECK_CONSENSUS"`, `thesis=None`.
4. If `check_consensus.mean_confidence < threshold`: return `decision="BELOW_CONFIDENCE"`, `thesis=None`.
5. If `sub_agent_consensus.size_multiplier == "SKIP"`: return `decision="SUB_AGENT_SKIP"`, `thesis=None`.
6. If check verdict != sub-agent verdict (e.g., checks say BUY, sub-agents say SELL): log warning and return `decision="NO_CHECK_CONSENSUS"`, `thesis=None` (conflict safety).
7. If venue==alpaca and any of `target_price`, `stop_price`, `horizon_hours` is None: raise `ValidationError` — Alpaca trades require all three (REQ-BRN-007).
8. Generate `decision_correlation_id = uuid5(scan_correlation_id, bot.value)` (deterministic, per DD-019).
9. Construct and return `Thesis` with aggregated confidence and p_win.

#### 1.8.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Checks agree BUY, sub-agents agree SELL | `decision="NO_CHECK_CONSENSUS"` with conflict log | REQ-BRN-011 |
| 2 | Alpaca trade missing `stop_price` | `ValidationError` | REQ-BRN-007 |
| 3 | Polymarket trade with `target_price` accidentally set | Allowed — extra Alpaca-only fields ignored for Polymarket construction | REQ-BRN-007 |
| 4 | `confidence = threshold` exactly | Allowed (>=) | REQ-BRN-012 |
| 5 | 3 checks agree BUY confidence [0.9, 0.8, 0.6], 1 check SELL | Mean agreeing conf = (0.9+0.8+0.6)/3 = 0.767 — above 0.75, thesis produced | REQ-BRN-011 |

#### 1.8.4 Error Handling

Raises:
- `ValueError` on input shape violations (wrong list size, duplicate check_type, wrong check_type set for venue).
- `pydantic.ValidationError` for invalid Alpaca thesis construction (missing target/stop/horizon).

Returns `ThesisOutcome` with `thesis=None` for business-logic rejections (not an error — these are the normal "didn't pass thresholds" outcomes).

#### 1.8.5 Non-Functional Requirements

| NFR | Requirement | Addressed by |
|---|---|---|
| Correctness | Deterministic; defensive input validation at boundary | Step 0 pre-validation |
| Observability | Verdict-mismatch (checks vs sub-agents) logged as WARN with both consensus snapshots | Step 6 implementation |
| Testability | Pure function; injectable `now`; comprehensive edge-case table | Test harness |
| Data Integrity | `decision_correlation_id` derived deterministically from `scan_correlation_id + bot` enables idempotent identity | DD-019, Step 8 |

---

## Cross-Cutting — Batch 1

### Testing Strategy (Batch 1)

Every module in `domain/` is pure and has:
- **Unit tests** in `tests/unit/domain/test_<module>.py` with ~100% line coverage.
- **Property tests** via `hypothesis` for `kelly.py`, `risk.py`, `scoring.py`:
  - Kelly: for all valid inputs, `position_size >= 0`; for `f_star <= 0`, `position_size == 0`.
  - Risk: any true predicate implies `allow=False` in `evaluate_pre_trade`.
  - Scoring: filter rejections have non-None `rejection_reason`.
- **Edge-case tests**: every row in the LLD edge-case tables has a named test.
- **Zero I/O**: tests run in <100ms in total.

### Assumptions Log (Batch 1)

None — all decisions traced to REQs + HLD.

### Open Items (Batch 1)

1. `score_polymarket_market` takes `estimated_probability` — where does that come from before the LLM runs? Pre-filter at scanner stage uses the `midpoint` as the estimate (gap = 0). The scanner accepts/rejects on structural grounds (depth, time). The **real** edge gap is computed post-brain, not at scan time. **Decision:** scan-time uses `estimated_probability = midpoint` so that initial gap = 0, and structural filters (depth, hours) dominate. The actual gap emerges in the brain. Will revisit in Batch 5 (scanner loop).

### Self-Review Findings (Batch 1) — Resolved

Subagent review was unavailable (quota); applied a self-review against the same checklist. Findings and resolutions:

| # | Severity | Module | Finding | Resolution |
|---|---|---|---|---|
| 1 | HIGH | `thesis.py` | `generate_thesis` did not validate that `check_results` had 4 distinct check_types — duplicates would skew majority counting | Added Step 0 pre-validation block (1.8.2) requiring 4 distinct check_types matching the venue's expected set; documented in Error Handling (1.8.4) |
| 2 | HIGH | `risk.py` | `PreTradeDecision.reason` included `LIVE_DISABLED`, but per separation of concerns LIVE_ENABLED gating is an executor-stage concern (DRY vs simulated), not a risk-evaluation concern | Removed `LIVE_DISABLED`; added `VERDICT_SKIP`; added explanatory note in `PreTradeDecision` definition; updated check-order Step 9 to make `allow=True` only on the OK branch |
| 3 | MED | `models.py` / `thesis.py` | DD-019 says `decision_correlation_id` flows through theses, but `Thesis` model didn't carry it | Added `decision_correlation_id: UUID` to `Thesis`; added Step 8 in `generate_thesis` to derive it deterministically as `uuid5(scan_correlation_id, bot.value)` |
| 4 | MED | `consensus.py`, `thesis.py` | Missing explicit NFR sections | Added §1.6.5 and §1.8.5 NFR tables |
| 5 | MED | `models.py` | `ScanScore.score: dict[str, Decimal]` was weakly typed; venue-specific score fields had no compile-time safety | Replaced with discriminated union of `PolymarketScoreFields` and `AlpacaScoreFields` (discriminated by `venue`) |
| 6 | LOW | `consensus.py` | Contradictory CheckResult (e.g., verdict=BUY with p_win<0.5) not handled | Added observability NFR (§1.6.5) — log at WARN before aggregation |
| 7 | LOW | `protocols.py` | `StrategistContext` could specialize per check_type | Deferred — current shape works; revisit in Batch 4 (LLM adapters) when prompt context shapes are concrete |
| 8 | LOW | `kelly.py` | `f_star > 1` cases (high p_win × low price) not in edge-case table explicitly | Added to open items — covered by clamp logic but worth a hypothesis property test |
