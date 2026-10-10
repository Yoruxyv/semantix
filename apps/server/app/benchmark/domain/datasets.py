"""Define ordered built-in cache-decision examples and semantic dataset identity.

Quick and extended are version 1.0.0; extended starts with the quick cases.
They illustrate expected reuse and unsafe-match cases, not statistical coverage
for every application. Order controls which earlier prompts can seed the cache.
Expected-hit flags express intended decisions; optional expected-match IDs give
reference context, not an additional identity check in execution. Categories group
cases and summaries preserve their first-occurrence order.
"""

import hashlib
import json
from collections.abc import Sequence

from app.benchmark.api.schemas import (
    BenchmarkDatasetId,
    BenchmarkDatasetSummary,
)
from app.benchmark.domain.models import BenchmarkCase, BenchmarkDataset

BUILTIN_DATASET_VERSION = "1.0.0"


def dataset_semantics_digest(cases: Sequence[BenchmarkCase]) -> str:
    """Hash the defined ordered semantic subset with SHA-256.

    For each case include ID, category, prompt and expected-hit flag, plus the
    expected-match ID when present. Serialize the ordered list as compact JSON
    with sorted object keys, UTF-8 and ensure_ascii=False. Reordering matters;
    dataset names/descriptions, case notes and version labels are excluded.

    Args:
        cases: Ordered validated cases used for dataset identity.

    Returns:
        Hex digest of the canonical semantic representation, not a privacy boundary.
    """
    ordered_semantics: list[dict[str, object]] = []
    for case in cases:
        semantics: dict[str, object] = {
            "case_id": case.case_id,
            "category": case.category,
            "prompt": case.prompt,
            "expected_cache_hit": case.expected_cache_hit,
        }
        if case.expected_match_case_id is not None:
            semantics["expected_match_case_id"] = case.expected_match_case_id
        ordered_semantics.append(semantics)
    canonical = json.dumps(
        ordered_semantics,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dataset(
    dataset_id: BenchmarkDatasetId,
    name: str,
    description: str,
    cases: tuple[BenchmarkCase, ...],
) -> BenchmarkDataset:
    """Build versioned built-in summary counts without changing case order."""
    expected_hits = sum(case.expected_cache_hit for case in cases)
    categories = list(dict.fromkeys(case.category for case in cases))
    return BenchmarkDataset(
        summary=BenchmarkDatasetSummary(
            dataset_id=dataset_id,
            dataset_source="builtin",
            schema_version=None,
            version=BUILTIN_DATASET_VERSION,
            digest=dataset_semantics_digest(cases),
            name=name,
            description=description,
            query_count=len(cases),
            expected_hits=expected_hits,
            expected_misses=len(cases) - expected_hits,
            categories=categories,
        ),
        cases=cases,
    )


QUICK_DATASET = _dataset(
    "quick",
    "Quick semantic safety set",
    "Eight ordered prompts covering reuse, typos, unrelated topics, negation, and intent boundaries.",
    (
        BenchmarkCase(
            "semantic-seed",
            "seed",
            "Explain semantic caching in simple terms.",
            False,
        ),
        BenchmarkCase(
            "semantic-exact",
            "exact_duplicate",
            "Explain semantic caching in simple terms.",
            True,
        ),
        BenchmarkCase(
            "semantic-paraphrase",
            "paraphrase",
            "What is semantic caching, explained simply?",
            True,
        ),
        BenchmarkCase(
            "semantic-typo",
            "typo",
            "Explain semantc cachng in simple terms.",
            True,
        ),
        BenchmarkCase(
            "unrelated-music",
            "unrelated",
            "Who is the Japanese rock duo Yorushika?",
            False,
        ),
        BenchmarkCase(
            "semantic-negation",
            "negation",
            "Explain why semantic caching should not be used for regulated decisions.",
            False,
        ),
        BenchmarkCase(
            "semantic-different-intent",
            "different_intent",
            "How do I invalidate one semantic cache entry?",
            False,
        ),
        BenchmarkCase(
            "music-exact",
            "exact_duplicate",
            "Who is the Japanese rock duo Yorushika?",
            True,
        ),
    ),
)


EXTENDED_DATASET = _dataset(
    "extended",
    "Extended semantic safety set",
    "The quick set plus additional paraphrase, typo, negation, and different-intent checks.",
    (
        *QUICK_DATASET.cases,
        BenchmarkCase(
            "music-paraphrase", "paraphrase", "Tell me about the band Yorushika.", True
        ),
        BenchmarkCase("music-typo", "typo", "Who are Yorushka?", True),
        BenchmarkCase(
            "music-negation",
            "negation",
            "Which artists are not members of Yorushika?",
            False,
        ),
        BenchmarkCase(
            "cache-cost-intent",
            "different_intent",
            "Calculate the infrastructure cost of a semantic cache.",
            False,
        ),
    ),
)

DATASETS: dict[BenchmarkDatasetId, BenchmarkDataset] = {
    "quick": QUICK_DATASET,
    "extended": EXTENDED_DATASET,
}
DEFAULT_DATASET_ID: BenchmarkDatasetId = "quick"


def list_datasets() -> list[BenchmarkDatasetSummary]:
    """Return shared built-in summaries in catalog insertion order."""
    return [dataset.summary for dataset in DATASETS.values()]


def get_dataset(dataset_id: BenchmarkDatasetId) -> BenchmarkDataset:
    """Return the shared built-in definition for a validated catalog ID.

    Raises:
        KeyError: A direct caller supplies an unknown ID outside schema validation.
    """
    return DATASETS[dataset_id]
