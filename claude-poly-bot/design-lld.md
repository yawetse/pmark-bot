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

---

## Batch 2 — Storage, Config, Observability, Wallet, Auth

10 modules. Concrete adapters for the ports defined in Batch 1 plus surface infra concerns (auth, secrets, alerts).

**Dependency order within batch:** `storage/db` + `storage/orm` → `storage/repos` → `storage/s3`; `config/` (depends on `storage/repos`); `observability/{logging, metrics, alerts}`; `wallet/evm`; `auth/{oauth, session}`.

---

### 2.1 `storage/db.py`

**File:** `python/claude_poly_bot/storage/db.py`
**Responsibility:** SQLAlchemy 2.0 async engine, session factory, transaction helpers. Single source of truth for DB connectivity.
**Requirements Covered:** REQ-INF-003 (RDS Postgres), REQ-CICD-007 (local dev via docker-compose), HLD §5.1 (RDS retry-with-pause).
**Dependencies:** `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `domain/protocols.py` (Clock for timestamps).
**Depended On By:** every repo, all CLI commands, alembic env.

#### 2.1.1 Public Interface

```python
@dataclass(frozen=True)
class DbSettings:
    url: str                          # postgresql+asyncpg://... — Tier 2
    pool_size: int = 10
    max_overflow: int = 5
    pool_recycle_sec: int = 1800
    echo: bool = False
    statement_timeout_ms: int = 30_000

async def create_engine(settings: DbSettings) -> AsyncEngine: ...
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]: ...

@asynccontextmanager
async def transaction(session_maker: async_sessionmaker) -> AsyncIterator[AsyncSession]:
    """Open a session, BEGIN; commit on success, rollback on exception."""

@asynccontextmanager
async def retrying_db(
    op_name: str,
    *,
    max_attempts: int = 5,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 8.0,
    metrics: MetricsSink,
) -> AsyncIterator[None]:
    """Wraps a DB operation in exponential-backoff retry on `OperationalError`/
    `DBAPIError` (connection lost). Used by loops to PAUSE during RDS failover
    rather than crash on first error (HLD §5.1)."""
```

#### 2.1.2 Internal Implementation Details

- Engine uses asyncpg with `server_settings={"statement_timeout": str(statement_timeout_ms)}`.
- `pool_pre_ping=True` so dead connections detected before use.
- `retrying_db` retries on `sqlalchemy.exc.OperationalError`, `sqlalchemy.exc.DBAPIError` where `e.connection_invalidated` is True; never retries on `IntegrityError` (those are programmer/data bugs).
- Each attempt emits `db.retry{op_name,attempt}` metric; final failure emits `db.exhausted{op_name}`.

#### 2.1.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Connection lost mid-query | `retrying_db` catches, sleeps, retries | HLD §5.1 |
| 2 | RDS failover takes >8s × 5 = 40s | `retrying_db` re-raises after exhaustion; caller's loop crashes | HLD §5.1 |
| 3 | `IntegrityError` (e.g., duplicate UUID) | Re-raised immediately, not retried | DD-020 |
| 4 | Statement timeout (slow query) | `OperationalError`; retried (idempotent reads) — for writes, must be inside an explicit `transaction()` so retry on commit-after-timeout is safe | Performance |

#### 2.1.4 Error Handling

Re-raises after retry exhaustion. Never silently swallows.

#### 2.1.5 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Reliability | Survive RDS failover up to 40s | `retrying_db` |
| Observability | Every retry/exhaustion metricized | MetricsSink calls |
| Performance | `pool_pre_ping`; configurable pool size | Settings |

---

### 2.2 `storage/orm.py`

**File:** `python/claude_poly_bot/storage/orm.py`
**Responsibility:** SQLAlchemy ORM table definitions mirroring domain models. Indices, constraints, triggers.
**Requirements Covered:** REQ-CFG-001, REQ-CFG-007 (config_audit append-only), all storage-backed REQs from Batch 1.
**Dependencies:** `sqlalchemy.orm`, `storage/db.py`.

#### 2.2.1 Tables (column highlights only — full DDL via Alembic)

| Table | Key Columns | Notable Constraints / Indices |
|---|---|---|
| `positions` | `id UUID PK`, `bot`, `venue`, `market_id`, `status`, `entry_price NUMERIC(24,8)`, `size NUMERIC(24,8)`, `realized_pnl NUMERIC(24,8) NULL`, `thesis_id UUID FK theses.id`, `entry_order_id UUID FK orders.client_order_id`, `exit_order_id UUID FK orders.client_order_id NULL`, `opened_at`, `closed_at NULL` | CHECK status transitions monotonic; UNIQUE (entry_order_id); INDEX (bot, venue, status); INDEX (status, closed_at) |
| `orders` | `client_order_id UUID PK`, `bot`, `venue`, `market_id`, `status`, `side`, `size`, `limit_price`, `venue_order_id NULL`, `is_entry BOOL`, `parent_position_id UUID NULL`, `submitted_at NULL`, `last_checked_at`, `error TEXT NULL` | CHECK status transitions monotonic; INDEX (status, bot); INDEX (venue_order_id); UNIQUE (venue_order_id) WHERE NOT NULL |
| `trades` | `id UUID PK`, `position_id UUID FK`, `order_id UUID FK orders.client_order_id`, `bot`, `venue`, `size`, `price`, `side`, `filled_at`, `fees` | INDEX (bot, venue, filled_at); INDEX (position_id) |
| `decisions` | `id UUID PK`, `bot`, `venue`, `market_id`, `check_type`, `sub_agent NULL`, `verdict`, `confidence`, `p_win`, `model_id`, `tokens_in`, `tokens_out`, `tokens_cached`, `cost_usd`, `latency_ms`, `web_search_used`, `prompt JSONB`, `response JSONB`, `error TEXT NULL`, `correlation_id UUID`, `thesis_id UUID NULL` | INDEX (bot, venue, created_at); INDEX (correlation_id); INDEX (thesis_id) |
| `theses` | `id UUID PK`, `bot`, `venue`, `market_id`, `verdict`, `p_win`, `confidence`, `size_multiplier`, `target_price NULL`, `stop_price NULL`, `horizon_hours NULL`, `scan_correlation_id UUID`, `decision_correlation_id UUID UNIQUE`, `created_at` | INDEX (scan_correlation_id); INDEX (bot, venue, created_at) |
| `candidate_queue` | `scan_correlation_id UUID PK`, `venue`, `market_id`, `market_snapshot JSONB`, `book_snapshot JSONB NULL`, `scan_score JSONB`, `created_at` | INDEX (venue, created_at) |
| `candidate_claims` | `scan_correlation_id UUID FK`, `bot`, `status` (`new`/`processing`/`done`/`error`), `decision_correlation_id UUID UNIQUE`, `claimed_at NULL`, `completed_at NULL`, `error TEXT NULL` | PRIMARY KEY (scan_correlation_id, bot); INDEX (bot, status); per DD-017 |
| `config` | `bot NULL`, `venue NULL`, `field`, `value JSONB`, `updated_at`, `updated_by` | PRIMARY KEY (COALESCE(bot,''), COALESCE(venue,''), field); CHECK (bot IS NULL OR bot IN enum) |
| `config_audit` | `id UUID PK`, `bot NULL`, `venue NULL`, `field`, `old_value JSONB`, `new_value JSONB`, `actor_email`, `changed_at`, `confirmation_checksum` | INDEX (changed_at DESC); TRIGGER `forbid_update_delete` BEFORE UPDATE OR DELETE → RAISE EXCEPTION |
| `target_wallets` | `address PK`, `total_trades`, `win_rate`, `total_pnl`, `refreshed_at` | INDEX (refreshed_at DESC) |
| `risk_halts` | `id UUID PK`, `bot`, `venue NULL`, `reason`, `triggered_at`, `resumes_at NULL`, `metrics_snapshot JSONB`, `lifted_at NULL` | INDEX (bot, venue, lifted_at); active halt query: `WHERE lifted_at IS NULL` |
| `auth_events` | `id UUID PK`, `event`, `email NULL`, `ip NULL`, `user_agent NULL`, `at` | INDEX (at DESC); INDEX (email, at DESC) |
| `market_scans` | `scan_correlation_id UUID PK`, `venue`, `started_at`, `ended_at`, `fetched`, `accepted`, `rejected`, `error NULL` | INDEX (venue, started_at DESC) |
| `bankroll_snapshots` | `id UUID PK`, `bot`, `venue`, `as_of`, `current_bankroll`, `day_start_bankroll`, `daily_pnl_realized`, `daily_pnl_unrealized` | INDEX (bot, venue, as_of DESC); written at 00:00 UTC by RISK + on demand |

#### 2.2.2 Constraints / Triggers

- `config_audit_forbid_modify`: PL/pgSQL trigger raising exception on UPDATE/DELETE to make audit append-only (REQ-CFG-007, HLD §5.2).
- `positions_status_transition`: row-level trigger validating status only moves OPEN → CLOSING → CLOSED (or to ORPHANED/ADOPTED reconciliation states).
- `orders_status_transition`: trigger validating PENDING → terminal states only.
- All NUMERIC columns are `NUMERIC(24, 8)`; PostgreSQL enforces precision.
- All timestamps `TIMESTAMP WITH TIME ZONE`; naive timestamps rejected by SQLAlchemy.

#### 2.2.3 Migrations

- `alembic/versions/0001_initial.py` — all tables created in initial migration.
- Subsequent schema changes require a new migration; CI fails if a model field has no corresponding migration.
- Alembic auto-generation as starting point only; reviewed by hand for safety.

#### 2.2.4 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Insert duplicate `client_order_id` into `orders` | `IntegrityError` | DD-020 |
| 2 | Insert claim row with same `(scan_correlation_id, bot)` twice | `IntegrityError`; consumed via `ON CONFLICT DO NOTHING` in repo layer | DD-017 |
| 3 | Update on `config_audit` | Trigger RAISES exception | REQ-CFG-007 |
| 4 | `scan_correlation_id` orphan in `candidate_claims` (deleted from `candidate_queue`) | Foreign key violation; queue rows are never deleted, only soft-archived | Data integrity |

#### 2.2.5 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Data Integrity | Triggers for monotonic transitions and append-only audit | PL/pgSQL |
| Performance | Indexes on common access patterns | Index list |
| Observability | All FKs declared so `pgaudit` can trace | Schema |

---

### 2.3 `storage/repos/`

**Files:** one Python module per protocol from `domain/protocols.py`.
**Responsibility:** Concrete async implementations of repo protocols using SQLAlchemy ORM.
**Requirements Covered:** All REQs requiring durable persistence.

#### 2.3.1 Public Interface

Each module exports a class implementing the corresponding Protocol:

```python
class SqlAlchemyPositionRepo(PositionRepo):
    def __init__(self, session_maker: async_sessionmaker, clock: Clock): ...
    # implements all PositionRepo methods

