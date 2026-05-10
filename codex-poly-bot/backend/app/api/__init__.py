"""FastAPI dashboard API routers.

REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005,
REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010,
REQ-UI-011, REQ-OBS-004, REQ-OBS-005, REQ-OBS-006
"""

from app.api.dashboard import build_dashboard_router

__all__ = ["build_dashboard_router"]
