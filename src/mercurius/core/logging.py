"""Logging setup: UTC timestamps, secret redaction on every record."""

from __future__ import annotations

import logging
import re
import time

# Alpaca key ids look like PK/AK + base32-ish; secrets are long base62 blobs.
_PATTERNS = [
    re.compile(r"\b[PA]K[A-Z0-9]{8,}\b"),
    re.compile(r"\b[A-Za-z0-9/+]{38,}\b"),
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"),  # telegram bot tokens
]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = msg
        for pat in _PATTERNS:
            redacted = pat.sub("[REDACTED]", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    fmt = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    )
    fmt.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
