"""Domain exception hierarchy.

Exceptions raised by adapters when domain operations fail. Domain code
itself is pure and raises only ValueError / pydantic.ValidationError.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base for all domain-related exceptions."""


# REQ: REQ-VEN-001 - Venue Protocol error surface
class VenueError(DomainError):
    """Base for venue adapter errors."""


class VenueUnreachableError(VenueError):
    """Venue API returned 5xx, network failed, or timed out."""


class InvalidOrderSpecError(VenueError):
    """OrderSpec failed adapter-side validation before submission."""


class OrderRejectedError(VenueError):
    """Venue accepted the request but rejected the order (4xx with reason)."""


class InsufficientBalanceError(VenueError):
    """Venue rejected order because the wallet/account lacks funds."""


class MarketClosedError(VenueError):
    """Operation attempted on a venue that is currently closed (Alpaca)."""


class AccountRestrictedError(VenueError):
    """Venue account is restricted; e.g., region-blocked."""


class PDTViolationError(VenueError):
    """Pattern Day Trader rule would be violated by this trade."""


# REQ: REQ-LLM-008 - LLM error surface
class StrategistError(DomainError):
    """Base for LLM strategist errors."""


class StrategistUnreachableError(StrategistError):
    """LLM provider 5xx / timeout / network."""


class MalformedResponseError(StrategistError):
    """LLM returned content that could not be parsed into CheckResult."""


class RateLimitExhaustedError(StrategistError):
    """LLM provider 429 retries exhausted."""


class LLMSustainedErrorsError(StrategistError):
    """LLM provider returned 5+ consecutive failures (REQ-BRN-015)."""


# Repo errors
class RepoError(DomainError):
    """Base for repository errors."""


class DuplicateClientOrderIdError(RepoError):
    """Attempt to insert an Order with a client_order_id that already exists."""


class InvariantViolationError(RepoError):
    """A domain invariant was violated (e.g., illegal state transition)."""


class UnknownConfigFieldError(RepoError):
    """Attempt to read or write an unknown Tier-1 config field."""
