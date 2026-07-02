"""SigNoz and HTTP response observability setup.

REQ: REQ-OBS-001, REQ-OBS-002, REQ-OBS-005, REQ-OBS-006
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import os
from time import perf_counter
from typing import Iterator, Mapping
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

try:  # pragma: no cover - exercised only when optional OTel packages are present.
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError:  # pragma: no cover - fallback keeps local tests usable before install.
    trace = None
    Status = None
    StatusCode = None
    OTLPLogExporter = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    HTTPXClientInstrumentor = None
    LoggerProvider = None
    LoggingHandler = None
    BatchLogRecordProcessor = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None


LOGGER = logging.getLogger(__name__)
DEFAULT_BACKEND_SERVICE_NAME = "codex-poly-bot-backend"
DEFAULT_FRONTEND_SERVICE_NAME = "codex-poly-bot-frontend"
SIGNOZ_CLOUD_ENDPOINT_TEMPLATE = "https://ingest.{region}.signoz.cloud:443"

_OTEL_CONFIGURED = False
_HTTPX_INSTRUMENTED = False


@dataclass(frozen=True)
class ObservabilityConfig:
    """Resolved OpenTelemetry exporter configuration.

    REQ: REQ-OBS-001, REQ-OBS-002
    """

    enabled: bool
    service_name: str
    environment: str
    endpoint: str
    traces_endpoint: str
    logs_endpoint: str
    headers: dict[str, str]
    service_version: str = "0.1.0"


class HttpResponseLoggingMiddleware(BaseHTTPMiddleware):
    """Emit one structured log line for every HTTP response.

    REQ: REQ-OBS-001
    """

    def __init__(self, app, *, environment: str):
        super().__init__(app)
        self.environment = environment

    async def dispatch(self, request: Request, call_next):
        start = perf_counter()
        request_id = request.headers.get("x-request-id") or str(uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (perf_counter() - start) * 1000
            _record_http_response(
                request=request,
                request_id=request_id,
                environment=self.environment,
                status_code=500,
                duration_ms=duration_ms,
                error_type=exc.__class__.__name__,
            )
            raise

        duration_ms = (perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        _record_http_response(
            request=request,
            request_id=request_id,
            environment=self.environment,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


def build_observability_config(
    environ: Mapping[str, str] | None = None,
    *,
    default_service_name: str = DEFAULT_BACKEND_SERVICE_NAME,
) -> ObservabilityConfig:
    """Resolve SigNoz and OTLP settings from environment variables.

    REQ: REQ-OBS-001, REQ-OBS-002
    """

    source = environ or os.environ
    region = source.get("SIGNOZ_REGION", "").strip()
    endpoint = _base_endpoint(source, region)
    traces_endpoint = source.get("SIGNOZ_OTLP_TRACES_ENDPOINT", "").strip() or _signal_endpoint(
        endpoint, "traces"
    )
    logs_endpoint = source.get("SIGNOZ_OTLP_LOGS_ENDPOINT", "").strip() or _signal_endpoint(
        endpoint, "logs"
    )
    headers = _otel_headers(source)
    enabled = _bool_env(source, "SIGNOZ_ENABLED", bool(endpoint))
    if _bool_env(source, "OTEL_SDK_DISABLED", False):
        enabled = False
    if not endpoint and not traces_endpoint and not logs_endpoint:
        enabled = False
    return ObservabilityConfig(
        enabled=enabled,
        service_name=source.get("OTEL_SERVICE_NAME", "").strip()
        or source.get("SIGNOZ_SERVICE_NAME", "").strip()
        or default_service_name,
        service_version=source.get("APP_VERSION", "").strip() or "0.1.0",
        environment=source.get("APP_ENV", "").strip()
        or source.get("ENVIRONMENT", "").strip()
        or "local",
        endpoint=endpoint,
        traces_endpoint=traces_endpoint,
        logs_endpoint=logs_endpoint,
        headers=headers,
    )


def frontend_observability_config(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Return browser-safe frontend telemetry configuration.

    REQ: REQ-OBS-001, REQ-OBS-002
    """

    source = environ or os.environ
    enabled = _bool_env(source, "SIGNOZ_FRONTEND_ENABLED", False)
    server_config = build_observability_config(
        source,
        default_service_name=source.get("SIGNOZ_FRONTEND_SERVICE_NAME", DEFAULT_FRONTEND_SERVICE_NAME),
    )
    return {
        "enabled": enabled and server_config.enabled,
        "serviceName": source.get("SIGNOZ_FRONTEND_SERVICE_NAME", DEFAULT_FRONTEND_SERVICE_NAME),
        "serviceVersion": server_config.service_version,
        "environment": server_config.environment,
        "tracesEndpoint": "/api/observability/v1/traces",
        "logsEndpoint": "/api/observability/v1/logs",
    }