class SqlAlchemyOrderRepo(OrderRepo): ...
class SqlAlchemyTradeRepo(TradeRepo): ...
class SqlAlchemyDecisionRepo(DecisionRepo): ...
class SqlAlchemyThesisRepo(ThesisRepo): ...
class SqlAlchemyCandidateRepo(CandidateRepo): ...
class SqlAlchemyConfigRepo(ConfigRepo): ...
class SqlAlchemyAuditRepo(AuditRepo): ...
class SqlAlchemyTargetWalletRepo(TargetWalletRepo): ...
class SqlAlchemyRiskHaltRepo(RiskHaltRepo): ...
class SqlAlchemyBankrollRepo(BankrollRepo): ...
```

#### 2.3.2 Key Implementation Notes

- **`SqlAlchemyCandidateRepo.claim_next(bot, limit)`**: per DD-017:
  ```python
  # 1. Find candidates without a claim row for this bot
  # 2. INSERT candidate_claims (... ON CONFLICT DO NOTHING) for each
  # 3. UPDATE candidate_claims SET status='processing' WHERE bot=? AND status='new'
  #    LIMIT N FOR UPDATE SKIP LOCKED RETURNING *
  # 4. Return the joined Candidate + CandidateClaim records
  ```
- **`SqlAlchemyOrderRepo.insert_pending`**: writes the `orders` row with `status='PENDING'` BEFORE the venue submit (DD-020). `mark_submitted` is the second step that records `venue_order_id` after a successful submit.
- **`SqlAlchemyConfigRepo.set`**: atomic `UPDATE config ...; INSERT INTO config_audit ...` in one transaction. `audit_log` is read-only.
- **`SqlAlchemyRiskHaltRepo.is_halted`**: query `risk_halts WHERE bot=? AND (venue=? OR venue IS NULL) AND lifted_at IS NULL ORDER BY triggered_at DESC LIMIT 1`. A `venue IS NULL` halt is a bot-wide halt.
- **`SqlAlchemyDecisionRepo.record`**: stores prompt and response as JSONB; redacts secrets via `RedactProcessor` before write (defense in depth).
- All repos use `transaction()` from `db.py` per call; loops can pass an outer transaction context if needed (sessions accepted as optional kwarg).

#### 2.3.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | `claim_next` called with no new candidates | Returns empty list | REQ-SCAN-005 |
| 2 | `claim_next` race between two concurrent callers (same bot) | `FOR UPDATE SKIP LOCKED` ensures each row is taken at most once per call; non-conflicting rows distributed | DD-017 |
| 3 | `insert_pending` with duplicate `client_order_id` | `IntegrityError` → caller raises `DuplicateClientOrderIdError` | DD-020 |
| 4 | `is_halted(bot, venue=None)` when both bot-wide and venue-specific halts exist | Returns most recent (DESC by triggered_at) | HLD §5.6 |
| 5 | `set_config` for unknown field | `UnknownConfigField` raised; validation rejects upstream (Tier 1 schema) | REQ-CFG-011 |
| 6 | `transition` on already-terminal position | Trigger raises; repo returns `InvalidStateTransitionError` | Invariants |

#### 2.3.4 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Correctness | Trigger-enforced invariants; idempotent operations | DB-level + repo-level |
| Performance | Indexes for common access patterns; bulk inserts where applicable | ORM design |
| Testability | Each repo testable against testcontainers Postgres | Per-test container with migrations |

---

### 2.4 `storage/s3.py`

**File:** `python/claude_poly_bot/storage/s3.py`
**Responsibility:** S3 client wrapper for trade-data parquet snapshots and archived LLM logs.
**Requirements Covered:** REQ-DATA-001, REQ-DATA-006, REQ-OBS-006 (90-day archive).
**Dependencies:** `boto3` (or `aioboto3`).

#### 2.4.1 Public Interface

```python
class S3StoreImpl(S3Store):
    def __init__(self, bucket: str, region: str = "us-east-1"): ...
    async def put_parquet(self, key: str, body: bytes) -> None: ...
    async def get_parquet(self, key: str) -> bytes: ...
    async def list_prefix(self, prefix: str) -> list[str]: ...
    async def archive_jsonl_gz(self, key: str, rows: AsyncIterator[dict]) -> int: ...

# Key conventions:
# polymarket-trades/yyyy=YYYY/mm=MM/dd=DD/trades.parquet
# decision-archives/yyyy=YYYY/mm=MM/dd=DD/decisions-{bot}.jsonl.gz
```

#### 2.4.2 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | S3 throttling (503) | boto3 default retry (3 attempts, exponential backoff) | REQ-DATA-001 |
| 2 | Missing key on `get_parquet` | `S3KeyNotFoundError` raised | REQ-DATA-005 |
| 3 | `archive_jsonl_gz` with empty iterator | Writes empty `.jsonl.gz` file (still a valid object) | REQ-OBS-006 |

#### 2.4.3 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Reliability | Retries on transient errors | boto3 |
| Observability | Every PUT/GET emits metric | MetricsSink |

---

### 2.5 `config/`

**Files:** `python/claude_poly_bot/config/{schema.py, service.py, defaults.py}`
**Responsibility:** Tier-1 config schema, validation, persistence; Tier-2 startup loading from env; Tier-3 module constants.
**Requirements Covered:** REQ-CFG-001..013, REQ-CFG-002 (tiers).
**Dependencies:** `pydantic`, `domain/protocols.py` (ConfigRepo), `storage/repos/config.py`.

#### 2.5.1 Public Interface

**`schema.py`** — Pydantic settings classes describing every Tier-1 field:

```python
class BotGlobalConfig(BaseModel):
    """Bot-level (venue=None). One row per bot."""
    llm_daily_spend_cap: Money = Money("20")
    auth_allowlist: list[EmailStr] = ["yaw.etse@gmail.com"]
    # Per-check, per-venue model overrides as nested dict
    models: dict[CheckType, dict[VenueName, str]] = {}

class VenuePolymarketConfig(BaseModel):
    """Per-(bot, polymarket) row."""
    live_enabled: bool = False
    starting_bankroll: Money
    max_position_pct: Decimal = Decimal("0.25")
    max_daily_loss_pct: Decimal = Decimal("0.50")
    max_open_positions: int = 5
    kelly_max_fraction: Decimal = Decimal("0.25")
    thesis_confidence_threshold: Probability = Decimal("0.75")
    scanner_cadence_sec: int = 300
    exit_cadence_sec: int = 60
    target_hit_multiplier: Decimal = Decimal("0.85")
    volume_exit_multiplier: Decimal = Decimal("3.0")
    stale_window_hours: int = 24
    stale_price_change_pct: Decimal = Decimal("0.02")
    order_ttl_sec: int = 300
    slippage_tolerance: Decimal = Decimal("0.02")
    geo: Geo = Geo.US
    min_gap: Decimal = Decimal("0.07")
    min_depth: Money = Money("500")
    min_hours_to_resolution: int = 4
    max_hours_to_resolution: int = 168
    target_wallet_min_trades: int = 100
    target_wallet_min_win_rate: Probability = Decimal("0.70")
    target_wallet_top_n: int = 50
    whale_check_cache_sec: int = 300
    usdc_low_balance_threshold: Money = Money("10")
    matic_low_balance_threshold: Money = Money("0.5")

