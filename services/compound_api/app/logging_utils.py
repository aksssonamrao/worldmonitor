from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

request_id_var: ContextVar[str] = ContextVar('request_id', default='-')


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'service': self.service,
            'logger': record.name,
            'message': record.getMessage(),
            'request_id': request_id_var.get(),
        }
        if hasattr(record, 'event'):
            payload['event'] = record.event
        if hasattr(record, 'meta'):
            payload['meta'] = record.meta
        return json.dumps(payload, default=str)


def configure_logging(service: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def next_request_id() -> str:
    return str(uuid4())
