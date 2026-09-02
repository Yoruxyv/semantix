from app.core.config import Settings
from app.factory import create_app

app = create_app(
    Settings(
        embedding_provider="mock",
        generation_provider="mock",
        cache_backend="memory",
        database_url=None,
        evaluation_dataset_storage="session",
        evaluation_run_history_storage="disabled",
        auth_mode="disabled",
        allowed_origins=["http://localhost:5173"],
        rate_limit="10000/second",
        log_level="INFO",
    )
)