class VenueAlpacaConfig(BaseModel):
    """Per-(bot, alpaca) row."""
    live_enabled: bool = False
    starting_bankroll: Money
    max_position_pct: Decimal = Decimal("0.25")
    max_daily_loss_pct: Decimal = Decimal("0.50")
    max_open_positions: int = 5
    kelly_max_fraction: Decimal = Decimal("0.25")
    thesis_confidence_threshold: Probability = Decimal("0.75")
    scanner_cadence_sec: int = 300
    exit_cadence_sec: int = 60
    target_hit_multiplier: Decimal = Decimal("0.85")
    volume_exit_multiplier: Decimal = Decimal("3.0")
    stale_window_hours: int = 24
    stale_price_change_pct: Decimal = Decimal("0.02")
    order_ttl_sec: int = 300
    slippage_tolerance: Decimal = Decimal("0.001")  # 0.1% for equities
    equity_universe: Literal["sp500", "sp500_nasdaq100_etfs", "custom"] = "sp500_nasdaq100_etfs"
    custom_universe: list[str] = []  # tickers; only used when equity_universe="custom"
    min_relative_volume: Decimal = Decimal("1.5")
    min_dollar_volume: Money = Money("10000000")
    price_range_low: Price = Price("5")
    price_range_high: Price = Price("2000")
    trade_horizon_hours: int = 72
    allow_overnight_holds: bool = False
    unusual_volume_cache_sec: int = 300
```

**`service.py`** — read/validate/apply config:

```python
class ConfigService:
    def __init__(self, repo: ConfigRepo): ...

    async def get_bot_global(self, bot: Bot) -> BotGlobalConfig: ...
    async def get_polymarket(self, bot: Bot) -> VenuePolymarketConfig: ...
    async def get_alpaca(self, bot: Bot) -> VenueAlpacaConfig: ...

    async def patch(self, bot: Bot | None, venue: VenueName | None, field: str,
                    new_value: Any, *, actor_email: str, confirmation_checksum: str) -> ConfigAudit: ...

    async def validate(self, bot: Bot | None, venue: VenueName | None, field: str, value: Any) -> None:
        """Raises ConfigValidationError on invalid value."""
```

**`defaults.py`** — first-run config seed: writes default rows for all (bot, venue) pairs. Idempotent.

#### 2.5.2 Internal Implementation Details

- `patch` flow:
  1. Validate `field` is a known Tier-1 field for the (bot, venue) scope.
  2. Validate `new_value` matches the field's type/range.
  3. Compute `confirmation_checksum_expected = sha256(field + str(new_value))[:8]` and compare.
  4. Read old value, write new, write audit row — all in one DB transaction.
  5. Return the audit row.
  6. Emit SES alert on `live_enabled` toggles (REQ-CFG-012).

- `validate` per field uses Pydantic model_validate or explicit constraints.

- Tier-2 loaded once at process startup from env vars; `Settings` class with `pydantic-settings`.

#### 2.5.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Patch unknown field | `ConfigValidationError("unknown_field")` | REQ-CFG-011 |
| 2 | Patch `max_position_pct` to 1.5 | Rejected by Pydantic (Decimal field with `le=1.0`) | REQ-CFG-011 |
| 3 | Patch with wrong checksum | `ConfigValidationError("checksum_mismatch")` — defends against UI race conditions | DD safety |
| 4 | Toggle `live_enabled` with no behavior change (true→true) | Still logged + alerted (audit truth) | REQ-CFG-009, REQ-CFG-012 |
| 5 | First-run with no config rows | `defaults.py` writes defaults; reads return defaults | REQ-CFG-001 |
| 6 | Read effective config for (bot, venue) | Merges bot-global + venue-specific rows | REQ-CFG-013 |

#### 2.5.4 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Correctness | Server-side validation; trigger-enforced audit | Pydantic + DB triggers |
| Auditability | Every change logged with checksum | `config_audit` |
| Live-reload | New config takes effect on next loop iteration | No process-local cache |

---

### 2.6 `observability/logging.py`

**File:** `python/claude_poly_bot/observability/logging.py`
**Responsibility:** structlog config; structured JSON to stdout; redaction processor.
**Requirements Covered:** REQ-OBS-001, REQ-OBS-002, REQ-OBS-003 (redaction).
**Dependencies:** `structlog`.

#### 2.6.1 Public Interface

```python
def configure_logging(*, service: str, env: str, level: str = "INFO") -> None: ...

def get_logger(name: str | None = None) -> BoundLogger: ...

# Decorator for adding correlation_id to all logs in scope:
def with_correlation_id(corr_id: UUID) -> AbstractContextManager: ...
```

#### 2.6.2 Internal Implementation Details

structlog processors (in order):
1. `merge_contextvars` — pulls correlation_id from `contextvars`.
2. `add_log_level`, `TimeStamper(fmt="iso")`, `add_logger_name`.
3. `RedactProcessor(patterns=[r"sk-\w+", r"ak-\w+", r"0x[0-9a-fA-F]{64,}"], field_names={"private_key", "api_key", "session_token", "client_secret"})`.
4. `JSONRenderer()`.

`RedactProcessor` walks the log record dict recursively; replaces matching values with `"[REDACTED]"`.

#### 2.6.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Log a dict containing `{"api_key": "sk-abc"}` | Logged as `{"api_key": "[REDACTED]"}` | REQ-OBS-003 |
| 2 | Private key embedded in a deeply nested dict | Recursive redaction catches it | REQ-OBS-003 |
| 3 | Log message contains an EVM private key in free-text | Pattern match redacts the substring | REQ-OBS-003 |
| 4 | Concurrent loops binding different correlation_ids | `contextvars` isolates per-task | REQ-OBS-002 |

#### 2.6.4 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Security | All known secret patterns + field names redacted | RedactProcessor |
| Performance | Redaction is O(record size); negligible | structlog efficient JSON |

---

### 2.7 `observability/metrics.py`

**File:** `python/claude_poly_bot/observability/metrics.py`
**Responsibility:** CloudWatch metric emission via Embedded Metric Format (EMF) on stdout.
**Requirements Covered:** REQ-OBS-007.

#### 2.7.1 Public Interface

```python
class CloudWatchMetricsSink(MetricsSink):
    def __init__(self, namespace: str, dimensions: dict[str, str]): ...
    def incr(self, name: str, *, by: int = 1, tags: dict[str, str] = {}) -> None: ...
    def gauge(self, name: str, value: Decimal, *, tags: dict[str, str] = {}) -> None: ...
    def timing(self, name: str, ms: float, *, tags: dict[str, str] = {}) -> None: ...
    def flush(self) -> None: ...  # called at end of each loop iteration

class NullMetricsSink(MetricsSink):
    """For tests / local dev."""
```

#### 2.7.2 Internal Implementation Details

- Writes EMF JSON to stdout: CloudWatch agent on Fargate ingests automatically.
- Metric values batched per-flush to minimize log volume.
- `tags` become CloudWatch metric dimensions (limited to 10; the most common are bot, venue, model, check, reason).

#### 2.7.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Metric named with invalid characters | Validated; raises `InvalidMetricNameError` | REQ-OBS-007 |
| 2 | Tags exceed 10 keys | Validated; oldest tags dropped with warning | CloudWatch limits |
| 3 | `flush()` called when no metrics buffered | No-op | Performance |

---

### 2.8 `observability/alerts.py`

**File:** `python/claude_poly_bot/observability/alerts.py`
**Responsibility:** SES email alert sink with deduplication.
**Requirements Covered:** REQ-OBS-004, REQ-OBS-005, HLD §5.1 alert-storm prevention.

#### 2.8.1 Public Interface

```python
class SesAlertSink(AlertSink):
    def __init__(
        self,
        ses_client: aioboto3 client,
        from_addr: str,
        to_addrs: list[str],
        dedup_repo: DedupRepo,
        *,
        dedup_window_sec: int = 900,
    ): ...

    async def emit(
        self,
        alert_type: str,
        *,
        bot: Bot | None,
        venue: VenueName | None,
        message: str,
        details: dict,
    ) -> None: ...

class DedupRepo(Protocol):
    """Backed by a Postgres `alert_dedup` table or Redis if needed."""
    async def should_emit(self, key: str, window_sec: int) -> bool: ...

class NullAlertSink(AlertSink):
    """For tests."""
```

#### 2.8.2 Internal Implementation Details

- Dedup key = `f"{alert_type}:{bot}:{venue}"`.
- `should_emit` returns True if no row exists with key + within last `window_sec`; inserts a row when emitting.
- Email subject: `[{env}] {alert_type} ({bot}, {venue})`.
- Body: human-readable `message` + JSON pretty-print of `details` + dashboard deep-link.
- Daily summary at 08:00 UTC is a separate scheduled task (uses `emit("daily_summary", ...)`) bypassing dedup.

#### 2.8.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Same alert emitted 100× in 15 min | First fires; rest suppressed; suppression count visible in dashboard | HLD §5.1 |
| 2 | SES throttle / 5xx | Logs error; does NOT crash bot; suppression key NOT recorded so retry can fire | Reliability |
| 3 | Empty `to_addrs` list | Raises `MisconfiguredAlertSinkError` at construction | Defensive |
| 4 | Daily summary | Bypasses dedup | REQ-OBS-005 |

---

### 2.9 `wallet/evm.py`

**File:** `python/claude_poly_bot/wallet/evm.py`
**Responsibility:** EVM key loading, signing primitives, balance queries (USDC + MATIC on Polygon).
**Requirements Covered:** REQ-WAL-001..009.
**Dependencies:** `eth-account`, `web3`.

#### 2.9.1 Public Interface

```python
@dataclass(frozen=True)
class EvmWallet:
    address: ChecksumAddress
    # private key never stored on the dataclass; held inside opaque signer object

