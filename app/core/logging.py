from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
        }
        for key in ("run_id", "job_type", "company_id", "platform"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    )
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        Path(log_dir) / "socialintel.log",
        maxBytes=2_000_000,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
