---
name: 'AI Image Generator'
description: 'Global repository architecture, stack preferences, and strict Python standards.'
applyTo: '**/*.py'
---

# Project Overview
This repository contains a program to create images from input speach audio using AI. It typically runs on a Raspberry Pi in kiosk mode. It is used by the general public without any training. Copilot must prioritize stability, easy to understand GUI, clean modular architectures, and explicit type checking.

# Tech Stack & Dependencies
- **Language:** Python 3.11+
- **Testing:** Pytest, pytest-asyncio
- **Linter/Formatter:** Ruff (replaces Flake8, Black, and isort)

# Directory Structure
- `src/` - Main source folder
- `tests/` - Pytest test suites

# Core Python Coding Conventions
- **Style:** Adhere strictly to PEP 8 standards enforced by Ruff.
- **Typing:** Use explicit PEP 484 type hints for all function signatures and variables. Avoid `Any`.
- **Async:** Use native `async`/`await` for all I/O bound operations, network calls, and database transactions.
- **Configuration:** Always use Pydantic `BaseSettings` for managing environment variables.

# Critical Constraints (What NOT to do)
- DO NOT use legacy `print()` functions for logging. Use the standard `logging` module.
- DO NOT use synchronous database drivers. Use `asyncpg` with SQLAlchemy async sessions.
- DO NOT use vanilla `dict` for API request/response modeling. Always implement Pydantic schemas.
- DO NOT mock third-party network libraries globally. Use `pytest-mock` or explicit dependency injection overrides.

