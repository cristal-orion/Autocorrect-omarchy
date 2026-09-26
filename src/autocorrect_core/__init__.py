"""Standalone correction engine. No desktop, keyboard or network side effects."""

from .engine import AutocorrectEngine, Candidate, Decision, Policy

__all__ = ["AutocorrectEngine", "Candidate", "Decision", "Policy"]