class EvmWalletService:
    def __init__(self, secret_store: SecretStore, polygon_rpc_url: str): ...

    async def load_wallet(self, bot: Bot) -> EvmWallet:
        """Load bot's wallet from Secrets Manager. Returns address only."""

    async def get_usdc_balance(self, address: ChecksumAddress) -> Money: ...
    async def get_matic_balance(self, address: ChecksumAddress) -> Money: ...

    async def sign_clob_order(self, bot: Bot, order: dict) -> str:
        """Sign a Polymarket CLOB order (EIP-712). Returns signature hex.
        Used by the Polymarket Venue adapter."""

class WalletGenerator:
    """Used by the `setup-wallets` CLI."""
    @staticmethod
    def new() -> tuple[ChecksumAddress, str]:  # (address, private_key)
        ...
```

#### 2.9.2 Internal Implementation Details

- `load_wallet` retrieves private key from Secrets Manager at name `claude-poly-bot-{env}-wallet-{bot}`. Key cached in process memory but never logged or returned.
- `sign_clob_order` builds the typed-data dict per Polymarket's CLOB spec, signs with `eth_account.Account.sign_typed_data`.
- `WalletGenerator.new()` uses `eth_account.Account.create()` for entropy. Not async.
- All balance queries use a configurable Polygon RPC (default Alchemy via env). Retries on RPC errors via `retrying_db`-style helper.

#### 2.9.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Missing secret in Secrets Manager | `SecretNotFoundError` at load; bot startup fails fast | REQ-WAL-002 |
| 2 | Malformed private key (not 64 hex chars) | Validation error; bot startup fails | REQ-WAL-007 |
| 3 | RPC unreachable | Retried; if exhausted, exception propagates | Reliability |
| 4 | Balance below threshold | Caller (RISK or WAL daily check) emits alert (REQ-WAL-005) | REQ-WAL-005 |
| 5 | `sign_clob_order` called for a malformed order dict | Raises `InvalidOrderSignError` before signing | Defensive |

#### 2.9.4 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Security | Key never logged, never returned from public API | RedactProcessor + opaque signer |
| Auditability | Every signing op metricized | MetricsSink |
| Testability | Mock `SecretStore` returns test key in tests | Port-based injection |

---

### 2.10 `auth/`

**Files:** `python/claude_poly_bot/auth/{oauth.py, session.py}`
**Responsibility:** GitHub OAuth flow, session management, allowlist enforcement.
**Requirements Covered:** REQ-AUTH-001..007.
**Dependencies:** `authlib[httpx_client]`, `itsdangerous`/`jose` for JWT.

#### 2.10.1 Public Interface

**`oauth.py`:**

```python
class GitHubOAuth:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, allowlist_provider: Callable[[], Awaitable[list[str]]]): ...
    async def authorize_url(self, state: str) -> str: ...
    async def exchange_code(self, code: str, state: str) -> AuthResult: ...

class AuthResult(BaseModel):
    email: str
    github_login: str
    permitted: bool          # against allowlist
    primary_email_verified: bool
```

**`session.py`:**

```python
class SessionService:
    def __init__(self, secret: str, *, ttl_sec: int = 12 * 3600, clock: Clock): ...
    def issue(self, email: str, github_login: str) -> str:  # returns signed JWT
        ...
    def verify(self, token: str) -> Session | None:
        ...

class Session(BaseModel):
    email: str
    github_login: str
    issued_at: datetime
    expires_at: datetime
```

#### 2.10.2 Internal Implementation Details

- OAuth flow: state param is a CSRF token written to a short-lived session cookie before redirect; verified on callback.
- After `exchange_code`, query GitHub `/user/emails` to find primary verified email; check against allowlist (fetched fresh from `ConfigRepo`).
- `SessionService.issue` builds a JWT with `email`, `github_login`, `iat`, `exp`; signs with HS256 using `secret` from Secrets Manager.
- `verify` validates signature, checks expiry, and optionally re-checks allowlist (allowlist re-check happens at API-request middleware layer per HLD §5.4).

#### 2.10.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | OAuth state mismatch | Reject with HTTP 400; log auth_event `login_denied` | REQ-AUTH-007 |
| 2 | Email not in allowlist | Return AuthResult with `permitted=False`; do NOT issue session; HTTP 403 | REQ-AUTH-003 |
| 3 | Email is in allowlist but `primary_email_verified=False` | Reject; log denied | Security |
| 4 | Session JWT expired | `verify` returns None; UI redirects to login | REQ-AUTH-004 |
| 5 | Session JWT signature invalid | `verify` returns None; possible attack — log auth_event with details | Security |
| 6 | WebSocket upgrade with no cookie | `verify` returns None; close socket with code 1008 | HLD §5.4 |
| 7 | Allowlist updated to remove a user mid-session | Next API request re-checks allowlist; HTTP 403; cookie cleared | HLD §5.4 |

#### 2.10.4 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Security | CSRF state, allowlist, session signing, expiry, allowlist re-check on each request | All listed |
| Auditability | Every login attempt logged | `auth_events` table |

---

## Cross-Cutting — Batch 2

### Testing Strategy (Batch 2)

- **Unit tests** for pure logic (`config/schema.py` validation, `observability/logging.RedactProcessor`).
- **Integration tests** with **testcontainers Postgres** for every repo class — full migrations applied, real SQL.
- **OAuth tests** using `httpx_mock` to stub GitHub.
- **SES tests** using `moto` (boto3 mock).
- **Wallet tests** with a known test key (deterministic signature outputs).

### Self-Review Findings (Batch 2)

| # | Severity | Module | Finding | Resolution |
|---|---|---|---|---|
| 1 | MED | `storage/orm.py` | `risk_halts.lifted_at` mentioned but `RiskHaltRepo.lift_expired` doesn't appear in protocol — orphaned column | Confirmed in `domain/protocols.py` 1.3.1: `RiskHaltRepo.lift_expired(now)` exists. Cross-checked: ORM column is correct. No change needed; clarified note added. |
| 2 | MED | `config/service.py` | `confirmation_checksum` mechanism prevents UI races but adds friction; unspecified format on the UI side | Documented format: `sha256(field + str(new_value))[:8]`; UI computes client-side and includes in patch body. Tradeoff accepted — rare race vs friction. |
| 3 | MED | `observability/alerts.py` | Dedup state — Postgres `alert_dedup` table not in §2.2 ORM list | Add to ORM: `alert_dedup(key text PK, last_emitted_at timestamptz)`. (Treated as additive; will fold into Alembic 0001.) |
| 4 | LOW | `wallet/evm.py` | `get_usdc_balance` / `get_matic_balance` async but use a sync `web3.py` underneath — could cause event loop blocking on slow RPCs | Use `web3` async provider OR run via `asyncio.to_thread`; document choice in the impl. |
| 5 | LOW | `auth/session.py` | JWT secret rotation procedure not specified | Out of scope v1; documented as: rotation requires re-deploy and forces all sessions invalid; acceptable for solo operator. |

### Open Items (Batch 2)

- `alert_dedup` table to be added to `storage/orm.py`'s table list before Alembic migration (folded into 0001 initial).
- Confirm `aioboto3` vs `boto3` blocking-call strategy for SES + S3 (default to `aioboto3` for both; fall back to `asyncio.to_thread` if needed).
- `web3.py` async provider compatibility for Polygon RPC (Alchemy supports async; QuickNode does too).

---

## Batch 3 — Venue Adapters

4 modules: `venues/registry.py`, `venues/polymarket/`, `venues/alpaca/`, `venues/mocks/`.

These are concrete `Venue` Protocol implementations from Batch 1. They are the adapters that connect the pure domain to real external services.

**Dependency order within batch:** `mocks` (no deps); `registry` (depends on Venue protocol only); `polymarket` and `alpaca` (depend on `wallet/`, `storage/`, third-party SDKs).

---

### 3.1 `venues/registry.py`

**File:** `python/claude_poly_bot/venues/registry.py`
**Responsibility:** Look up `Venue` instances by name; iterate enabled venues per bot.
**Requirements Covered:** REQ-VEN-003, REQ-VEN-006.
**Dependencies:** `domain/protocols.py` (`Venue`), `domain/models.py` (`VenueName`).
**Depended On By:** scanner loop, bot loops, dashboard health endpoint, tests.

#### 3.1.1 Public Interface

```python
class VenueRegistry:
    def __init__(self, venues: dict[VenueName, Venue]):
        """Constructed at startup with all available Venue instances."""
        self._venues = venues

    def get(self, name: VenueName) -> Venue:
        """Raises VenueNotRegisteredError if unknown."""

    def list_all(self) -> list[Venue]: ...

    def list_enabled_for_bot(self, bot: Bot, config: ConfigService) -> list[Venue]:
        """Returns only the venues where the bot has venue-specific config rows
        (i.e., the venue is 'enabled' for that bot per REQ-VEN-006)."""

    async def health_check_all(self) -> dict[VenueName, HealthStatus]: ...
