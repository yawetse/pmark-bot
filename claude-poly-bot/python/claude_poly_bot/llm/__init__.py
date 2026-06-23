"""LLM strategist adapters and prompt registry.

`Strategist` protocol lives in `domain.protocols`; implementations live
under this package.
"""

from claude_poly_bot.llm.anthropic_impl import AnthropicStrategist
from claude_poly_bot.llm.mocks.fake_strategist import FakeStrategist
from claude_poly_bot.llm.openai_impl import OpenAIStrategist
from claude_poly_bot.llm.prompts import PromptRegistry, default_prompts_dir

__all__ = [
    "AnthropicStrategist",
    "FakeStrategist",
    "OpenAIStrategist",
    "PromptRegistry",
    "default_prompts_dir",
]
