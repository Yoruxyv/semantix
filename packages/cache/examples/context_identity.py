"""Offline application-defined context recipes; run as examples.context_identity.

All names/data are synthetic. The toy vectors prove partitioning, not semantic
quality. Reuse the public wrapper from the custom integration example.
"""

import asyncio
import json
from collections.abc import Sequence
from functools import partial

from examples.custom_integration import CustomEmbedding, demo_model
from semantix_cache import (
    AsyncSemanticCache,
    EmbeddingSpace,
    EmbeddingSpaceError,
    MemoryStore,
)

PROMPT = "weather today"


def support_namespace(
    *,
    tenant: str,
    generation_revision: str,
    knowledge_revision: str,
    locale: str,
    output_contract: str,
) -> str:
    # These short aliases come from trusted application configuration AFTER auth.
    # This naming convention is illustrative; namespace does not authorize access.
    return (
        f"support:{tenant}:{generation_revision}:{knowledge_revision}:"
        f"{locale}:{output_contract}"
    )


async def partitioned_resolve() -> None:
    settings = {
        "tenant": "demo-a",
        "generation_revision": "g1",
        "knowledge_revision": "kb1",
        "locale": "en",
        "output_contract": "text1",
    }
    scopes = [
        ("original", settings),
        ("generation revision", {**settings, "generation_revision": "g2"}),
        ("tenant", {**settings, "tenant": "demo-b"}),
        ("knowledge/index revision", {**settings, "knowledge_revision": "kb2"}),
        ("locale", {**settings, "locale": "id"}),
        ("output contract", {**settings, "output_contract": "json1"}),
    ]
    embedder = CustomEmbedding(
        embedding_space=EmbeddingSpace(identity="demo-model:r1:raw:d2", dimensions=2),
        embed_text=demo_model,
    )
    generation_calls: list[str] = []

    async def generate(
        prompt: str,
        *,
        label: str,
        namespace: str,
        locale: str,
        output_contract: str,
    ) -> str:
        # Replace with YOUR async model/RAG/tool flow using these frozen inputs.
        generation_calls.append(label)
        answer = f"Demo answer [{namespace}]: {prompt}"
        if locale == "id":
            answer = f"Jawaban contoh [{namespace}]: {prompt}"
        if output_contract == "json1":
            return json.dumps({"answer": answer})
        return answer

    async with (
        MemoryStore(embedding_space=embedder.embedding_space) as store,
        AsyncSemanticCache(embedder=embedder, store=store) as cache,
    ):
        for label, configuration in scopes:
            namespace = support_namespace(**configuration)
            # Earlier scopes contain this exact prompt/vector; this scope is empty.
            if await cache.get(PROMPT, namespace=namespace) is not None:
                raise RuntimeError("A different application scope reused an answer")
            # Bind each scope explicitly; no late-bound loop closure or coalescing.
            generation = partial(
                generate,
                label=label,
                namespace=namespace,
                locale=configuration["locale"],
                output_contract=configuration["output_contract"],
            )
            first = await cache.resolve(
                PROMPT, namespace=namespace, generate=generation
            )
            second = await cache.resolve(
                PROMPT, namespace=namespace, generate=generation
            )
            if not (
                not first.cache_hit
                and first.provider_called
                and first.cache_written
                and second.cache_hit
                and second.generation_skipped
                and second.response == first.response
            ):
                raise RuntimeError("Scope did not produce an independent miss then hit")
            if configuration["output_contract"] == "json1" and set(
                json.loads(first.response)
            ) != {"answer"}:
                raise RuntimeError("JSON output contract was not preserved")
            if configuration["locale"] == "id" and not first.response.startswith(
                "Jawaban contoh"
            ):
                raise RuntimeError("Locale output contract was not preserved")
        if generation_calls != [label for label, _ in scopes]:
            raise RuntimeError("Generation was not skipped on each scope's hit")


async def lowercase_model(text: str) -> Sequence[float]:
    # Same logical demo model, changed preprocessing: a different vector space.
    return await demo_model(text.lower())


async def embedding_revision_and_migration() -> None:
    old = CustomEmbedding(
        embedding_space=EmbeddingSpace(identity="demo-model:r1:raw:d2", dimensions=2),
        embed_text=demo_model,
    )
    new = CustomEmbedding(
        embedding_space=EmbeddingSpace(identity="demo-model:r1:lower:d2", dimensions=2),
        embed_text=lowercase_model,
    )
    question = "Weather today"
    namespace = "migration:demo-a:g1:kb1:en:text1"
    if old.embedding_space.dimensions != new.embedding_space.dimensions or (
        await old.embed(question) == await new.embed(question)
    ):
        raise RuntimeError("Preprocessing demo must change vectors at equal dimensions")
    async with (
        MemoryStore(embedding_space=old.embedding_space) as old_store,
        MemoryStore(embedding_space=new.embedding_space) as new_store,
        AsyncSemanticCache(embedder=old, store=old_store) as old_cache,
    ):
        await old_cache.set(
            question, "Reviewed synthetic source answer", namespace=namespace
        )
        try:
            AsyncSemanticCache(embedder=new, store=old_store)
        except EmbeddingSpaceError:
            pass  # Equal dimensions do not allow an incompatible space binding.
        else:
            raise RuntimeError("Incompatible embedding-space binding was accepted")

        async with AsyncSemanticCache(embedder=new, store=new_store) as new_cache:
            if await new_cache.get(question, namespace=namespace) is not None:
                raise RuntimeError("A new embedding-space store must start empty")
            # Export only approved prompt/response text, then re-embed via set.
            # Real migrations must also review context and remaining retention.
            approved_export = [(question, "Reviewed synthetic source answer")]
            for prompt, response in approved_export:
                key = await new_cache.set(
                    prompt,
                    response,
                    namespace=namespace,
                    cache_ttl_seconds=60,
                )
                hit = await new_cache.get(prompt, namespace=namespace)
                if hit is None or hit.response != response:
                    raise RuntimeError("Re-embedded approved text was not reusable")
                if not await new_cache.delete(key, namespace=namespace) or (
                    await new_cache.get(prompt, namespace=namespace) is not None
                ):
                    raise RuntimeError("Delete must use the returned key and scope")
                await new_cache.set(
                    prompt,
                    response,
                    namespace=namespace,
                    cache_ttl_seconds=60,
                )
            if await new_cache.clear(namespace=namespace) != 1:
                raise RuntimeError("Clear must remove only the target namespace")
            # Delete/clear above did not touch the old store's bound space.
            if await old_cache.get(question, namespace=namespace) is None:
                raise RuntimeError("Migration mutated the old store")


async def main() -> None:
    await partitioned_resolve()
    await embedding_revision_and_migration()


if __name__ == "__main__":
    asyncio.run(main())
