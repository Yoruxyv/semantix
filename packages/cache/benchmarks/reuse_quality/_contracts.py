"""Pure data contracts and calibration for the version-one reuse-quality benchmark.

QualityCase and CorpusInfo describe frozen inputs. Metrics, SweepPoint and
CategoryResult enforce confusion-matrix accounting; Embedding records the pinned
lexical or semantic identity. Run and Summary validate complete report evidence,
including calibration-only selection and review restrictions.

These contracts perform no file or Git operations and load no embedding models.
The runner collects evidence and owns resources, provenance and publication.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

DIMENSIONS: Literal[2048] = 2048
Normalization = Literal["raw", "whitespace", "NFC"]
LexicalBaseline = Literal["token-count", "char-trigram"]
Baseline = Literal["token-count", "char-trigram", "minilm-l6-v2"]
SEMANTIC_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SEMANTIC_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
SEMANTIC_PACKAGES = {
    "sentence-transformers": "6.1.0",
    "torch": "2.14.1",
    "transformers": "5.18.0",
    "huggingface-hub": "1.33.0",
}
SEMANTIC_PREPROCESSING = (
    "pinned uncased tokenizer; max_seq_length=256; mean pooling; "
    "float32 CPU; batch_size=1; normalize_embeddings=True; threads=1; deterministic"
)
LEXICAL_PREPROCESSING = (
    "sha256-feature-counts-v1; case-sensitive; cache L2 normalization"
)
Split = Literal["calibration", "held_out"]
Count = Annotated[int, Field(ge=0)]
Rate = Annotated[float, Field(ge=0, le=1)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class QualityCase(StrictModel):
    id: Identifier
    category: Identifier
    split: Split
    source_prompt: str = Field(min_length=1, max_length=2000)
    source_response: str = Field(min_length=1, max_length=100000)
    candidate_prompt: str = Field(min_length=1, max_length=2000)
    expected_reuse: bool
    context_id: Identifier
    notes: str = Field(min_length=1, max_length=1000)


class CorpusInfo(StrictModel):
    schema_version: Literal[1]
    version: str = Field(min_length=1)
    sha256: Digest
    provenance: Literal["independently-authored-synthetic"]
    label_review: Literal["unreviewed", "maintainer-reviewed"]
    split_policy: str = Field(min_length=1)


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


class Metrics(StrictModel):
    cases: Count
    true_positive: Count
    false_positive: Count
    false_negative: Count
    true_negative: Count
    reuse_precision: Rate | None
    reuse_recall: Rate | None
    false_accept_rate: Rate | None
    wrong_among_accepted: Rate | None
    false_reject_rate: Rate | None
    generation_avoidance: Rate | None

    @model_validator(mode="after")
    def accounting(self) -> Self:
        tp, fp, fn, tn = (
            self.true_positive,
            self.false_positive,
            self.false_negative,
            self.true_negative,
        )
        expected = (
            ratio(tp, tp + fp),
            ratio(tp, tp + fn),
            ratio(fp, fp + tn),
            ratio(fp, tp + fp),
            ratio(fn, tp + fn),
            ratio(tp + fp, self.cases),
        )
        actual = (
            self.reuse_precision,
            self.reuse_recall,
            self.false_accept_rate,
            self.wrong_among_accepted,
            self.false_reject_rate,
            self.generation_avoidance,
        )
        if tp + fp + fn + tn != self.cases or any(
            a != b and (a is None or b is None or not math.isclose(a, b, abs_tol=1e-12))
            for a, b in zip(actual, expected, strict=True)
        ):
            raise ValueError("Invalid confusion-matrix arithmetic")
        return self


def score(
    labels: Sequence[bool], similarities: Sequence[float], threshold: float
) -> Metrics:
    """Score inclusive threshold decisions without executing an embedding model.

    Args:
        labels: Expected reuse decisions in similarity order.
        similarities: Finite cosine scores between -1 and 1.
        threshold: Inclusive acceptance boundary between 0 and 1.

    Returns:
        Validated confusion counts and rates, with None for zero denominators.
    """
    if (
        len(labels) != len(similarities)
        or not 0 <= threshold <= 1
        or not math.isfinite(threshold)
    ):
        raise ValueError("Invalid score inputs")
    counts = [0, 0, 0, 0]  # TP, FP, FN, TN
    for label, similarity in zip(labels, similarities, strict=True):
        if (
            type(label) is not bool
            or not math.isfinite(similarity)
            or not -1 <= similarity <= 1
        ):
            raise ValueError("Invalid label/similarity")
        accepted = similarity >= threshold
        counts[0 if label and accepted else 1 if accepted else 2 if label else 3] += 1
    tp, fp, fn, tn = counts
    return Metrics(
        cases=len(labels),
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
        reuse_precision=ratio(tp, tp + fp),
        reuse_recall=ratio(tp, tp + fn),
        false_accept_rate=ratio(fp, fp + tn),
        wrong_among_accepted=ratio(fp, tp + fp),
        false_reject_rate=ratio(fn, tp + fn),
        generation_avoidance=ratio(tp + fp, len(labels)),
    )


class SweepPoint(StrictModel):
    threshold: Rate
    calibration: Metrics
    held_out: Metrics


class CategoryResult(StrictModel):
    category: Identifier
    default: Metrics
    calibrated: Metrics


class Embedding(StrictModel):
    baseline: Baseline
    identity: str = Field(min_length=1)
    dimensions: Literal[2048, 384]
    normalization: Normalization
    revision: Literal[1] | Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    kind: Literal["lexical-control", "pretrained-semantic"]
    model_id: str | None
    model_preprocessing: str
    runtime_versions: dict[str, str]

    @model_validator(mode="after")
    def configuration(self) -> Self:
        semantic = self.baseline == "minilm-l6-v2"
        revision = SEMANTIC_REVISION if semantic else 1
        dimensions = 384 if semantic else DIMENSIONS
        identity = (
            f"semantix-quality:{self.baseline}:"
            f"{revision if semantic else 'v1'}:d{dimensions}:{self.normalization}"
        )
        if (
            self.identity != identity
            or self.dimensions != dimensions
            or self.revision != revision
            or self.kind != ("pretrained-semantic" if semantic else "lexical-control")
            or self.model_id != (SEMANTIC_MODEL if semantic else None)
            or self.model_preprocessing
            != (SEMANTIC_PREPROCESSING if semantic else LEXICAL_PREPROCESSING)
            or any(
                not self.runtime_versions.get(p)
                for p in ("python", "numpy", "pydantic", "platform")
            )
            or (
                semantic
                and any(
                    self.runtime_versions.get(p, "").split("+", 1)[0] != v
                    for p, v in SEMANTIC_PACKAGES.items()
                )
            )
            or (
                semantic
                and any(
                    not self.runtime_versions.get(p)
                    for p in ("tokenizers", "safetensors")
                )
            )
        ):
            raise ValueError("Embedding model/configuration/version evidence disagrees")
        return self


class Run(StrictModel):
    embedding: Embedding
    calibrated_threshold: Rate
    sweep: list[SweepPoint] = Field(min_length=2)
    held_out_categories: list[CategoryResult] = Field(min_length=1)
    preprocessing_ns_per_prompt: Annotated[float, Field(ge=0)]


class Summary(StrictModel):
    schema_version: Literal[1]
    benchmark: Literal["semantix-reuse-quality"]
    evidence_kind: Literal["development-benchmark", "certified-static-benchmark"]
    certification: Literal["unreviewed", "reviewed"]
    source_sha: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    source_dirty: bool
    source_files_sha256: dict[str, Digest]
    generated_at_utc: str
    corpus: CorpusInfo
    calibration_cases: Count
    held_out_cases: Count
    default_threshold: Rate
    threshold_grid: list[Rate]
    selection_rule: Literal[
        "calibration only: minimize FP, then maximize TP, then highest threshold"
    ]
    similarity_semantics: Literal[
        "MemoryStore float64 cosine; inclusive >=; one seeded candidate per isolated case"
    ]
    runs: list[Run] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def structure(self) -> Self:
        reviewed = self.certification == "reviewed"
        if (
            reviewed
            and (self.corpus.label_review != "maintainer-reviewed" or self.source_dirty)
        ) or self.evidence_kind != (
            "certified-static-benchmark" if reviewed else "development-benchmark"
        ):
            raise ValueError("Certification must agree with completed corpus review")
        if (
            self.default_threshold not in self.threshold_grid
            or self.threshold_grid != sorted(set(self.threshold_grid))
        ):
            raise ValueError("Invalid threshold grid")
        if (
            not self.calibration_cases
            or not self.held_out_cases
            or not self.source_files_sha256
        ):
            raise ValueError("Missing split/source evidence")
        if datetime.fromisoformat(self.generated_at_utc).utcoffset() != UTC.utcoffset(
            None
        ):
            raise ValueError("Timestamp must be UTC")
        if reviewed and {
            r.embedding.normalization
            for r in self.runs
            if r.embedding.kind == "pretrained-semantic"
        } != {"raw", "whitespace", "NFC"}:
            raise ValueError(
                "Reviewed evidence requires the pinned semantic baseline and all normalization ablations"
            )
        identities = [run.embedding.identity for run in self.runs]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate embedding run")
        for run in self.runs:
            if [point.threshold for point in run.sweep] != self.threshold_grid:
                raise ValueError("Incomplete threshold sweep")
            if any(
                point.calibration.cases != self.calibration_cases
                or point.held_out.cases != self.held_out_cases
                for point in run.sweep
            ):
                raise ValueError("Split counts disagree")
            selected = select_threshold(run.sweep)
            if run.calibrated_threshold != selected:
                raise ValueError("Threshold must be selected only on calibration")
            categories = [c.category for c in run.held_out_categories]
            if categories != sorted(set(categories)):
                raise ValueError("Categories must be unique and sorted")
            for field in ("default", "calibrated"):
                point = next(
                    p
                    for p in run.sweep
                    if p.threshold
                    == (self.default_threshold if field == "default" else selected)
                )
                for count in (
                    "cases",
                    "true_positive",
                    "false_positive",
                    "false_negative",
                    "true_negative",
                ):
                    if sum(
                        getattr(getattr(c, field), count)
                        for c in run.held_out_categories
                    ) != getattr(point.held_out, count):
                        raise ValueError("Category accounting disagrees")
        return self


def select_threshold(sweep: Sequence[SweepPoint]) -> float:
    """Choose by calibration FP, then TP, then highest threshold.

    Held-out metrics never influence selection. An empty sweep retains min()'s
    ValueError rather than inventing a default calibration result.
    """
    return min(
        sweep,
        key=lambda p: (
            p.calibration.false_positive,
            -p.calibration.true_positive,
            -p.threshold,
        ),
    ).threshold
