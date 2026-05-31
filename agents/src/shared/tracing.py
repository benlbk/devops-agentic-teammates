"""OpenTelemetry tracing for the orchestrator (NFR-5).

- Configures the global tracer provider with a `Resource` describing service
  name + version + environment.
- Picks an exporter based on env:
    OTEL_EXPORTER_OTLP_ENDPOINT set  → OTLP/HTTP (e.g. http://otel-collector:4318)
    OTEL_TRACES_CONSOLE=1            → ConsoleSpanExporter (dev debugging)
    otherwise                        → no exporter (spans still created,
                                       context still propagates, no I/O cost)
- Instruments FastAPI (per-request spans), httpx (outbound HTTP, e.g. GitHub),
  botocore (DynamoDB / EventBridge / Bedrock / Secrets Manager), and stdlib
  logging (injects trace_id/span_id into log records — works alongside
  structlog because both write to the same root logger).

The module is import-safe even when the OTel libraries are missing
(`init()` becomes a no-op). The legacy code path is therefore unaffected.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_TRACER: Any = None
_INITIALISED: bool = False
_PROVIDER_READY: bool = False


def _init_provider() -> None:
    """Set up TracerProvider + exporter + library auto-instrumentation.

    Safe to call at module import time so httpx/botocore clients constructed
    later are automatically traced.
    """
    global _TRACER, _PROVIDER_READY
    if _PROVIDER_READY:
        return
    _PROVIDER_READY = True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except Exception as exc:
        logger.warning("opentelemetry not installed, tracing disabled: %s", exc)
        return

    service_name = os.environ.get("OTEL_SERVICE_NAME", "agent-orchestrator")
    service_version = os.environ.get("OTEL_SERVICE_VERSION", "v74")
    deployment_env = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT",
                                    os.environ.get("ENVIRONMENT", "dev"))

    resource = Resource.create({
        "service.name": service_name,
        "service.version": service_version,
        "deployment.environment": deployment_env,
    })
    provider = TracerProvider(resource=resource)

    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            logger.info("OTLP exporter configured: endpoint=%s", otlp_endpoint)
        except Exception as exc:
            logger.error("OTLP exporter init failed: %s", exc)

    if os.environ.get("OTEL_TRACES_CONSOLE", "").lower() in ("1", "true", "yes"):
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("agent-orchestrator")

    # Instrument client libraries BEFORE any AsyncClient / boto3 client is
    # constructed by the importing app. FastAPI is instrumented later in
    # `init(app)` once the app instance exists.
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:
        logger.warning("httpx instrumentation failed: %s", exc)

    try:
        from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
        BotocoreInstrumentor().instrument()
    except Exception as exc:
        logger.warning("botocore instrumentation failed: %s", exc)

    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        LoggingInstrumentor().instrument(set_logging_format=False)
    except Exception as exc:
        logger.warning("logging instrumentation failed: %s", exc)

    logger.info("tracing provider initialised: service=%s version=%s env=%s exporter=%s",
                service_name, service_version, deployment_env,
                "otlp" if otlp_endpoint else ("console" if os.environ.get("OTEL_TRACES_CONSOLE") else "noop"))


def init(app: Any | None = None) -> None:
    """Late-stage init: ensure provider exists, then instrument FastAPI app."""
    global _INITIALISED
    _init_provider()
    if _INITIALISED:
        return
    _INITIALISED = True

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
        except Exception as exc:
            logger.warning("fastapi instrumentation failed: %s", exc)


# Kick the provider up at import time so all libraries imported after this
# module get traced. The actual exporter / instrumentations are safe to set
# up before the FastAPI app exists.
_init_provider()


def get_tracer() -> Any:
    """Return the configured tracer, or a no-op tracer if init() never ran."""
    global _TRACER
    if _TRACER is not None:
        return _TRACER
    try:
        from opentelemetry import trace
        return trace.get_tracer("agent-orchestrator")
    except Exception:
        return _NoopTracer()


@contextmanager
def task_span(agent_type: str, task_type: str, task_id: str, **attrs: Any):
    """Convenience wrapper for the per-task span used by `execute_agent_task`."""
    tracer = get_tracer()
    name = f"agent.task {agent_type}.{task_type}"
    try:
        span_cm = tracer.start_as_current_span(name)
    except Exception:
        yield None
        return
    with span_cm as span:
        try:
            if span is not None and getattr(span, "is_recording", lambda: False)():
                span.set_attribute("agent.type", agent_type)
                span.set_attribute("agent.task_type", task_type)
                span.set_attribute("agent.task_id", task_id)
                for k, v in attrs.items():
                    if v is not None:
                        span.set_attribute(k, str(v)[:512])
        except Exception:
            pass
        yield span


def trace_context_headers() -> dict[str, str]:
    """Return W3C `traceparent`/`tracestate` headers for the current span.

    Used when emitting events into EventBridge / DynamoDB so downstream
    consumers can stitch the trace together.
    """
    try:
        from opentelemetry.propagate import inject
        carrier: dict[str, str] = {}
        inject(carrier)
        return carrier
    except Exception:
        return {}


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, _name: str, **_kw: Any):
        yield None
