from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import (
    AuthRole,
    CacheBackendName,
    EvaluationDatasetStorageMode,
)
from app.providers.configuration import EmbeddingProviderName, GenerationProviderName


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HealthResponse(StrictModel):
    status: Literal["ok"]
    embedding_provider: EmbeddingProviderName
    generation_provider: GenerationProviderName


class ReadinessResponse(StrictModel):
    status: Literal["ready"]
    cache_backend: CacheBackendName
    evaluation_dataset_storage: EvaluationDatasetStorageMode


class AuthConfigResponse(StrictModel):
    authentication_required: bool


class AuthSessionResponse(StrictModel):
    name: str
    role: AuthRole
    namespaces: list[str]


class ErrorResponse(StrictModel):
    error: str = Field(min_length=1, max_length=100)
    detail: str | None = Field(default=None, max_length=500)
