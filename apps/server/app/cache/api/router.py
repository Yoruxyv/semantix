"""Expose live-cache inspection, administration and global threshold policy.

Every route uses the configured quota and a borrowed SemanticCache. Viewers
can read authorized statistics, lists and details, and the global threshold.
Admins can delete entries or clear authorized scope; updating the threshold
requires a wildcard global admin. Threshold changes affect live queries and
are independent of evaluation comparisons or recommendations.

List/stats/clear resolve an optional namespace: a restricted sole namespace
can be inferred, while only wildcard principals may omit it for global scope.
Entry-key operations instead pass the principal's namespace set to storage;
knowledge of a key grants no access. Inspection returns sensitive prompt and
response data without confirming a hit or refreshing hit/LRU metadata. Pages
describe live observations and can shift between concurrent requests.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.api.deps import get_semantic_cache
from app.cache.api.schemas import (
    CacheEntryListResponse,
    CacheEntryMetadata,
    CacheEntrySort,
    CacheStatsResponse,
    CacheThresholdRequest,
    CacheThresholdResponse,
    ClearCacheResponse,
    DeleteCacheEntryResponse,
)
from app.cache.application.service import SemanticCache
from app.cache.domain.namespaces import CacheNamespace
from app.core.limits import MAX_PROMPT_LENGTH
from app.middleware.rate_limit import app_rate_limit, limiter
from app.security.auth import (
    AdminPrincipal,
    GlobalAdminPrincipal,
    ViewerPrincipal,
    resolve_namespace,
)

router = APIRouter(prefix="/api/v1/cache", tags=["cache"])
SemanticCacheDependency = Annotated[SemanticCache, Depends(get_semantic_cache)]
CacheKeyPath = Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")]
CacheNamespaceQuery = Annotated[CacheNamespace | None, Query()]


@router.get("/stats", response_model=CacheStatsResponse)
@limiter.limit(app_rate_limit)
async def cache_stats(
    request: Request,
    cache: SemanticCacheDependency,
    principal: ViewerPrincipal,
    namespace: CacheNamespaceQuery = None,
) -> CacheStatsResponse:
    authorized_namespace = resolve_namespace(principal, namespace, allow_global=True)
    return await cache.stats(authorized_namespace)


@router.get("/entries", response_model=CacheEntryListResponse)
@limiter.limit(app_rate_limit)
async def list_cache_entries(
    request: Request,
    cache: SemanticCacheDependency,
    principal: ViewerPrincipal,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    namespace: CacheNamespaceQuery = None,
    search: Annotated[str | None, Query(max_length=MAX_PROMPT_LENGTH)] = None,
    sort: Annotated[CacheEntrySort, Query()] = "newest",
) -> CacheEntryListResponse:
    """List viewer-authorized metadata with bounded offset pagination.

    Search is a trimmed, case-insensitive prompt substring. Sorting changes
    presentation, not recency; listings contain previews without full responses.
    """
    authorized_namespace = resolve_namespace(principal, namespace, allow_global=True)
    return await cache.list_entries(
        offset=offset,
        limit=limit,
        namespace=authorized_namespace,
        search=search,
        sort=sort,
    )


@router.get("/entries/{cache_key}", response_model=CacheEntryMetadata)
@limiter.limit(app_rate_limit)
async def get_cache_entry(
    request: Request,
    cache_key: CacheKeyPath,
    cache: SemanticCacheDependency,
    principal: ViewerPrincipal,
) -> CacheEntryMetadata:
    """Read a sensitive full response within the viewer's authorized scope.

    Raises:
        CacheEntryNotFoundError: The entry is absent, expired or outside the
            permitted namespaces; these cases share the public HTTP 404.
    """
    return await cache.get_entry(
        cache_key,
        authorized_namespaces=(
            None if principal.has_global_namespace_access else principal.namespaces
        ),
    )


@router.delete("/entries/{cache_key}", response_model=DeleteCacheEntryResponse)
@limiter.limit(app_rate_limit)
async def delete_cache_entry(
    request: Request,
    cache_key: CacheKeyPath,
    cache: SemanticCacheDependency,
    principal: AdminPrincipal,
) -> DeleteCacheEntryResponse:
    """Delete as admin; absent or out-of-scope entries share the public HTTP 404."""
    await cache.delete_entry(
        cache_key,
        authorized_namespaces=(
            None if principal.has_global_namespace_access else principal.namespaces
        ),
    )
    return DeleteCacheEntryResponse(deleted=True, cache_key=cache_key)


@router.delete("", response_model=ClearCacheResponse)
@limiter.limit(app_rate_limit)
async def clear_cache(
    request: Request,
    cache: SemanticCacheDependency,
    principal: AdminPrincipal,
    namespace: CacheNamespaceQuery = None,
) -> ClearCacheResponse:
    """Clear admin-authorized scope; only wildcard access permits global clearing."""
    authorized_namespace = resolve_namespace(principal, namespace, allow_global=True)
    await cache.clear(authorized_namespace)
    return ClearCacheResponse(cleared=True)


@router.get("/threshold", response_model=CacheThresholdResponse)
@limiter.limit(app_rate_limit)
async def get_threshold(
    request: Request,
    cache: SemanticCacheDependency,
    principal: ViewerPrincipal,
) -> CacheThresholdResponse:
    return CacheThresholdResponse(threshold=await cache.read_similarity_threshold())


@router.put("/threshold", response_model=CacheThresholdResponse)
@limiter.limit(app_rate_limit)
async def update_threshold(
    request: Request,
    payload: CacheThresholdRequest,
    cache: SemanticCacheDependency,
    principal: GlobalAdminPrincipal,
) -> CacheThresholdResponse:
    """Set the live global threshold through the global-admin dependency."""
    threshold = await cache.write_similarity_threshold(payload.threshold)
    return CacheThresholdResponse(threshold=threshold)
