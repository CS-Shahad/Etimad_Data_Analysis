import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.runtime_budget import resolve_max_runtime_seconds


def test_env_var_takes_priority_over_config(monkeypatch):
    monkeypatch.setenv("SOME_MAX_MINUTES", "10")
    assert resolve_max_runtime_seconds("SOME_MAX_MINUTES", 999) == 600.0


def test_falls_back_to_config_value_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("SOME_MAX_MINUTES", raising=False)
    assert resolve_max_runtime_seconds("SOME_MAX_MINUTES", 5) == 300.0


def test_returns_none_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("SOME_MAX_MINUTES", raising=False)
    assert resolve_max_runtime_seconds("SOME_MAX_MINUTES", None) is None


def test_returns_none_when_config_value_is_zero(monkeypatch):
    monkeypatch.delenv("SOME_MAX_MINUTES", raising=False)
    assert resolve_max_runtime_seconds("SOME_MAX_MINUTES", 0) is None
