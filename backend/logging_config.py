"""Structured JSON logging for requests and schedule runs.

Every log line is one JSON object. Extra fields passed with logger.info(..., extra={...}) are
included when they are in EXTRA_FIELDS, so logs can be filtered by request_id, run_id, etc.
"""
import json
import logging
import sys
from datetime import datetime, timezone

EXTRA_FIELDS = ("event", "request_id", "method", "path", "status", "duration_ms", "username",
                "role", "scenario_id", "strategy", "run_id", "scheduled_count", "task_count",
                "total_cost", "makespan_hours", "error")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level=logging.INFO):
    logger = logging.getLogger("gridrestore")
    if getattr(logger, "_configured", False):
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    logger._configured = True
    return logger


log = configure_logging()