```

#### 3.1.2 Internal Implementation Details

- Construction wires up real venues (production) or fake venues (tests/local).
- `list_enabled_for_bot` reads the bot's effective config; a (bot, venue) pair without a row is treated as disabled.
- `health_check_all` runs all venues' health checks concurrently via `asyncio.gather(return_exceptions=True)`.

#### 3.1.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Lookup with unknown VenueName | `VenueNotRegisteredError` | REQ-VEN-003 |
| 2 | Bot has NO enabled venues | `list_enabled_for_bot` returns empty list; bot loops idle | REQ-VEN-006 |
| 3 | One venue's health-check raises | `health_check_all` returns it as `HealthStatus(status="error", error=str(e))` for that venue; others succeed | Reliability |

#### 3.1.4 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Extensibility | Add a 3rd venue = register new key | Dict-based registry |
| Testability | Construct with mocks for tests | Constructor injection |

---

### 3.2 `venues/polymarket/`

**Files:** `python/claude_poly_bot/venues/polymarket/{venue.py, stream.py}`
**Responsibility:** `Venue` implementation backed by `py-clob-client`. WebSocket order-book subscription.
**Requirements Covered:** REQ-POLY-001..008, REQ-VEN-002 (Polymarket variant), REQ-EXE-005, REQ-EXE-008, REQ-EXE-009, REQ-EXIT-009.
**Dependencies:** `py-clob-client`, `wallet/evm.py`, `storage/repos/orders.py`, `domain/protocols.py`.

#### 3.2.1 Public Interface — `venue.py`

```python
class PolymarketVenue:
    name = VenueName.POLYMARKET

    def __init__(
        self,
        bot: Bot,
        wallet: EvmWalletService,
        order_repo: OrderRepo,
        clock: Clock,
        metrics: MetricsSink,
        alerts: AlertSink,
        *,
        host_us: str = "https://clob.polymarket.com",
        host_intl: str = "https://clob.polymarket.com",  # same; geo enforced by wallet/account
        geo: Geo,
    ): ...

    # Implements every method on the Venue Protocol from §1.3.1
    async def list_active_markets(self, *, geo: Geo | None = None) -> list[PolymarketMarket]: ...
    async def get_market_data(self, market_id: str) -> PolymarketMarket: ...
    async def get_book(self, market_id: str) -> Book: ...
    async def place_order(self, spec: OrderSpec) -> Order: ...
    async def cancel_order(self, client_order_id: UUID) -> Order: ...
    async def get_order(self, client_order_id: UUID) -> Order | None: ...
    async def get_positions(self, bot: Bot) -> list[Position]: ...
    async def get_balance(self, bot: Bot) -> Balance: ...
    async def is_market_open(self) -> bool: return True   # always
    async def health_check(self) -> HealthStatus: ...
    async def subscribe_to_updates(self, market_ids: list[str]) -> AsyncIterator[BookUpdate]: ...
```

#### 3.2.2 Internal Implementation Details

**`list_active_markets`:**
- Calls `clob_client.get_markets(limit=500, active=True)`, paginates via cursor.
- Maps each into `PolymarketMarket` (fields: question, resolution_rules, resolution_time, outcomes, token_ids).
- Filters out markets resolving < `min_hours_to_resolution` from now (cheap pre-filter; main filter in `domain/scoring.py`).
- Caches per-call, no shared cache (scanner cadence is the cache).

**`place_order`** (per DD-020 store-before-submit):
1. Validate `spec.venue == polymarket`.
2. Call `order_repo.insert_pending(spec)` to persist `status=PENDING` row with `client_order_id`.
3. Convert `OrderSpec` → CLOB order dict (token_id, price, size, side).
4. Sign via `wallet.sign_clob_order(bot, order_dict)`.
5. Submit to `/orders`. Capture `venue_order_id`.
6. Call `order_repo.mark_submitted(client_order_id, venue_order_id, now)`.
7. Return `Order` with submitted status.
- If step 5 raises with ambiguous outcome (timeout, 5xx): query `/orders/{client_order_id}` (Polymarket supports client-id lookup); reconcile via `order_repo.update_status`.

**`cancel_order`:**
- Looks up `venue_order_id` from `order_repo.get(client_order_id)`.
- Calls `clob_client.cancel_order(venue_order_id)`.
- Updates `order_repo.update_status(..., status=CANCELLED)`.

**`get_order`:**
- Reconciliation primitive. Used at startup (HLD §5.6).
- Queries `/orders/{client_order_id}` directly; returns canonical state.

**`get_positions`:**
- Calls `/positions?user=<wallet_address>` on Polymarket.
- Returns positions matching this bot's wallet.

**`get_balance`:**
- USDC: `web3.eth.contract(USDC_POLYGON).functions.balanceOf(addr).call()`.
- MATIC: `web3.eth.get_balance(addr)`.
- Returns `Balance(usdc=..., matic=..., equity=None, buying_power=None)`.

**`subscribe_to_updates`** (`stream.py`):
- Connects to `wss://ws-subscriptions-clob.polymarket.com/ws/market`.
- Subscribes to all market_ids passed.
- Yields `BookUpdate` per message.
- Implements REQ-EXIT-008 / REQ-EXIT-011 reconnect: on disconnect, exponential backoff up to 30 s, re-subscribe; if reconnection fails 5×, alert.

#### 3.2.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | `place_order` venue returns 409 (duplicate client_order_id) | Reconcile with `get_order`; if matches our PENDING row, adopt as submitted | DD-020 |
| 2 | Order partially fills, then resolution time elapses | `get_order` returns FILLED with `filled_size < size`; position created at `filled_size` | REQ-EXIT-013 |
| 3 | Wallet has insufficient USDC at submission | Polymarket returns 4xx; map to `InsufficientBalanceError` | REQ-EXE-001 |
| 4 | Geo-restricted market for US wallet | Polymarket rejects; logged, `place_order` raises `OrderRejectedError` | REQ-VEN-006 |
| 5 | WebSocket dropped mid-volume-window | `stream.py` reconnects; missed events imply 0 trades for that interval (conservative) | REQ-EXIT-008, REQ-EXIT-011 |
| 6 | Polymarket adds a new market field that breaks our model | Pydantic `extra='forbid'` raises; logged + alerted; non-fatal (skip that market) | Reliability |
| 7 | Two consecutive `place_order` calls with same `client_order_id` | Repo's `insert_pending` raises `DuplicateClientOrderIdError` before submit | DD-020 |

#### 3.2.4 Error Handling

Maps SDK exceptions to domain exceptions:
- `py_clob_client.exceptions.PolyApiException` → `VenueUnreachableError` (5xx) or `OrderRejectedError` (4xx with rejection reason in body).
- Connection errors → `VenueUnreachableError`.
- Signature errors → `InvalidOrderSpecError`.

All errors emit `polymarket.error{type}` metric.

#### 3.2.5 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Reliability | Retries on 5xx; reconciliation on ambiguous submits | `place_order` flow |
| Observability | Every API call latency-tracked | MetricsSink |
| Correctness | Idempotent submit via `client_order_id` | DD-020 |
| Security | Wallet key never logged or returned | RedactProcessor + opaque signer |

---

### 3.3 `venues/alpaca/`

**Files:** `python/claude_poly_bot/venues/alpaca/{venue.py, stream.py, calendar.py}`
**Responsibility:** `Venue` implementation backed by `alpaca-py`. Market-hours gating. Streaming trade/quote feed.
**Requirements Covered:** REQ-ALPC-001..013, REQ-VEN-002 (Alpaca variant), REQ-EXE-006 (limit + market fallback), REQ-EXE-015 (bracket stop), REQ-EXIT-005, REQ-EXIT-006, REQ-EXIT-010, REQ-EXIT-014.
**Dependencies:** `alpaca-py`, `storage/repos/orders.py`, `domain/clock.py`.

#### 3.3.1 Public Interface — `venue.py`

```python
class AlpacaVenue:
    name = VenueName.ALPACA

    def __init__(
        self,
        bot: Bot,
        secret_store: SecretStore,
        order_repo: OrderRepo,
        clock: Clock,
        calendar: AlpacaCalendar,
        metrics: MetricsSink,
        alerts: AlertSink,
        *,
        env: str,                 # "dev" | "prod"
        live_mode: bool = False,  # paper vs live endpoint
        config: VenueAlpacaConfig,
    ): ...

    # Same Venue Protocol surface as PolymarketVenue
    async def list_active_markets(self, *, geo: Geo | None = None) -> list[AlpacaMarket]: ...
    async def get_market_data(self, market_id: str) -> AlpacaMarket: ...
    async def get_book(self, market_id: str) -> Book: ...
    async def place_order(self, spec: OrderSpec) -> Order: ...
    async def cancel_order(self, client_order_id: UUID) -> Order: ...
    async def get_order(self, client_order_id: UUID) -> Order | None: ...
    async def get_positions(self, bot: Bot) -> list[Position]: ...
    async def get_balance(self, bot: Bot) -> Balance: ...
    async def is_market_open(self) -> bool: ...
    async def health_check(self) -> HealthStatus: ...
    async def subscribe_to_updates(self, market_ids: list[str]) -> AsyncIterator[BookUpdate]: ...
```