def configure_observability(app: FastAPI, *, settings: object) -> None:
    """Attach request logging and OpenTelemetry exporters to the app.

    REQ: REQ-OBS-001, REQ-OBS-002
    """

    runtime_env = getattr(settings, "runtime_env", os.environ)
    environment = getattr(getattr(settings, "environment", None), "value", None) or str(
        runtime_env.get("APP_ENV", "local")
    )
    if _bool_env(runtime_env, "HTTP_RESPONSE_LOGS_ENABLED", True):
        app.add_middleware(HttpResponseLoggingMiddleware, environment=environment)

    config = build_observability_config(runtime_env)
    app.state.observability = config
    if not config.enabled:
        return
    _configure_opentelemetry(app, config)


def signoz_signal_endpoint(signal: str, environ: Mapping[str, str] | None = None) -> str:
    """Resolve the upstream SigNoz endpoint for one OTLP signal.

    REQ: REQ-OBS-001, REQ-OBS-002
    """

    config = build_observability_config(environ)
    if signal == "traces":
        return config.traces_endpoint
    if signal == "logs":
        return config.logs_endpoint
    raise ValueError(f"unsupported observability signal: {signal}")


def signoz_headers(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return exporter headers without exposing them to browser config.

    REQ: REQ-OBS-001, REQ-OBS-002
    """

    return build_observability_config(environ).headers


@contextmanager
def start_observability_span(
    name: str,
    *,
    attributes: Mapping[str, object] | None = None,
) -> Iterator[object | None]:
    """Start a child span when OpenTelemetry is configured.

    REQ: REQ-OBS-005
    """

    if trace is None:
        yield None
        return
    tracer = trace.get_tracer("codex-poly-bot")
    with tracer.start_as_current_span(name) as span:
        set_span_attributes(span, attributes)
        yield span


def set_span_attributes(span: object | None, attributes: Mapping[str, object] | None) -> None:
    """Attach scalar application attributes to a span.

    REQ: REQ-OBS-005
    """

    if span is None:
        return
    set_attribute = getattr(span, "set_attribute", None)
    if not callable(set_attribute):
        return
    for key, value in _prefixed_span_attributes(attributes).items():
        set_attribute(key, value)


def record_span_failure(
    span: object | None,
    exc: Exception,
    *,
    event_name: str,
    attributes: Mapping[str, object] | None = None,
) -> None:
    """Record an application failure event and mark the span as failed.

    REQ: REQ-OBS-005
    """

    if span is None:
        return
    payload = {
        "event_name": event_name,
        "status": "error",
        "error_type": exc.__class__.__name__,
        "error_message": _safe_span_error_message(exc),
        **dict(attributes or {}),
    }
    span_attributes = _prefixed_span_attributes(payload)
    set_span_attributes(span, payload)

    record_exception = getattr(span, "record_exception", None)
    if callable(record_exception):
        record_exception(exc, attributes=span_attributes)

    add_event = getattr(span, "add_event", None)
    if callable(add_event):
        add_event(event_name, attributes=span_attributes)

    set_status = getattr(span, "set_status", None)
    if callable(set_status) and Status is not None and StatusCode is not None:
        set_status(
            Status(
                StatusCode.ERROR,
                description=f"{event_name}: {exc.__class__.__name__}",
            )
        )


def record_span_event(
    span: object | None,
    *,
    event_name: str,
    attributes: Mapping[str, object] | None = None,
) -> None:
    """Record a non-error application event on an active span.

    REQ: REQ-OBS-005
    """

    if span is None:
        return
    payload = {"event_name": event_name, **dict(attributes or {})}
    span_attributes = _prefixed_span_attributes(payload)
    set_span_attributes(span, payload)

    add_event = getattr(span, "add_event", None)
    if callable(add_event):
        add_event(event_name, attributes=span_attributes)


def _configure_opentelemetry(app: FastAPI, config: ObservabilityConfig) -> None:
    global _OTEL_CONFIGURED
    global _HTTPX_INSTRUMENTED

    if not _otel_packages_available():
        LOGGER.warning("otel_unavailable service=%s", config.service_name)
        return

    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.version": config.service_version,
            "deployment.environment": config.environment,
            "service.namespace": "codex-poly-bot",
        }
    )

    if not _OTEL_CONFIGURED:
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=config.traces_endpoint, headers=config.headers)
            )
        )
        trace.set_tracer_provider(tracer_provider)

        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(endpoint=config.logs_endpoint, headers=config.headers)
            )
        )
        logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))
        _OTEL_CONFIGURED = True

    if FastAPIInstrumentor is not None and not getattr(app.state, "otel_fastapi_instrumented", False):
        FastAPIInstrumentor.instrument_app(app)
        app.state.otel_fastapi_instrumented = True

    if HTTPXClientInstrumentor is not None and not _HTTPX_INSTRUMENTED:
        HTTPXClientInstrumentor().instrument()
        _HTTPX_INSTRUMENTED = True


def _record_http_response(
    *,
    request: Request,
    request_id: str,
    environment: str,
    status_code: int,
    duration_ms: float,
    error_type: str | None = None,
) -> None:
    payload = {
        "event_name": "http.response",
        "request_id": request_id,
        "environment": environment,
        "method": request.method,
        "path": request.url.path,
        "route": _route_path(request),
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2),
        "client_ip": request.client.host if request.client else "",
        "user_agent": request.headers.get("user-agent", ""),
    }
    if error_type:
        payload["error_type"] = error_type
    _set_current_span_attributes(payload)
    LOGGER.info("http_response %s", json.dumps(payload, sort_keys=True))


def _set_current_span_attributes(payload: Mapping[str, object]) -> None:
    if trace is None:
        return
    span = trace.get_current_span()
    if not span:
        return
    set_span_attributes(span, payload)


def _prefixed_span_attributes(attributes: Mapping[str, object] | None) -> dict[str, object]:
    prefixed: dict[str, object] = {}
    for key, value in dict(attributes or {}).items():
        if isinstance(value, (str, int, float, bool)):
            prefixed[f"codex_poly_bot.{key}"] = value
    return prefixed


def _safe_span_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return (message or "application failure")[:300]


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path or request.url.path)


def _base_endpoint(source: Mapping[str, str], region: str) -> str:
    configured = (
        source.get("SIGNOZ_OTLP_ENDPOINT", "").strip()
        or source.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    )
    if configured:
        return configured.rstrip("/")
    if region:
        return SIGNOZ_CLOUD_ENDPOINT_TEMPLATE.format(region=region)
    return ""


def _signal_endpoint(endpoint: str, signal: str) -> str:
    if not endpoint:
        return ""
    if endpoint.endswith(f"/v1/{signal}"):
        return endpoint
    return f"{endpoint.rstrip('/')}/v1/{signal}"


def _otel_headers(source: Mapping[str, str]) -> dict[str, str]:
    headers = _parse_header_list(source.get("OTEL_EXPORTER_OTLP_HEADERS", ""))
    ingestion_key = source.get("SIGNOZ_INGESTION_KEY", "").strip()
    if ingestion_key:
        headers["signoz-ingestion-key"] = ingestion_key
    return headers


def _parse_header_list(raw_headers: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in raw_headers.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            headers[key] = value.strip()
    return headers


def _bool_env(source: Mapping[str, str], name: str, default: bool) -> bool:
    value = source.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _otel_packages_available() -> bool:
    return all(
        dependency is not None
        for dependency in (
            trace,
            OTLPLogExporter,
            OTLPSpanExporter,
            FastAPIInstrumentor,
            HTTPXClientInstrumentor,
            LoggerProvider,
            LoggingHandler,
            BatchLogRecordProcessor,
            Resource,
            TracerProvider,
            BatchSpanProcessor,
        )
    )
