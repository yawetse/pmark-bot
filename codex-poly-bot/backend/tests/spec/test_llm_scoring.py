"""Red-phase tests for LLM Scoring."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import Environment, Instrument, InstrumentType, ModelProvider, ScoringOutput, Venue
from app.services import ActorContext, AuthService, ConfigPatchOperation, ConfigService
from tests.spec.helpers import pending


def prediction_instrument() -> Instrument:
    return Instrument(
        venue=Venue.POLYMARKET_US,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id="market-1",
        outcome_id="yes",
        display_name="Will the event happen?",
    )


def test_req_llm_001_01_eligible_polymarket_alpaca_candidates_scoring_runs_both_claude() -> None:
    """TST-REQ-LLM-001-01: Validates REQ-LLM-001

    Given: eligible Polymarket and Alpaca candidates
    When: scoring runs
    Then: both Claude and OpenAI providers evaluate the candidates
    """
    pending("TST-REQ-LLM-001-01", "REQ-LLM-001")

def test_req_llm_001_02_one_model_provider_disabled_out_budget_scoring_runs() -> None:
    """TST-REQ-LLM-001-02: Validates REQ-LLM-001

    Given: one model provider is disabled or out of budget
    When: scoring runs
    Then: eligible remaining providers continue independently
    """
    pending("TST-REQ-LLM-001-02", "REQ-LLM-001")

def test_req_llm_002_01_claude_openai_budget_settings_scoring_costs_recorded_each() -> None:
    """TST-REQ-LLM-002-01: Validates REQ-LLM-002

    Given: Claude and OpenAI budget settings
    When: scoring costs are recorded
    Then: each provider budget is tracked separately
    """
    pending("TST-REQ-LLM-002-01", "REQ-LLM-002")

def test_req_llm_002_02_scoring_event_attempts_consume_wrong_provider_budget_budget() -> None:
    """TST-REQ-LLM-002-02: Validates REQ-LLM-002

    Given: a scoring event attempts to consume the wrong provider budget
    When: budget accounting runs
    Then: the event is rejected or corrected before persistence
    """
    pending("TST-REQ-LLM-002-02", "REQ-LLM-002")

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
    pending("TST-REQ-LLM-004-01", "REQ-LLM-004")

def test_req_llm_004_02_claude_exhausted_openai_budget_scoring_runs_openai_continues() -> None:
    """TST-REQ-LLM-004-02: Validates REQ-LLM-004

    Given: Claude is exhausted and OpenAI has budget
    When: scoring runs
    Then: OpenAI continues while Claude is skipped
    """
    pending("TST-REQ-LLM-004-02", "REQ-LLM-004")

def test_req_llm_005_01_llm_scoring_succeeds_model_market_execution_eligibility_checked() -> None:
    """TST-REQ-LLM-005-01: Validates REQ-LLM-005

    Given: LLM scoring succeeds for a model and market
    When: execution eligibility is checked
    Then: the scoring failure gate passes
    """
    pending("TST-REQ-LLM-005-01", "REQ-LLM-005")

def test_req_llm_005_02_llm_scoring_fails_model_market_execution_eligibility_checked() -> None:
    """TST-REQ-LLM-005-02: Validates REQ-LLM-005

    Given: LLM scoring fails for a model and market
    When: execution eligibility is checked in the same loop
    Then: live orders are blocked for that pair
    """
    pending("TST-REQ-LLM-005-02", "REQ-LLM-005")

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
