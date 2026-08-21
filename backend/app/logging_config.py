"""Structured logging.

Two formats from one call site. `console` is for a human watching an ingest
run; `json` is one object per line, for when the same run is happening
unattended on the workstation and the interesting part is what it did at 2am.

Everything goes to **stderr**. The CLI writes its results to stdout, so
`... health --json | jq` stays clean no matter how chatty the log level is.

Extra fields ride along on the record and are rendered in both formats:

    log.info("indexed document", extra={"doc_id": doc_id, "chunks": 412})
    12:04:31  INFO  app.index    indexed document  doc_id=ab12 chunks=412
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import IO, Any, Literal

LogFormat = Literal["console", "json"]

# Attribute names the stdlib puts on every record. Anything else on a record
# was passed by us through `extra=` and should be rendered.
_RESERVED = frozenset(
    logging.LogRecord(name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None).__dict__
) | {"message", "asctime", "taskName"}

_LEVEL_COLOUR = {
    "DEBUG": "\033[38;5;245m",
    "INFO": "\033[38;5;37m",  # teal, to match the product
    "WARNING": "\033[38;5;179m",
    "ERROR": "\033[38;5;167m",
    "CRITICAL": "\033[1;38;5;167m",
}
_DIM = "\033[38;5;245m"
_RESET = "\033[0m"

_configured = False


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _RESERVED}


class ConsoleFormatter(logging.Formatter):
    """Aligned, single line per record, colour only when a terminal is watching."""

    def __init__(self, *, colour: bool) -> None:
        super().__init__()
        self.colour = colour

    def format(self, record: logging.LogRecord) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created))
        level = record.levelname
        name = record.name

        if self.colour:
            stamp = f"{_DIM}{stamp}{_RESET}"
            level = f"{_LEVEL_COLOUR.get(record.levelname, '')}{record.levelname:<8}{_RESET}"
            name = f"{_DIM}{record.name:<22}{_RESET}"
        else:
            level = f"{level:<8}"
            name = f"{name:<22}"

        line = f"{stamp}  {level}{name}{record.getMessage()}"

        extras = _extras(record)
        if extras:
            pairs = " ".join(f"{k}={v}" for k, v in extras.items())
            line += f"  {_DIM}{pairs}{_RESET}" if self.colour else f"  {pairs}"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class JsonFormatter(logging.Formatter):
    """One JSON object per line, UTC timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_extras(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    level: str = "INFO",
    fmt: LogFormat = "console",
    *,
    stream: IO[str] | None = None,
) -> None:
    """Install the root handler. Idempotent — calling it twice replaces, never duplicates."""
    global _configured

    target = stream or sys.stderr
    colour = fmt == "console" and hasattr(target, "isatty") and target.isatty() and not os.environ.get("NO_COLOR")

    handler = logging.StreamHandler(target)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter(colour=colour))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Model libraries are enthusiastic loggers; keep their chatter out of the
    # ingest transcript unless we asked for DEBUG.
    for noisy in ("urllib3", "httpx", "httpcore", "filelock", "transformers", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))

    logging.captureWarnings(True)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """A logger, configuring logging with defaults first if nobody has yet."""
    if not _configured:
        configure_logging()
    return logging.getLogger(name)
