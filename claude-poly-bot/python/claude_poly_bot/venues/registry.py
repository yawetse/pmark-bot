"""Venue registry — lookup by name, iterate enabled venues.

Traces: REQ-VEN-003, REQ-VEN-006.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from claude_poly_bot.domain.models import VenueName
from claude_poly_bot.domain.protocols import HealthStatus, Venue


class VenueNotRegisteredError(KeyError):
    """Raised when a VenueName is not present in the registry."""


@dataclass
class VenueRegistry:
    """Wraps a dict of registered Venues. Constructed at startup with all
    Venue impls (real or fake)."""

    venues: dict[VenueName, Venue]

    # REQ: REQ-VEN-003
    def get(self, name: VenueName) -> Venue:
        try:
            return self.venues[name]
        except KeyError as e:
            raise VenueNotRegisteredError(name) from e

    def list_all(self) -> list[Venue]:
        return list(self.venues.values())

    # REQ: REQ-VEN-007 - concurrent health probe across all venues.
    async def health_check_all(self) -> dict[VenueName, HealthStatus]:
        names = list(self.venues.keys())
        results = await asyncio.gather(
            *(v.health_check() for v in self.venues.values()),
            return_exceptions=True,
        )
        out: dict[VenueName, HealthStatus] = {}
        for name, res in zip(names, results, strict=True):
            if isinstance(res, BaseException):
                out[name] = HealthStatus(
                    status="error",
                    latency_ms=0.0,
                    checked_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    error=str(res),
                )
            else:
                out[name] = res
        return out
