from dataclasses import replace

from app.benchmark.domain.datasets import (
    EXTENDED_DATASET,
    QUICK_DATASET,
    dataset_semantics_digest,
)


def test_builtin_dataset_digests_are_stable() -> None:
    assert QUICK_DATASET.summary.version == "1.0.0"
    assert (
        QUICK_DATASET.summary.digest
        == "c3e933b5b3e57305ff896ab28caf7fc98f6a8c6784f27cc3cfd8d94442522091"
    )
    assert (
        EXTENDED_DATASET.summary.digest
        == "96238656a018be259989f93c9614c532d68ce19029568dd5e40c9c46c863cf66"
    )


def test_dataset_digest_changes_with_ordered_evaluation_semantics() -> None:
    cases = QUICK_DATASET.cases

    assert dataset_semantics_digest(tuple(reversed(cases))) != (
        QUICK_DATASET.summary.digest
    )
    assert (
        dataset_semantics_digest(
            (replace(cases[0], expected_cache_hit=True), *cases[1:])
        )
        != QUICK_DATASET.summary.digest
    )
