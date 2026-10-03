import os

import pytest

os.environ.setdefault("HF_API_KEY", "test-only-placeholder")
os.environ.setdefault("ALLOWED_ORIGINS", '["http://localhost:5173"]')

# Keep ordinary tests isolated from the developer's local runtime configuration.
os.environ["CACHE_BACKEND"] = "memory"
os.environ["EVALUATION_DATASET_STORAGE"] = "session"
os.environ["EVALUATION_RUN_HISTORY_STORAGE"] = "disabled"

from app.core.config import Settings, get_settings

# Keep automated tests deterministic by ignoring developer-local .env values.
# Tests use explicit settings and controlled environment variables instead.
Settings.model_config["env_file"] = None


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(
        hf_api_key="test-only-placeholder",
        cache_backend="memory",
        prompt_typo_correction_enabled=False,
        allowed_origins=["http://localhost:5173"],
    )
