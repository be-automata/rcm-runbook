"""Observability wiring: structured JSON logging + flag-gated OpenTelemetry hook.

"Observed" for this MVP means:
- every tool call logged as JSON ({tool, outcome, duration_ms}) — see agent/tools.py
- decision-engine paths logged (policy, consequence, route, HITL) — JA1011 audit trail
- Agno stores sessions/runs/metrics in our SQLite (no third-party egress)
- optional OTel export behind RCM_OTEL_ENABLED for any collector (e.g. Langfuse)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from rcm_runbook.config import Settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
        }
        msg = record.getMessage()
        try:
            payload["event"] = json.loads(msg)
        except (json.JSONDecodeError, TypeError):
            payload["message"] = msg
        if record.exc_info and record.exc_info[0]:
            payload["exception"] = self.formatException(record.exc_info)[-800:]
        return json.dumps(payload, ensure_ascii=False)


def setup_observability(cfg: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("rcm_runbook")
    root.setLevel(cfg.log_level.upper())
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False

    if cfg.otel_enabled:
        _setup_otel()


def _setup_otel() -> None:
    """Single wiring point so ops can target any OTLP collector. Off by default."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": "rcm-runbook"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        logging.getLogger("rcm_runbook").info(
            json.dumps({"otel": "enabled", "exporter": "otlp-http"})
        )
    except ImportError:
        logging.getLogger("rcm_runbook").warning(
            json.dumps({
                "otel": "requested but opentelemetry-sdk not installed",
                "fix": "uv add opentelemetry-sdk opentelemetry-exporter-otlp-proto-http",
            })
        )
