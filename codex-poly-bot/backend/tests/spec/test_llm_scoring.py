"""Red-phase tests for LLM Scoring."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain import (
    Environment,
    Instrument,
    InstrumentType,
    ModelProvider,
    ScoringOutput,
    Venue,
)
from app.services import (
    ActorContext,
    AuthService,
    ClaudeMessagesProvider,
    ConfigPatchOperation,
    ConfigService,
    FakeLlmProvider,
    LlmBudgetLedger,
    LlmProviderCredential,
    ScoringFailure,
    OpenAIResponsesProvider,
    build_scoring_queue,
    check_scoring_failure_gate,
    reconcile_scoring_cost,
    record_provider_cost,
    run_llm_scoring,
)


def prediction_instrument() -> Instrument:
    return Instrument(
        venue=Venue.POLYMARKET_US,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id="market-1",
        outcome_id="yes",
        display_name="Will the event happen?",
    )


def scoring_response_text(*, thesis: str, cost: str = "0.01") -> str:
    return (
        "{"
        f"\"output_thesis\":\"{thesis}\","
        "\"confidence\":\"0.70\","
        "\"estimated_probability\":\"0.60\","
        f"\"cost_estimate\":\"{cost}\""
        "}"
    )


class RecordingProviderTransport:
    def __init__(self, responses: tuple[dict[str, Any], ...]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        return self.responses.pop(0)


def test_req_llm_001_01_eligible_polymarket_alpaca_candidates_scoring_runs_both_claude() -> None:
    """TST-REQ-LLM-001-01: Validates REQ-LLM-001

    Given: eligible Polymarket and Alpaca candidates
    When: scoring runs
    Then: both Claude and OpenAI providers evaluate the candidates
    """
    providers = (
        FakeLlmProvider(ModelProvider.CLAUDE),
        FakeLlmProvider(ModelProvider.OPENAI),
    )

    result = run_llm_scoring((prediction_instrument(),), providers)

    assert result.ok
    assert {score.model_provider for score in result.scores} == {
        ModelProvider.CLAUDE,
        ModelProvider.OPENAI,
    }
    assert providers[0].call_count == 1
    assert providers[1].call_count == 1


def test_req_llm_001_03_configured_credentials_send_scoring_to_openai_and_claude_adapters() -> None:
    """TST-REQ-LLM-001-03: Validates REQ-LLM-001

    Given: configured OpenAI and Claude credentials are present
    When: eligible scoring requests run through provider adapters
    Then: both providers receive scoring requests through their external API boundary
    """
    openai_transport = RecordingProviderTransport(
        (
            {
                "output_text": scoring_response_text(
                    thesis="OpenAI sees positive expected value",
                    cost="0.015",
                )
            },
        )
    )
    claude_transport = RecordingProviderTransport(
        (
            {
                "content": [
                    {
                        "type": "text",
                        "text": scoring_response_text(
                            thesis="Claude sees positive expected value",
                            cost="0.012",
                        ),
                    }
                ]
            },
        )
    )
    providers = (
        ClaudeMessagesProvider(
            credential=LlmProviderCredential(api_key="claude-test-key"),
            transport=claude_transport,
            remaining_budget=Decimal("1.00"),
        ),
        OpenAIResponsesProvider(
            credential=LlmProviderCredential(api_key="openai-test-key"),
            transport=openai_transport,
            remaining_budget=Decimal("1.00"),
        ),
    )

    result = run_llm_scoring((prediction_instrument(),), providers)

    assert result.ok
    assert {score.model_provider for score in result.scores} == {
        ModelProvider.CLAUDE,
        ModelProvider.OPENAI,
    }
    assert openai_transport.calls[0]["url"] == "https://api.openai.com/v1/responses"
    assert openai_transport.calls[0]["headers"]["Authorization"] == "Bearer openai-test-key"
    assert openai_transport.calls[0]["payload"]["model"] == "gpt-5"
    assert claude_transport.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert claude_transport.calls[0]["headers"]["x-api-key"] == "claude-test-key"
    assert claude_transport.calls[0]["payload"]["model"] == "claude-opus-4-1-20250805"


def test_req_llm_001_02_one_model_provider_disabled_out_budget_scoring_runs() -> None:
    """TST-REQ-LLM-001-02: Validates REQ-LLM-001

    Given: one model provider is disabled or out of budget
    When: scoring runs
    Then: eligible remaining providers continue independently
    """
    providers = (
        FakeLlmProvider(ModelProvider.CLAUDE, remaining_budget=Decimal("0")),
        FakeLlmProvider(ModelProvider.OPENAI, remaining_budget=Decimal("1.00")),
    )

    result = run_llm_scoring((prediction_instrument(),), providers)

    assert result.ok
    assert tuple(score.model_provider for score in result.scores) == (ModelProvider.OPENAI,)
    assert result.skipped_providers == (ModelProvider.CLAUDE,)


def test_req_llm_002_01_claude_openai_budget_settings_scoring_costs_recorded_each() -> None:
    """TST-REQ-LLM-002-01: Validates REQ-LLM-002

    Given: Claude and OpenAI budget settings
    When: scoring costs are recorded
    Then: each provider budget is tracked separately
    """
    ledger = LlmBudgetLedger(
        budgets={
            ModelProvider.CLAUDE: Decimal("1.00"),
            ModelProvider.OPENAI: Decimal("1.00"),
        }
    )

    claude = record_provider_cost(
        ledger,
        ModelProvider.CLAUDE,
        ModelProvider.CLAUDE,
        Decimal("0.25"),
    )
    openai = record_provider_cost(
        ledger,
        ModelProvider.OPENAI,
        ModelProvider.OPENAI,
        Decimal("0.10"),
    )

    assert claude.ok
    assert openai.ok
    assert ledger.spent[ModelProvider.CLAUDE] == Decimal("0.25")
    assert ledger.spent[ModelProvider.OPENAI] == Decimal("0.10")


def test_req_llm_002_03_provider_cost_returned_or_estimated_reconciles_budget_status() -> None:
    """TST-REQ-LLM-002-03: Validates REQ-LLM-002

    Given: provider cost is returned or estimated
    When: budget ledger reconciliation runs
    Then: cost entries are recorded and structured budget status is emitted
    """
    ledger = LlmBudgetLedger(
        budgets={
            ModelProvider.OPENAI: Decimal("1.00"),
            ModelProvider.CLAUDE: Decimal("1.00"),
        }
    )
    openai_score = ScoringOutput(
        model_provider=ModelProvider.OPENAI,
        prompt_version="pm-v1",
        input_summary="market context",
        output_thesis="positive expected value",
        confidence="0.70",
        estimated_probability="0.60",
        cost_estimate="0.015",
        instrument=prediction_instrument(),
    )
    claude_score = ScoringOutput(
        model_provider=ModelProvider.CLAUDE,
        prompt_version="pm-v1",
        input_summary="market context",
        output_thesis="positive expected value",
        confidence="0.71",
        estimated_probability="0.61",
        cost_estimate="0.012",
        instrument=prediction_instrument(),
    )

    returned = reconcile_scoring_cost(
        ledger,
        openai_score,
        actual_cost=Decimal("0.014"),
    )
    estimated = reconcile_scoring_cost(ledger, claude_score)

    assert returned.ok
    assert returned.payload["cost_source"] == "actual"
    assert returned.payload["budget_status"]["remaining"] == "0.986"
    assert estimated.ok
    assert estimated.payload["cost_source"] == "estimated"
    assert estimated.payload["budget_status"]["remaining"] == "0.988"


def test_req_llm_002_02_scoring_event_attempts_consume_wrong_provider_budget_budget() -> None:
    """TST-REQ-LLM-002-02: Validates REQ-LLM-002

    Given: a scoring event attempts to consume the wrong provider budget
    When: budget accounting runs
    Then: the event is rejected or corrected before persistence
    """
    ledger = LlmBudgetLedger(budgets={ModelProvider.CLAUDE: Decimal("1.00")})

    result = record_provider_cost(
        ledger,
        ModelProvider.CLAUDE,
        ModelProvider.OPENAI,
        Decimal("0.10"),
    )

    assert not result.ok
    assert result.refusal_reason == "provider budget mismatch"
    assert ledger.spent == {}


def test_req_llm_003_01_successful_model_evaluation_score_persisted_provider_prompt_version() -> None:
    """TST-REQ-LLM-003-01: Validates REQ-LLM-003

    Given: a successful model evaluation
    When: the score is persisted
    Then: provider, prompt version, input summary, thesis, confidence, probability, and cost estimate are stored
    """
    score = ScoringOutput(
        model_provider=ModelProvider.CLAUDE,
        prompt_version="pm-v1",
        input_summary="market and price context",
        output_thesis="price is below estimated probability",
        confidence="0.71",
        estimated_probability="0.64",
        cost_estimate="0.013",
        instrument=prediction_instrument(),
    )

    assert score.model_provider == ModelProvider.CLAUDE
    assert score.prompt_version == "pm-v1"
    assert score.input_summary
    assert score.output_thesis
    assert score.confidence == Decimal("0.71")
    assert score.estimated_probability == Decimal("0.64")
    assert score.cost_estimate == Decimal("0.013")
    assert score.instrument.identifier == "market-1:yes"
    assert score.created_at is not None


def test_req_llm_003_02_model_response_missing_required_scoring_fields_parsing_runs() -> None:
    """TST-REQ-LLM-003-02: Validates REQ-LLM-003

    Given: a model response missing required scoring fields
    When: parsing runs
    Then: the score is marked failed and no live order can use it
    """
    with pytest.raises(ValidationError):
        ScoringOutput(
            model_provider=ModelProvider.CLAUDE,
            prompt_version="pm-v1",
            input_summary="market and price context",
            output_thesis="",
            confidence="1.2",
            estimated_probability="0.64",
            cost_estimate="0.013",
            instrument=prediction_instrument(),
        )


def test_req_llm_004_01_model_budget_exhausted_scoring_queues_built_no_new() -> None:
    """TST-REQ-LLM-004-01: Validates REQ-LLM-004

    Given: a model budget is exhausted
    When: scoring queues are built
    Then: no new requests are sent to that model
    """
    result = build_scoring_queue(
        (prediction_instrument(),),
        (FakeLlmProvider(ModelProvider.CLAUDE, remaining_budget=Decimal("0")),),
    )

    assert result.requests == ()
    assert result.skipped_providers == (ModelProvider.CLAUDE,)


def test_req_llm_004_02_claude_exhausted_openai_budget_scoring_runs_openai_continues() -> None:
    """TST-REQ-LLM-004-02: Validates REQ-LLM-004

    Given: Claude is exhausted and OpenAI has budget
    When: scoring runs
    Then: OpenAI continues while Claude is skipped
    """
    providers = (
        FakeLlmProvider(ModelProvider.CLAUDE, remaining_budget=Decimal("0")),
        FakeLlmProvider(ModelProvider.OPENAI, remaining_budget=Decimal("1.00")),
    )

    result = run_llm_scoring((prediction_instrument(),), providers)

    assert tuple(score.model_provider for score in result.scores) == (ModelProvider.OPENAI,)
    assert result.skipped_providers == (ModelProvider.CLAUDE,)


def test_req_llm_004_03_budget_exhausted_stops_one_external_provider_other_continues() -> None:
    """TST-REQ-LLM-004-03: Validates REQ-LLM-004

    Given: OpenAI is exhausted and Claude has budget
    When: scoring runs through external provider adapters
    Then: OpenAI receives no request and Claude continues independently
    """
    openai_transport = RecordingProviderTransport(
        ({"output_text": scoring_response_text(thesis="should not be called")},)
    )
    claude_transport = RecordingProviderTransport(
        (
            {
                "content": [
                    {
                        "type": "text",
                        "text": scoring_response_text(thesis="Claude continues"),
                    }
                ]
            },
        )
    )
    providers = (
        OpenAIResponsesProvider(
            credential=LlmProviderCredential(api_key="openai-test-key"),
            transport=openai_transport,
            remaining_budget=Decimal("0"),
        ),
        ClaudeMessagesProvider(
            credential=LlmProviderCredential(api_key="claude-test-key"),
            transport=claude_transport,
            remaining_budget=Decimal("1.00"),
        ),
    )

    result = run_llm_scoring((prediction_instrument(),), providers)

    assert tuple(score.model_provider for score in result.scores) == (ModelProvider.CLAUDE,)
    assert result.skipped_providers == (ModelProvider.OPENAI,)
    assert openai_transport.calls == []
    assert len(claude_transport.calls) == 1


def test_req_llm_005_01_llm_scoring_succeeds_model_market_execution_eligibility_checked() -> None:
    """TST-REQ-LLM-005-01: Validates REQ-LLM-005

    Given: LLM scoring succeeds for a model and market
    When: execution eligibility is checked
    Then: the scoring failure gate passes
    """
    result = check_scoring_failure_gate(
        failures=(),
        model_provider=ModelProvider.CLAUDE,
        instrument=prediction_instrument(),
    )

    assert result.ok


def test_req_llm_005_02_llm_scoring_fails_model_market_execution_eligibility_checked() -> None:
    """TST-REQ-LLM-005-02: Validates REQ-LLM-005

    Given: LLM scoring fails for a model and market
    When: execution eligibility is checked in the same loop
    Then: live orders are blocked for that pair
    """
    instrument = prediction_instrument()
    result = check_scoring_failure_gate(
        failures=(
            ScoringFailure(
                model_provider=ModelProvider.CLAUDE,
                instrument_id=instrument.identifier,
                reason="provider timeout",
            ),
        ),
        model_provider=ModelProvider.CLAUDE,
        instrument=instrument,
    )

    assert not result.ok
    assert result.refusal_reason == "SCORING_MISSING_OR_FAILED"


def test_req_llm_006_01_authorized_dashboard_user_changes_model_budgets_scoring_settings() -> None:
    """TST-REQ-LLM-006-01: Validates REQ-LLM-006

    Given: an authorized dashboard user changes model budgets or scoring settings
    When: the update is saved
    Then: the new scoring config is persisted
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)
    result = service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=auth.authorize_request(auth.create_session_token(username="yaw")),
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[
            ConfigPatchOperation("replace", "llm.claude.budget_usd", "30.00"),
            ConfigPatchOperation("replace", "llm.claude.settings.temperature", "0.2"),
        ],
    )
    payload = result.mutation.config_version["payload"]["llm"]["claude"]

    assert payload["budget_usd"] == "30.00"
    assert payload["settings"]["temperature"] == "0.2"


def test_req_llm_007_01_scoring_config_changes_saved_next_trading_loop_starts() -> None:
    """TST-REQ-LLM-007-01: Validates REQ-LLM-007

    Given: scoring config changes are saved
    When: the next trading loop starts
    Then: the updated settings are used
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)
    service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=auth.authorize_request(auth.create_session_token(username="yaw")),
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[ConfigPatchOperation("replace", "llm.openai.settings.prompt_version", "v2")],
    )
    snapshot = service.config_for_next_loop(Environment.DEVELOPMENT)

    assert snapshot.snapshot.payload["llm"]["openai"]["settings"]["prompt_version"] == "v2"
