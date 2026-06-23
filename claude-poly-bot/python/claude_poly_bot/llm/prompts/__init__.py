"""Prompt template registry for LLM strategists.

Each venue has its own subdirectory of .md templates. The PromptRegistry
loads, parses, and renders them on demand.
"""

from pathlib import Path

from claude_poly_bot.llm.prompts.registry import (
    PromptNotFoundError,
    PromptRegistry,
    PromptShapeError,
)

__all__ = [
    "PromptNotFoundError",
    "PromptRegistry",
    "PromptShapeError",
    "default_prompts_dir",
]


def default_prompts_dir() -> Path:
    """Path to the prompts/ directory shipped with the package."""
    return Path(__file__).parent
