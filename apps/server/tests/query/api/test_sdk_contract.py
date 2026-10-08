"""Executable OpenAPI contract for the three SDK-supported routes."""

import pytest
from pydantic import ValidationError

from app.main import app
from app.query.api.schemas import QueryResponse

SDK_CONTRACTS = {
    ("POST", "/api/v1/query"),
    ("GET", "/health"),
    ("GET", "/ready"),
}
QUERY_FIELDS = {
    "response",
    "cache_hit",
    "similarity_score",
    "similarity_threshold",
    "matched_prompt",
    "matched_cache_key",
    "cache_entry_created_at",
    "cache_entry_age_seconds",
    "generation_skipped",
    "provider_called",
    "latency_ms",
}
NULLABLE_EVIDENCE = {
    "similarity_score",
    "matched_prompt",
    "matched_cache_key",
    "cache_entry_created_at",
    "cache_entry_age_seconds",
}


def test_sdk_openapi_subset() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    for method, path in SDK_CONTRACTS:
        assert method.lower() in spec["paths"][path]

    query = spec["paths"]["/api/v1/query"]["post"]
    assert query["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/QueryRequest"
    }
    assert query["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/QueryResponse"
    }
    assert "422" in query["responses"]
    request = schemas["QueryRequest"]
    assert set(request["properties"]) == {
        "prompt",
        "namespace",
        "cache_enabled",
        "cache_read_enabled",
        "cache_write_enabled",
        "private",
        "cache_ttl_seconds",
    }
    assert set(request["required"]) == {"prompt"}
    assert request["properties"]["prompt"]["minLength"] == 1
    assert request["properties"]["prompt"]["maxLength"] == 2_000
    assert request["properties"]["namespace"]["pattern"] == (
        "^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
    )
    ttl = request["properties"]["cache_ttl_seconds"]["anyOf"]
    assert {part["type"] for part in ttl} == {"integer", "null"}
    assert ttl[0]["minimum"] == 1
    assert ttl[0]["maximum"] == 31_536_000
    for flag in (
        "cache_enabled",
        "cache_read_enabled",
        "cache_write_enabled",
        "private",
    ):
        assert request["properties"][flag]["type"] == "boolean"

    response = schemas["QueryResponse"]
    assert set(response["properties"]) == QUERY_FIELDS
    assert set(response["required"]) == QUERY_FIELDS
    assert all(
        {part["type"] for part in response["properties"][name]["anyOf"]}
        == {
            "null",
            "number"
            if name in {"similarity_score", "cache_entry_age_seconds"}
            else "string",
        }
        for name in NULLABLE_EVIDENCE
    )
    assert response["properties"]["similarity_score"]["anyOf"][0]["minimum"] == -1
    assert response["properties"]["similarity_threshold"]["maximum"] == 1
    assert response["properties"]["latency_ms"]["minimum"] == 0
    assert response["properties"]["cache_hit"]["type"] == "boolean"
    assert response["properties"]["generation_skipped"]["type"] == "boolean"
    assert response["properties"]["provider_called"]["type"] == "boolean"

    for path, schema_name in (
        ("/health", "HealthResponse"),
        ("/ready", "ReadinessResponse"),
    ):
        assert spec["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"] == {"$ref": f"#/components/schemas/{schema_name}"}
        assert set(schemas[schema_name]["required"]) == set(
            schemas[schema_name]["properties"]
        )
    assert "503" in spec["paths"]["/ready"]["get"]["responses"]
    health = schemas["HealthResponse"]["properties"]
    assert health["status"]["const"] == "ok"
    for name in ("embedding_provider", "generation_provider"):
        assert health[name]["minLength"] == 1
        assert health[name]["maxLength"] == 50
        assert health[name]["pattern"] == "^[A-Za-z0-9][A-Za-z0-9._:-]{0,49}$"
    ready = schemas["ReadinessResponse"]["properties"]
    assert ready["status"]["const"] == "ready"
    assert set(ready["cache_backend"]["enum"]) == {"memory", "pgvector", "redis"}
    assert set(ready["evaluation_dataset_storage"]["enum"]) == {"session", "postgres"}


def test_query_response_requires_nullable_evidence_keys() -> None:
    payload = {
        "response": "answer",
        "cache_hit": False,
        "similarity_score": None,
        "similarity_threshold": 0.92,
        "matched_prompt": None,
        "matched_cache_key": None,
        "cache_entry_created_at": None,
        "cache_entry_age_seconds": None,
        "generation_skipped": False,
        "provider_called": True,
        "latency_ms": 1.0,
    }
    assert QueryResponse.model_validate(payload).similarity_score is None
    for name in QUERY_FIELDS:
        with pytest.raises(ValidationError):
            QueryResponse.model_validate(
                {key: value for key, value in payload.items() if key != name}
            )
