import pytest

from shadescout.config import load_settings
from shadescout.errors import ConfigError


def _clear_env(monkeypatch):
    for key in [
        "REALTY_PROVIDER",
        "REALTYAPI_KEY",
        "RENTCAST_API_KEY",
        "RAPIDAPI_KEY",
        "GOOGLE_MAPS_API_KEY",
        "OPENROUTER_API_KEY",
        "VISION_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_load_settings_missing_realtyapi_key_raises(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "g")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    with pytest.raises(ConfigError, match="REALTYAPI_KEY"):
        load_settings()


def test_load_settings_missing_rentcast_key_raises(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("REALTY_PROVIDER", "rentcast")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "g")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    with pytest.raises(ConfigError, match="RENTCAST_API_KEY"):
        load_settings()


def test_load_settings_invalid_provider_raises(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("REALTY_PROVIDER", "not_a_real_provider")
    with pytest.raises(ConfigError):
        load_settings()


def test_load_settings_success(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("REALTY_PROVIDER", "realtyapi")
    monkeypatch.setenv("REALTYAPI_KEY", "a")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "g")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    settings = load_settings()
    assert settings.realty_provider == "realtyapi"
    assert settings.vision_model == "google/gemini-3.5-flash"


def test_load_settings_default_provider_is_realtyapi(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("REALTYAPI_KEY", "a")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "g")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    settings = load_settings()
    assert settings.realty_provider == "realtyapi"