#### 3.3.2 Public Interface — `calendar.py`

```python
class AlpacaCalendar:
    def __init__(self, alpaca_client, clock: Clock, refresh_interval_hours: int = 24): ...
    async def is_trading_day(self, date_et: date) -> bool: ...
    async def is_market_open(self, et_now: datetime) -> bool: ...
    async def market_close_today(self, et_now: datetime) -> datetime | None: ...
    async def refresh(self) -> None: ...   # Pulls /calendar from Alpaca
```

#### 3.3.3 Internal Implementation Details

**Endpoint selection** (REQ-ALPC-002, REQ-ALPC-005):
- If `live_mode`: connects to `api.alpaca.markets`.
- Else: connects to `paper-api.alpaca.markets`.
- Each pair has separate keys retrieved from Secrets Manager:
  - `claude-poly-bot-{env}-alpaca-{bot}-paper`
  - `claude-poly-bot-{env}-alpaca-{bot}-live`

**`list_active_markets`** (REQ-SCAN-012):
- Resolves universe based on `config.equity_universe`:
  - `sp500`: hardcoded list (or fetched from a static source committed to the repo)
  - `sp500_nasdaq100_etfs`: union (~600 tickers)
  - `custom`: `config.custom_universe`
- For each ticker, fetches `Asset` info via `alpaca-py` to get current status, sector, last earnings date.
- Filters out `tradable=False` or `fractionable=False`.

**`get_market_data` / `get_book`:**
- Uses `alpaca-py` market-data client to fetch latest quote (bid, ask, midpoint).
- For `get_book`: Alpaca exposes top-of-book only (Level 1); `Book.bids`/`asks` will have a single tuple each (best bid + best ask). Documented as a Polymarket-vs-Alpaca asymmetry.

**`place_order`** (per REQ-EXE-006, REQ-EXE-015, DD-020):
1. Validate spec.
2. `order_repo.insert_pending(spec)` with `client_order_id`.
3. If `is_entry`:
   a. Submit limit order at `spec.limit_price` with `time_in_force=DAY` and `client_order_id`.
   b. Spawn a background task: after `config.order_ttl_sec`, if order still PENDING/PARTIAL, cancel and submit a market order as fallback.
   c. After fill: submit a bracket-style child order using `OrderClass.OTO` with stop-loss at `position.stop_price`.
4. If exit (close): submit market order (no TTL fallback needed; we want to close).
5. `order_repo.mark_submitted` with venue_order_id.

**`is_market_open`:**
- Wraps `calendar.is_market_open(clock.et_now())`.
- Returns False outside 09:30–16:00 ET on a trading day, or on holidays/weekends.

**`get_balance`:**
- Calls Alpaca `/v2/account` → `equity`, `buying_power`, `daytrade_count`.
- Returns `Balance(equity=..., buying_power=..., day_trade_count=..., usdc=None, matic=None)`.

**`subscribe_to_updates`** (`stream.py`):
- Connects to Alpaca's stream (SIP if subscription supports it; else IEX fallback per REQ-ALPC-007).
- Subscribes to trades + quotes for given symbols.
- Yields `BookUpdate` (synthesizes a 1-level book from quote messages; volume from trade messages).
- Reconnect logic mirrors Polymarket (REQ-EXIT-011).

**`AlpacaCalendar.refresh`:**
- Pulls calendar via `alpaca_client.get_calendar()` for current month + next month.
- Caches in memory; refreshes every 24 hours or on-demand.
- Persists holidays as `set[date]` for fast lookup.

#### 3.3.4 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | `place_order` during market-closed | Returns `MarketClosedError` immediately; no API call | REQ-ALPC-006 |
| 2 | Limit order TTL expires unfilled, market fallback also fails (e.g., halt) | Both orders marked `EXPIRED`/`REJECTED`; alert fires | REQ-EXE-006 |
| 3 | Bracket stop-loss fills (price hit stop) | Position closed at stop price; ExitReason.STOP_LOSS | REQ-EXIT-005 |
| 4 | Position open at 15:55 ET on a trading day, `allow_overnight_holds=False` | EXIT loop submits market close; reason `EOD_FLATTEN` | REQ-EXIT-014 |
| 5 | PDT violation (4th day trade with equity < $25k) | `place_order` raises `PDTViolationError` (caller treats as a SKIP); RISK has already pre-filtered most cases | REQ-ALPC-012 |
| 6 | API key wrong tier (paper key sent to live endpoint) | 401 from Alpaca → `VenueUnreachableError` with permanent flag | REQ-ALPC-002 |
| 7 | Universe ticker delisted | `list_active_markets` filters `tradable=False`; logged | REQ-SCAN-012 |
| 8 | Holiday — `is_market_open` False all day | Scanner skips; existing positions: exit logic still runs (REST polling against last-close price) | REQ-EXIT-008, REQ-ALPC-006 |
| 9 | Stream missing for a symbol with open position | Falls back to REST polling at exit-loop cadence | REQ-EXIT-011 |
| 10 | Account is restricted by Alpaca | API returns 403; alert fires; bot pauses live trading on Alpaca | REQ-ALPC-010, REQ-ALPC-011 |

#### 3.3.5 Error Handling

Maps Alpaca SDK exceptions:
- `APIError(code=4xx)` → `OrderRejectedError` with reason
- `APIError(code=5xx)` → `VenueUnreachableError`
- `APIError(code=403)` → `AccountRestrictedError`
- Stream disconnect → falls through to reconnect loop; emits metric

#### 3.3.6 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Reliability | Bracket stops are server-side (Alpaca-managed) | OTO order class |
| Correctness | Market-hours gating prevents bad-state submissions | `is_market_open` predicate |
| Observability | Per-call latency + error metrics | MetricsSink |
| Security | Live keys distinct from paper keys; never crossed | Secret naming convention |

---

### 3.4 `venues/mocks/fake_venue.py`

**File:** `python/claude_poly_bot/venues/mocks/fake_venue.py`
**Responsibility:** In-memory `Venue` impl for tests + local DRY_RUN.
**Requirements Covered:** REQ-VEN-008, REQ-LLM-009 (testing), REQ-CICD-009 (offline tests).
**Dependencies:** `domain/protocols.py`, stdlib only.

#### 3.4.1 Public Interface

```python
class FakeVenue(Venue):
    def __init__(
        self,
        name: VenueName,
        clock: Clock,
        *,
        markets: list[Market] = [],
        books: dict[str, Book] = {},
        # Test hooks:
        fill_strategy: Literal["instant","delayed","reject","partial"] = "instant",
        reject_after: int | None = None,
        is_open: bool = True,
    ): ...

    # Implements full Venue Protocol with in-memory state.
    # Test methods:
    def add_market(self, market: Market) -> None: ...
    def set_book(self, market_id: str, book: Book) -> None: ...
    def push_book_update(self, market_id: str, update: BookUpdate) -> None: ...
    def trigger_fill(self, client_order_id: UUID, fill_price: Price, fill_size: Money) -> None: ...
    def force_disconnect(self) -> None: ...   # for testing reconnect logic
    def fast_forward_market_close(self) -> None: ...
```

#### 3.4.2 Internal Implementation Details

- All state in plain dicts/lists; no I/O.
- `fill_strategy` configures placement behavior:
  - `instant`: order goes from PENDING → FILLED immediately at limit_price.
  - `delayed`: stays PENDING until `trigger_fill()` is called.
  - `reject`: returns `OrderRejectedError`.
  - `partial`: fills `size/2` at limit_price; remainder stays PENDING.
- `subscribe_to_updates` yields `BookUpdate`s from an in-memory queue per market_id.
- `is_market_open` returns `self._is_open` configurable.

#### 3.4.3 Edge Cases — by design

This module's *purpose* is to emit edge cases on demand so the loops can be tested:
- Fill races
- Disconnect/reconnect
- Out-of-order events
- Rejected orders
- Market-closed scenarios

#### 3.4.4 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Testability | Drives test scenarios deterministically | Pure in-memory |
| Performance | Sub-microsecond ops | No I/O |

---

## Cross-Cutting — Batch 3

### Inter-Venue Protocol Conformance

A test asserts that `PolymarketVenue`, `AlpacaVenue`, and `FakeVenue` all satisfy `isinstance(v, Venue)` (runtime_checkable Protocol) and implement every method. CI fails if a Protocol method is added without all three impls updated.

### Self-Review Findings (Batch 3)

