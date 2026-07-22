"""CORS_ALLOWED_ORIGINS env-parsing regression suite (F-02).

Pure **unit** tests — no DB, no Docker, no live services. They pin the fix for
the Phase-12 rev-00021 startup crash: pydantic-settings JSON-decodes ``list[str]``
env values BEFORE any ``mode="before"`` field_validator runs, so a
comma-separated ``CORS_ALLOWED_ORIGINS`` value never reached the
``_split_cors_origins`` validator and crashed ``Settings()`` construction. The
field is now ``Annotated[list[str], NoDecode]`` so the raw env string always
reaches the validator, which accepts BOTH the comma-separated form and the
JSON-array form (the live-prod value).

Authoritative reference: finding F-02 (Phase-12 cutover, rev 00021 failed start).
"""

from __future__ import annotations

from app.core.config import Settings


def test_cors_env_comma_separated(monkeypatch):
    """Comma-separated env form parses into a list — the rev-00021 crash case.

    Before the ``NoDecode`` fix this raised at ``Settings()`` construction
    because pydantic-settings tried ``json.loads`` on the raw string first.
    """
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")

    settings = Settings()

    assert settings.cors_allowed_origins == ["https://a.example", "https://b.example"]


def test_cors_env_json_array(monkeypatch):
    """JSON-array env form (live-prod compat) parses to the same result."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["https://a.example","https://b.example"]')

    settings = Settings()

    assert settings.cors_allowed_origins == ["https://a.example", "https://b.example"]


def test_cors_env_empty_string(monkeypatch):
    """Empty string -> empty list (no origins -> CORSMiddleware not installed)."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")

    settings = Settings()

    assert settings.cors_allowed_origins == []


def test_cors_env_single_origin(monkeypatch):
    """A single origin with no comma yields a one-element list."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://nestor.example.com")

    settings = Settings()

    assert settings.cors_allowed_origins == ["https://nestor.example.com"]
