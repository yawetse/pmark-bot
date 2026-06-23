"""Prompt registry — loads and renders venue/check_type/sub_agent templates.

Each .md file is split into a `@system` block (cacheable across calls) and a
`@user` block (per-call data). Sub-agent prompts receive `check_results` in
their render context so they can see what the brain decided.

Traces: REQ-LLM-010 (per-venue prompts), REQ-BRN-001, REQ-BRN-010 (system
prompt is the cacheable portion).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, StrictUndefined, Template

from claude_poly_bot.domain.models import CheckType, SubAgent, VenueName

# Splitter marker — `<!-- @system -->` / `<!-- @user -->` lines.
_BLOCK_RE = re.compile(r"^<!--\s*@(system|user)\s*-->\s*$", re.MULTILINE)


class PromptNotFoundError(LookupError):
    """Raised when no template exists for (venue, check_type[, sub_agent])."""


class PromptShapeError(ValueError):
    """Raised when a template file is missing the system/user markers."""


@dataclass(frozen=True)
class _Compiled:
    system: Template
    user: Template


class PromptRegistry:
    """Loads .md templates from `prompts_dir` lazily and caches compiled
    Jinja2 templates per (venue, check_type, sub_agent).
    """

    def __init__(self, prompts_dir: Path) -> None:
        self._dir = prompts_dir
        # Prompts are rendered as plaintext for the LLM, never as HTML — HTML
        # escaping would corrupt the JSON examples and angle brackets in
        # rationale text. autoescape is intentionally off.
        self._env = Environment(
            autoescape=False,  # noqa: S701 - LLM prompt rendering, not HTML
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        self._cache: dict[tuple[VenueName, CheckType | None, SubAgent | None], _Compiled] = {}
        self._shared_schema: str | None = None

    def render(
        self,
        venue: VenueName,
        check_type: CheckType,
        sub_agent: SubAgent | None,
        context: dict[str, object],
    ) -> tuple[str, str]:
        """Return `(system_prompt, user_prompt)` for the given dispatch.

        Sub-agent templates use the venue's BASE_RATE check_type slot for
        path lookup — sub-agent prompt files live alongside check prompts
        keyed by their own name (`arbitrage.md`, `convergence.md`, etc.).
        """
        compiled = self._load(venue, check_type, sub_agent)
        ctx = {**context, "response_schema": self._load_shared_schema()}
        return compiled.system.render(**ctx), compiled.user.render(**ctx)

    def list_available(self) -> list[tuple[VenueName, CheckType, SubAgent | None]]:
        """Enumerate every (venue, check_type, sub_agent) the directory provides.

        Walks the disk once per call — intended for startup health checks,
        not the request path.
        """
        out: list[tuple[VenueName, CheckType, SubAgent | None]] = []
        for venue in VenueName:
            venue_dir = self._dir / venue.value
            if not venue_dir.exists():
                continue
            for path in sorted(venue_dir.glob("*.md")):
                stem = path.stem
                check, sub = _classify_stem(stem)
                if check is None and sub is None:
                    continue
                if sub is not None:
                    # Sub-agent prompt — pair it with BASE_RATE as the
                    # check_type slot (registry convention; sub_agent is
                    # the disambiguator).
                    out.append((venue, CheckType.BASE_RATE, sub))
                elif check is not None:
                    out.append((venue, check, None))
        return out

    # ---- internals ----

    def _load(
        self,
        venue: VenueName,
        check_type: CheckType,
        sub_agent: SubAgent | None,
    ) -> _Compiled:
        key = (venue, check_type if sub_agent is None else None, sub_agent)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        stem = sub_agent.value if sub_agent is not None else check_type.value
        path = self._dir / venue.value / f"{stem}.md"
        if not path.exists():
            raise PromptNotFoundError(
                f"No prompt template for venue={venue.value} "
                f"check_type={check_type.value} sub_agent={sub_agent}"
            )

        system_src, user_src = _split_blocks(path.read_text(encoding="utf-8"), path)
        compiled = _Compiled(
            system=self._env.from_string(system_src),
            user=self._env.from_string(user_src),
        )
        self._cache[key] = compiled
        return compiled

    def _load_shared_schema(self) -> str:
        if self._shared_schema is None:
            path = self._dir / "shared" / "response_schema.md"
            if not path.exists():
                raise PromptNotFoundError(f"Missing shared response schema at {path}")
            self._shared_schema = path.read_text(encoding="utf-8").strip()
        return self._shared_schema


def _split_blocks(text: str, path: Path) -> tuple[str, str]:
    """Split a .md file at `<!-- @system -->` / `<!-- @user -->` markers."""
    matches = list(_BLOCK_RE.finditer(text))
    if len(matches) != 2:
        raise PromptShapeError(
            f"Prompt {path} must contain exactly one @system and one @user marker; "
            f"found {len(matches)}"
        )
    labels = [m.group(1) for m in matches]
    if labels != ["system", "user"]:
        raise PromptShapeError(
            f"Prompt {path} markers must appear in order @system then @user; got {labels}"
        )
    system_src = text[matches[0].end() : matches[1].start()].strip()
    user_src = text[matches[1].end() :].strip()
    if not system_src or not user_src:
        raise PromptShapeError(f"Prompt {path} has an empty @system or @user block")
    return system_src, user_src


def _classify_stem(stem: str) -> tuple[CheckType | None, SubAgent | None]:
    """Map a filename stem to either a CheckType or a SubAgent."""
    try:
        return CheckType(stem), None
    except ValueError:
        pass
    try:
        return None, SubAgent(stem)
    except ValueError:
        return None, None
