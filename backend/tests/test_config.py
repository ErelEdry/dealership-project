"""Settings defaults that matter for a fresh, unconfigured deployment."""

import pytest

from app.core.config import Settings


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("DEBUG", "CORS_ORIGINS", "ADMIN_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_debug_off_by_default(clean_env):
    # debug drives SQLAlchemy echo=..., which logs every query.
    assert Settings(_env_file=None).debug is False


def test_cors_default_is_local_frontend(clean_env):
    assert Settings(_env_file=None).cors_origin_list == ["http://localhost:3000"]


def test_cors_origins_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://cars.example.com ,")
    assert Settings(_env_file=None).cors_origin_list == [
        "http://localhost:3000", "https://cars.example.com"]


def test_email_validator_is_a_direct_requirement():
    from pathlib import Path
    reqs = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    assert any(line.startswith("email-validator==") for line in reqs.splitlines())