| # | Severity | Module | Finding | Resolution |
|---|---|---|---|---|
| 1 | MED | `venues/polymarket/venue.py` | `place_order` step 5 reconciles via `get_order` on ambiguous submit, but says `Polymarket supports client-id lookup` — verify in API docs | Documented as assumption to verify in impl phase; if not supported, fall back to listing recent orders by user and matching `client_order_id` field |
| 2 | MED | `venues/alpaca/venue.py` | Bracket stop-loss via `OrderClass.OTO` mentioned but the Alpaca SDK uses `BRACKET` for two-sided OCO (stop + take-profit). Our exits use other triggers, so we only want a stop. Should be `STOP` order linked to position, OR `OTO` with stop-only | Verify with alpaca-py: use `OTO` (one-triggers-other) where the trigger is the parent fill and the linked order is a stop. Documented as impl-phase verification. |
| 3 | MED | `venues/alpaca/venue.py` | `Book.bids`/`asks` from Alpaca will have only top-of-book (Level 1). `domain/scoring.score_alpaca_instrument` doesn't use book depth, so that's fine — but `EXIT.VOLUME_EXIT` for Alpaca needs trade-stream volume, not book depth. Consistent. | Confirmed; documented asymmetry in §3.3.3. |
| 4 | LOW | `venues/registry.py` | `list_enabled_for_bot` reads `ConfigService` per call; potentially slow at scale | Not a concern at our cadence (5 min); cached read in ConfigService is sufficient |
| 5 | LOW | `venues/alpaca/calendar.py` | Daily refresh might miss late calendar additions (rare) | Manual refresh available; safe-default behavior is to assume closed if uncertain |

### Open Items (Batch 3)

