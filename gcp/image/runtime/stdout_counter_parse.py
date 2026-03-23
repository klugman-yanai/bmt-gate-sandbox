"""Shared stdout counter line parsing for kardome_runner logs (NAMUH / custom regex)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)

DEFAULT_KARDOME_COUNTER_KEYWORD: Final[str] = "NAMUH"


class StdoutCounterParseConfig(BaseModel):
    """Subset of plugin_config used to find the integer counter in runner stdout logs."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    keyword: str = DEFAULT_KARDOME_COUNTER_KEYWORD
    counter_pattern: str | None = None

    @field_validator("keyword")
    @classmethod
    def _keyword_non_empty(cls, v: str) -> str:
        s = v.strip()
        return s or DEFAULT_KARDOME_COUNTER_KEYWORD

    @field_validator("counter_pattern", mode="before")
    @classmethod
    def _empty_pattern_to_none(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    @field_validator("counter_pattern")
    @classmethod
    def _pattern_must_compile(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"counter_pattern is not a valid regex: {exc}") from exc
        return v


def compile_counter_pattern(cfg: StdoutCounterParseConfig) -> re.Pattern[str]:
    """Build the regex used to extract the counter (last capture group wins for findall)."""
    if cfg.counter_pattern:
        return re.compile(cfg.counter_pattern)
    keyword = cfg.keyword.strip() or DEFAULT_KARDOME_COUNTER_KEYWORD
    return re.compile(rf"Hi {re.escape(keyword)} counter = (\d+)")


def counter_pattern_from_parsing_dict(parsing: dict[str, Any]) -> re.Pattern[str]:
    """Validate ``parsing`` (plugin_config subset) and return a compiled counter regex."""
    return compile_counter_pattern(StdoutCounterParseConfig.model_validate(parsing))


def read_counter_from_log(log_path: Path, counter_re: re.Pattern[str]) -> int | None:
    """Return the last counter value from the log, or None if the pattern never matches."""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if "\ufffd" in text:
        logger.warning("Log file %s contains encoding replacement characters", log_path)
    matches = counter_re.findall(text)
    if not matches:
        logger.warning("Counter pattern %r not found in %s", counter_re.pattern, log_path)
        return None
    return int(matches[-1])
