"""Shared exception types (kept apart so answers.py and generate.py can both
raise them without importing each other)."""


class GenerateError(Exception):
    pass