- Verify Polymarket CLOB supports `client_order_id` lookup endpoint (Finding #1).
- Verify exact Alpaca OTO/BRACKET semantics for stop-only attachment (Finding #2).
- Confirm SIP vs IEX feed access tier per REQ-ALPC-007 (depends on Alpaca subscription).

---

## Batch 4 — LLM Adapters

4 modules: `llm/anthropic_impl.py`, `llm/openai_impl.py`, `llm/mocks/fake_strategist.py`, `llm/prompts/`.

These are concrete `Strategist` Protocol implementations from Batch 1. They are the pivotal experimental surface — the *only* thing that differs between the two bots.

**Dependency order within batch:** `prompts/` (no deps); `mocks/` (depends on protocols); `anthropic_impl` and `openai_impl` (depend on prompts + Pydantic schemas + secret_store).

---

### 4.1 `llm/prompts/`

**Files:** `python/claude_poly_bot/llm/prompts/{polymarket,alpaca}/{base_rate,news,whale,unusual_volume,disposition,arbitrage,convergence,whale_copy,flow_copy}.md`
**Responsibility:** Prompt templates per (venue × check_type) and per (venue × sub_agent). Static content cached on Claude.
**Requirements Covered:** REQ-LLM-010, REQ-BRN-001..005.

#### 4.1.1 Layout

```
prompts/
  polymarket/
    base_rate.md
    news.md
    whale.md
    disposition.md
    arbitrage.md
    convergence.md
    whale_copy.md
  alpaca/
    base_rate.md
    news.md
    unusual_volume.md
    disposition.md
    arbitrage.md
    convergence.md
    flow_copy.md
  shared/
    response_schema.md   # JSON schema description appended to every prompt
```

#### 4.1.2 Prompt Anatomy

Each `.md` file is split with markers:

```
<!-- @system -->
You are a quantitative trading analyst...
[fixed instructions for this check + venue]
[response format schema reference: see shared/response_schema.md]
<!-- @user -->
Market: {{market.question}}
Resolution: {{market.resolution_rules}}
Book: bid={{book.bids[0]}}, ask={{book.asks[0]}}, mid={{book.midpoint}}
Score: gap={{score.gap}}, depth={{score.depth}}, hours={{score.hours}}
Target wallets holding: {{context.target_wallets_hits}}
Recent news (last 6h):
{% for snippet in context.recent_news %}
- {{snippet.title}} ({{snippet.source}})
{% endfor %}
```

- The `@system` block is the prompt-cacheable portion (REQ-BRN-010 / REQ-LLM-005). Identical across calls until prompt is updated.
- The `@user` block is per-call data; it varies and is NOT cached.
- Templates use Jinja2-style `{{ }}` and `{% %}` syntax.

#### 4.1.3 Public Interface

```python
class PromptRegistry:
    def __init__(self, prompts_dir: Path): ...
    def render(
        self,
        venue: VenueName,
        check_type: CheckType,
        sub_agent: SubAgent | None,
        context: dict,
    ) -> tuple[str, str]:    # (system_prompt, user_prompt)
        ...
    def list_available(self) -> list[tuple[VenueName, CheckType, SubAgent | None]]: ...
```

#### 4.1.4 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Missing template file for (venue, check_type, sub_agent) | `PromptNotFoundError` at render | REQ-BRN-001 |
| 2 | Template references undefined variable | Jinja2 `UndefinedError` raised; logged + alert | Defensive |
| 3 | Whale check rendered for Alpaca venue | `PromptNotFoundError` (correct — Alpaca uses unusual_volume); brain dispatches by venue | REQ-BRN-004 |

#### 4.1.5 Versioning

- Prompt content changes are tracked in git; commit hash of the prompt file is included in `decisions.prompt_version` for the comparison record.
- Prompt-version churn during the experiment is a known risk (R14 in HLD) — operator discipline.

---

### 4.2 `llm/anthropic_impl.py`

**File:** `python/claude_poly_bot/llm/anthropic_impl.py`
**Responsibility:** `Strategist` implementation backed by Anthropic Claude API.
**Requirements Covered:** REQ-LLM-001..010, REQ-BRN-008 (prompt caching), REQ-BRN-005 (JSON output), REQ-BRN-006 (malformed JSON retry), REQ-BRN-014 (rate-limit retry), REQ-BRN-015 (sustained-error halt), REQ-LLM-006 (web search per check).
**Dependencies:** `anthropic`, `llm/prompts/`, `domain/protocols.py`.

#### 4.2.1 Public Interface

```python
class AnthropicStrategist:
    bot = Bot.CLAUDE

    def __init__(
        self,
        api_key_provider: Callable[[], Awaitable[str]],
        prompts: PromptRegistry,
        config_service: ConfigService,
        clock: Clock,
        metrics: MetricsSink,
        decision_repo: DecisionRepo,
        *,
        default_model: str = "claude-opus-4-7",
        max_retries_malformed: int = 2,
        max_retries_rate_limit: int = 3,
        consecutive_error_threshold: int = 5,
        request_timeout_sec: int = 60,
    ): ...

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

    async def consecutive_error_count(self) -> int: ...   # for RISK module
```

#### 4.2.2 Internal Implementation Details

**`evaluate` flow:**

1. Resolve effective `model_id`:
   - If passed: use it.
   - Else: `config.models[check_type][venue]` if set; else `default_model`.
2. Render prompts via `prompts.render(venue, check_type, sub_agent, context.dict())`.
3. Build Anthropic request:
   ```python
   {
     "model": model_id,
     "system": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
     "messages": [{"role": "user", "content": user_prompt}],
     "max_tokens": 1024,
     "tools": [WEB_SEARCH_TOOL] if web_search else [],
     "tool_choice": {"type": "auto"} if web_search else None,
     "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"},
   }
   ```
4. Call `anthropic_client.messages.create(...)` with `request_timeout_sec`.
5. Parse response:
   - Extract assistant text.
   - Locate JSON block (regex: ```json…``` or first `{...}` block).
   - Parse via `CheckResult` Pydantic schema.
6. On parse failure: increment retries; loop back to step 4 with the error appended to the user prompt; max 2 retries (REQ-BRN-006).
7. On 429 rate-limit: exponential backoff (1, 2, 4 s); max 3 retries (REQ-BRN-014).
8. On other errors: bump consecutive-error counter; if ≥5, raise `LLMSustainedErrorsError` (REQ-BRN-015).
9. On success: reset consecutive-error counter; populate `CheckResult` with usage metadata; persist via `decision_repo.record(...)`; emit metrics; return.

**Web search tool spec:**

```python
WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web for recent news, prices, or factual data...",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}
```

When the model invokes the tool, the strategist:
- Calls a `WebSearchProvider` port (separate adapter; out of scope for this LLD section, but specified as: takes a query, returns top-N snippets).
- Returns the tool result back to the model in a follow-up message.
- Tool-use round trips are accounted for in `tokens_in/out` and `cost_usd`.

**Cost estimation:**
- Per Anthropic published prices for the model; cached input billed at 10% (per REQ-BRN-010 expectation).
- Cost computed at response time and stored on `CheckResult.cost_usd`.

#### 4.2.3 Edge Cases

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | Model returns valid JSON but wrong schema (e.g., verdict="MAYBE") | Pydantic `ValidationError`; counted as malformed; retried | REQ-BRN-006 |
| 2 | Response missing JSON entirely | Counted as malformed; retried | REQ-BRN-006 |
| 3 | 429 with `retry-after` header | Honor header value (preferred over backoff) | REQ-BRN-014 |
| 4 | Model invokes web_search but it's disabled for this check | Strategist refuses the tool call; returns SKIP with rationale "web search disabled" | REQ-LLM-006 |
| 5 | Request timeout (60s) | Counted as error; retried up to consecutive-error threshold | Reliability |
| 6 | Successful call after consecutive errors | Counter reset to 0 | REQ-BRN-015 |
| 7 | API key invalid (401) | Immediate failure (no retry); `LLMUnreachableError` raised | Security |
| 8 | Web search tool returns no results | Strategist returns the empty result to the model; model may SKIP based on "no information" | REQ-LLM-006 |
| 9 | Web search tool itself errors | Bubble up to model as a tool error; model decides to SKIP or proceed | Reliability |

#### 4.2.4 Error Handling

Exception hierarchy:
- `LLMUnreachableError` — 5xx / network / timeout
- `MalformedResponseError` — JSON parse / schema validation after retries
- `RateLimitExhaustedError` — 429 retries exhausted
- `LLMSustainedErrorsError` — 5+ consecutive errors

The first three return `CheckResult(verdict=SKIP, error=...)` per REQ-LLM-008.
The fourth propagates to the bot loop, which halts decisioning per REQ-BRN-015.

#### 4.2.5 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Reliability | Bounded retries; sustained-error halt | Retry loop |
| Cost | Prompt caching enabled by default | `cache_control` on system prompt |
| Observability | Every call's tokens, cost, latency, model logged | `decision_repo.record` |
| Determinism | Temperature default 0.0; configurable per check via Tier 1 | Config-driven |
| Testability | Mock via `FakeStrategist` (4.4) | Port-based |

---

### 4.3 `llm/openai_impl.py`

**File:** `python/claude_poly_bot/llm/openai_impl.py`
**Responsibility:** `Strategist` implementation backed by OpenAI API.
**Requirements Covered:** REQ-LLM-001..010 (OpenAI variant).
**Dependencies:** `openai`, `llm/prompts/`, `domain/protocols.py`.

#### 4.3.1 Public Interface

Mirrors `AnthropicStrategist` exactly (Protocol-driven), with `bot = Bot.OPENAI` and `default_model = "gpt-5"`.

#### 4.3.2 Internal Implementation Details

**`evaluate` flow** (mirrors §4.2.2 with provider-specific adjustments):

1. Same model-resolution logic.
2. Same prompt rendering.
3. OpenAI request:
   ```python
   {
     "model": model_id,
     "messages": [
       {"role": "system", "content": system_prompt},
       {"role": "user", "content": user_prompt},
     ],
     "response_format": {
       "type": "json_schema",
       "json_schema": {
         "name": "CheckResult",
         "schema": CheckResult.model_json_schema(),
         "strict": True,
       },
     },
     "tools": [WEB_SEARCH_TOOL] if web_search else None,
     "tool_choice": "auto" if web_search else None,
     "temperature": 0.0,
     "timeout": request_timeout_sec,
   }
   ```
4. With OpenAI structured-output mode (`strict: True`), responses are guaranteed-conformant — malformed parse should be rare. Still keep retry logic for resilience.
5. OpenAI does not have prompt caching equivalent to Anthropic's; cost trade-off accepted per HLD R1.
6. Web-search tool: OpenAI's web-search tool follows a similar tool-call shape to Anthropic; the strategist normalizes both providers behind the same `WebSearchProvider` adapter.
7. Rate-limit retry on 429 with `retry-after` header.
8. Same consecutive-error threshold as Anthropic.

**Cost estimation:**
- Per OpenAI published prices for `gpt-5` family; computed at response time.

#### 4.3.3 Edge Cases

Same edge cases as Anthropic strategist (§4.2.3) plus:

| # | Scenario | Expected Behavior | REQ Trace |
|---|---|---|---|
| 1 | OpenAI's `strict: True` rejects a model output that doesn't match schema | OpenAI returns 400 with details; counted as malformed; retried | REQ-BRN-006 |
| 2 | Token usage differs from Anthropic accounting (no separate cached count) | `tokens_cached = 0` always for OpenAI; `tokens_in/out` populated normally | REQ-BRN-007 |

#### 4.3.4 Provider Parity Concerns

To keep the Claude-vs-OpenAI comparison fair:

- **Same prompts** — both providers render the same templates from `llm/prompts/`. Provider-specific tweaks NOT permitted in v1.
- **Same temperature** — both default to 0.0 unless configured.
- **Same retry budgets** — same `max_retries_*` constants.
- **Same web-search policy** — same checks have web-search enabled.
- **Same JSON schema** — both use the exact `CheckResult` schema.
- **Different model selection allowed** — that's the point.

A test enforces these parities by asserting both strategists' `evaluate()` produces the same SHAPE of request given the same inputs (different content okay; same wire structure required).

#### 4.3.5 NFRs

Same as AnthropicStrategist (§4.2.5), with the cost line adjusted: no prompt caching → higher per-call cost relative to Claude.

---

### 4.4 `llm/mocks/fake_strategist.py`

**File:** `python/claude_poly_bot/llm/mocks/fake_strategist.py`
**Responsibility:** Scripted `Strategist` for tests + local DRY_RUN.
**Requirements Covered:** REQ-LLM-009.
**Dependencies:** `domain/protocols.py`, stdlib.

#### 4.4.1 Public Interface

```python
class FakeStrategist(Strategist):
    bot: Bot

    def __init__(self, bot: Bot, *, clock: Clock): ...

    def queue_response(
        self,
        check_type: CheckType,
        venue: VenueName,
        verdict: Verdict,
        confidence: Probability,
        p_win: Probability,
        rationale: str = "fake",
        sub_agent: SubAgent | None = None,
        target_price: Price | None = None,
        stop_price: Price | None = None,
        horizon_hours: int | None = None,
        delay_ms: int = 0,
        raise_error: Exception | None = None,
    ) -> None: ...

    def queue_response_for_market(self, market_id: str, **kwargs) -> None: ...

    async def evaluate(...) -> CheckResult: ...
    async def consecutive_error_count(self) -> int: return 0
```

#### 4.4.2 Internal Implementation Details

- Maintains a FIFO queue of scripted responses keyed by (check_type, venue, sub_agent) and optionally by market_id.
- `evaluate` pops from the queue; if empty, returns a default SKIP response with rationale "no script".
- `delay_ms` lets tests exercise timing concerns.
- `raise_error` lets tests exercise error paths.

#### 4.4.3 Use Cases

- **Bot loop integration tests**: queue 4 BUYs across the 4 checks → expect a thesis.
- **Sub-agent consensus tests**: queue 2 BUY + 1 SKIP across 3 sub-agents → expect HALF size.
- **Sustained-error halt tests**: queue 5 consecutive errors → expect bot halt.
- **Local DRY_RUN demo**: a default scripted "alternating BUY/SKIP" pattern for the operator to exercise the dashboard without API costs.

#### 4.4.4 NFRs

| NFR | Requirement | Addressed by |
|---|---|---|
| Testability | Deterministic outputs | Scripted queue |
| Performance | Sub-microsecond | In-memory |

---

## Cross-Cutting — Batch 4

### Strategist Conformance

A test asserts `AnthropicStrategist`, `OpenAIStrategist`, `FakeStrategist` all satisfy `isinstance(s, Strategist)` and pass the parity checks (§4.3.4).

### Cost Comparison Methodology

For the Claude-vs-OpenAI experiment:
- Every `CheckResult` records `cost_usd`, `tokens_in`, `tokens_out`, `tokens_cached`, `latency_ms`, `model_id`, `prompt_version` (git hash of the prompt file).
- Dashboard surfaces side-by-side cost-per-thesis and cost-per-trade.
- The fairness premise: same prompts + same data + same loop logic → spend differences reflect provider efficiency, not architecture choices.

### Self-Review Findings (Batch 4)

| # | Severity | Module | Finding | Resolution |
|---|---|---|---|---|
| 1 | MED | `llm/anthropic_impl.py` | Web search "tool refusal when disabled for this check" — but if the model invokes a disabled tool, modeling response as SKIP loses the actual model output. Better: don't expose the tool at all when disabled (don't include in `tools` list) | Per §4.2.2 step 3, `tools=[WEB_SEARCH_TOOL] if web_search else []` already excludes the tool when disabled — model can't invoke it. Edge case 4 was misleading; revised: edge case applies when `web_search=False` is passed but tool somehow leaks (defensive only). |
| 2 | MED | `llm/openai_impl.py` | OpenAI structured outputs require schema in OpenAPI 3.0 dialect (with restrictions); Pydantic's `model_json_schema()` is JSON Schema 2020-12 — may need adapter | Documented as impl-phase concern; the OpenAI SDK has a helper or we wrap manually. If incompatible, fall back to OpenAI's `tools` mode with a single function whose parameters are the schema |
| 3 | MED | `llm/prompts/` | `decisions.prompt_version` requires committing all prompt files to git AND reading the file's last-commit hash at render time — moderately complex for a metadata field | Acceptable cost for traceability. Implementation: `git log -n 1 --format=%H -- {prompt_file}` cached at startup, refreshed if prompt files mtime changes |
| 4 | LOW | `llm/anthropic_impl.py` | `consecutive_error_count` is per-strategist instance; if the bot creates a new instance per loop iteration, the counter resets | Specify: one strategist instance per bot per process, lifetime = process. Documented in §4.2.1 (constructor expectation) |
| 5 | LOW | `llm/anthropic_impl.py` | Web search beta header may change; provider-specific betas leak into our adapter | Wrap betas in a `class AnthropicCapabilities: web_search_beta: str = "..."`; one place to update |

### Open Items (Batch 4)

- Verify OpenAI structured-output schema dialect compatibility with `model_json_schema()` (Finding #2).
- Define `WebSearchProvider` adapter interface (deferred — not required for v1 if we use each provider's native search; may need our own if we add a 3rd provider later).
- Decide on temperature: 0.0 deterministic vs slight (0.2) for diversity. Default 0.0 specified; Tier 1 configurable per check.
