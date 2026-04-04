---
description: "Use when writing or modifying Python backend code in scalper-ai/. Covers async patterns, type hints, import conventions, error handling, and code style for the trading bot."
applyTo: "scalper-ai/**/*.py"
---

# Python Code Standards — SCALPER-AI

## Imports

- Every file starts with `from __future__ import annotations`
- Use `TYPE_CHECKING` for forward references to avoid circular imports:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from ml.online_learner import OnlineLearner
  ```

## Type Hints

- ALL function parameters and return types must have type annotations
- Use `Optional[X]` for nullable, `dict[str, X]` not `Dict`, `list[X]` not `List`
- Dataclasses for all data objects (`Signal`, `Position`, `MarketSnapshot`, etc.)

## Async Pattern

- All I/O is async — never block the event loop
- Use `asyncio.Lock` per symbol for MarketCache writes
- External API calls wrapped in retry logic (3 attempts, exponential backoff)
- Use `aiohttp` for HTTP, not `requests`

## Logging

- Use `loguru.logger`, never `print()` or stdlib `logging`
- Log levels: `logger.info()` for flow, `logger.warning()` for recoverable, `logger.error()` for failures
- Always include context: `logger.error(f"SL failed for {symbol}: {error}")`

## Constants

- Module-level UPPER_CASE constants at top of file
- No magic numbers in logic — extract to named constant
- Thresholds for strategies at top of strategy file

## Error Handling

- Catch specific exceptions, never bare `except:`
- All division: check denominator ≠ 0
- All dict access on external data: use `.get()` with defaults
- All exchange responses: validate required fields exist before use

## Limits

- Max function length: 50 lines — split if longer
- Max file length: 400 lines — split module if longer
- No circular imports
