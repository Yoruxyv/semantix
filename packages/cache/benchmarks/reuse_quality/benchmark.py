"""Offline, isolated-pair reuse evidence through the unchanged public cache API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import math as _math
import platform
import re
import subprocess
import typing as _typing
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any

import pydantic as _pydantic

from benchmarks.common import write_result
from benchmarks.reuse_quality import _contracts
from semantix_cache import (
    AsyncSemanticCache,
    CachePolicy,
    EmbeddingAdapter,
    EmbeddingSpace,
    MemoryStore,
)

# Preserve existing imports without restricting the module's star-import surface.
DIMENSIONS = _contracts.DIMENSIONS
LEXICAL_PREPROCESSING = _contracts.LEXICAL_PREPROCESSING
SEMANTIC_MODEL = _contracts.SEMANTIC_MODEL
SEMANTIC_PACKAGES = _contracts.SEMANTIC_PACKAGES
SEMANTIC_PREPROCESSING = _contracts.SEMANTIC_PREPROCESSING
SEMANTIC_REVISION = _contracts.SEMANTIC_REVISION
Baseline = _contracts.Baseline
CategoryResult = _contracts.CategoryResult
CorpusInfo = _contracts.CorpusInfo
Count = _contracts.Count
Digest = _contracts.Digest
Embedding = _contracts.Embedding
Identifier = _contracts.Identifier
LexicalBaseline = _contracts.LexicalBaseline
Metrics = _contracts.Metrics
Normalization = _contracts.Normalization
QualityCase = _contracts.QualityCase
Rate = _contracts.Rate
Run = _contracts.Run
Split = _contracts.Split
StrictModel = _contracts.StrictModel
Summary = _contracts.Summary
SweepPoint = _contracts.SweepPoint
ratio = _contracts.ratio
score = _contracts.score
select_threshold = _contracts.select_threshold
Annotated = _typing.Annotated
Literal = _typing.Literal
Self = _typing.Self
BaseModel = _pydantic.BaseModel
ConfigDict = _pydantic.ConfigDict
Field = _pydantic.Field
model_validator = _pydantic.model_validator
math = _math


ROOT = Path(__file__).resolve().parents[4]
FEATURE = Path(__file__).parent
DATA = FEATURE / "data"
SCHEMAS = FEATURE / "schemas"
PUBLIC = ROOT / "apps/web/public/benchmarks/reuse-quality-summary.json"
THRESHOLDS = (0.5, 0.65, 0.75, 0.85, 0.9, 0.92, 0.95, 0.97, 1.0)
CLI = "uv run --no-sync --offline python -B -m benchmarks.reuse_quality.benchmark"


def _canonical(content: bytes) -> bytes:
    text = content.decode("utf-8")
    return (text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n").encode(
        "utf-8"
    )


def canonical_bytes(path: Path) -> bytes:
    """UTF-8 content, CRLF/CR -> LF, exactly one final LF; no Unicode folding."""
    return _canonical(path.read_bytes())


def file_digest(path: Path) -> str:
    return hashlib.sha256(canonical_bytes(path)).hexdigest()


def read_cases(path: Path) -> list[QualityCase]:
    """Parse every case and validate the same invariants for reads and explicit refresh."""
    cases = [
        QualityCase.model_validate_json(line)
        for line in canonical_bytes(path).splitlines()
    ]
    ids = [case.id for case in cases]
    if not cases or ids != sorted(set(ids)):
        raise ValueError("Corpus IDs must be unique and sorted")
    families: dict[str, Split] = {}
    for case in cases:
        for prompt in (case.source_prompt, case.candidate_prompt):
            key = " ".join(unicodedata.normalize("NFC", prompt).split())
            if key in families and families[key] != case.split:
                raise ValueError("Prompt family crosses calibration/held-out split")
            families[key] = case.split
    for category in {case.category for case in cases}:
        for split in ("calibration", "held_out"):
            labels = [
                case.expected_reuse
                for case in cases
                if case.category == category and case.split == split
            ]
            if set(labels) != {False, True} or labels.count(True) != labels.count(
                False
            ):
                raise ValueError(
                    "Each category/split needs balanced positive and negative labels"
                )
    return cases


def load_corpus(directory: Path = DATA) -> tuple[CorpusInfo, list[QualityCase]]:
    info = CorpusInfo.model_validate_json(
        (directory / "corpus.manifest.json").read_bytes()
    )
    path = directory / "cases.jsonl"
    if file_digest(path) != info.sha256:
        raise ValueError(
            f"Corpus hash mismatch. From packages/cache run: {CLI} refresh-manifest. "
            "Review the input edits and follow the corpus-version policy."
        )
    return info, read_cases(path)


def refresh_manifest(directory: Path = DATA) -> CorpusInfo:
    """Explicit maintainer action; updates only the digest and resets changed-label review."""
    path = directory / "corpus.manifest.json"
    info = CorpusInfo.model_validate_json(path.read_bytes())
    cases_path = directory / "cases.jsonl"
    read_cases(cases_path)
    digest = file_digest(cases_path)
    if digest == info.sha256:
        return info
    refreshed = info.model_copy(update={"sha256": digest, "label_review": "unreviewed"})
    path.write_text(
        refreshed.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return refreshed


def runtime_versions(*, semantic: bool = False) -> dict[str, str]:
    packages = ["numpy", "pydantic"]
    if semantic:
        packages += [*SEMANTIC_PACKAGES, "tokenizers", "safetensors"]
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        **{p: importlib.metadata.version(p) for p in packages},
    }


def load_semantic_model(*, download: bool = False) -> Any:
    """Only explicit model runs import heavy dependencies or permit public downloads."""
    try:
        versions = runtime_versions(semantic=True)
    except importlib.metadata.PackageNotFoundError as error:
        raise ValueError(
            "Install benchmark-only dependencies: uv sync --locked --extra dev --group reuse-quality"
        ) from error
    if any(versions[p].split("+", 1)[0] != v for p, v in SEMANTIC_PACKAGES.items()):
        raise ValueError(
            "Semantic package versions differ from pinned benchmark configuration"
        )
    torch = importlib.import_module("torch")
    torch.set_num_threads(1)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    sentence_transformers = importlib.import_module("sentence_transformers")
    model = sentence_transformers.SentenceTransformer(
        SEMANTIC_MODEL,
        revision=SEMANTIC_REVISION,
        device="cpu",
        cache_folder=str(ROOT / ".cache/reuse-quality/model-cache"),
        local_files_only=not download,
        token=False,
        trust_remote_code=False,
        model_kwargs={"dtype": "float32", "attn_implementation": "eager"},
    )
    model.max_seq_length = 256
    model.eval()
    if model.get_embedding_dimension() != 384:
        raise ValueError("Pinned semantic model dimension differs")
    return model


def preprocess(text: str, normalization: Normalization) -> str:
    if normalization == "whitespace":
        return " ".join(text.split())
    return unicodedata.normalize("NFC", text) if normalization == "NFC" else text


class LexicalEmbedder:
    def __init__(self, baseline: LexicalBaseline, normalization: Normalization) -> None:
        self.baseline = baseline
        self.embedding_space = EmbeddingSpace(
            identity=f"semantix-quality:{baseline}:v1:d{DIMENSIONS}:{normalization}",
            dimensions=DIMENSIONS,
        )
        self.evidence = Embedding(
            baseline=baseline,
            identity=self.embedding_space.identity,
            dimensions=DIMENSIONS,
            normalization=normalization,
            revision=1,
            kind="lexical-control",
            model_id=None,
            model_preprocessing=LEXICAL_PREPROCESSING,
            runtime_versions=runtime_versions(),
        )

    async def embed(self, text: str) -> Sequence[float]:
        # ponytail: hashed lexical features collide and miss paraphrases; use the semantic baseline for model-quality evidence.
        features = (
            re.findall(r"[^\W_]+|[^\w\s]", text)
            if self.baseline == "token-count"
            else [text[i : i + 3] for i in range(max(1, len(text) - 2))]
        )
        vector = [0.0] * DIMENSIONS
        for feature in features or [text]:
            index = (
                int.from_bytes(
                    hashlib.sha256(feature.encode("utf-8")).digest()[:4], "big"
                )
                % DIMENSIONS
            )
            vector[index] += 1.0
        return vector


class SemanticEmbedder:
    def __init__(
        self,
        normalization: Normalization,
        model: Any,
        vectors: dict[str, list[float]],
    ) -> None:
        self.model = model
        # Replays share exact-text embeddings only, never labels or responses.
        self.vectors = vectors
        self.embedding_space = EmbeddingSpace(
            identity=f"semantix-quality:minilm-l6-v2:{SEMANTIC_REVISION}:d384:{normalization}",
            dimensions=384,
        )
        self.evidence = Embedding(
            baseline="minilm-l6-v2",
            identity=self.embedding_space.identity,
            dimensions=384,
            normalization=normalization,
            revision=SEMANTIC_REVISION,
            kind="pretrained-semantic",
            model_id=SEMANTIC_MODEL,
            model_preprocessing=SEMANTIC_PREPROCESSING,
            runtime_versions=runtime_versions(semantic=True),
        )

    async def embed(self, text: str) -> Sequence[float]:
        if text not in self.vectors:
            self.vectors[text] = self.model.encode(
                text,
                batch_size=1,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
                precision="float32",
            ).tolist()
        return self.vectors[text]


async def measure(
    case: QualityCase,
    embedder: EmbeddingAdapter,
    normalization: Normalization,
    threshold: float = 0.0,
) -> tuple[float, bool]:
    store = MemoryStore(embedding_space=embedder.embedding_space)
    cache = AsyncSemanticCache(
        embedder=embedder,
        store=store,
        similarity_threshold=threshold,
        prompt_normalizer=None
        if normalization == "raw"
        else lambda text: preprocess(text, normalization),
    )

    async def generate(prompt: str) -> str:
        return "synthetic miss: " + prompt

    try:
        await cache.set(
            case.source_prompt, case.source_response, namespace=case.context_id
        )
        result = await cache.resolve(
            case.candidate_prompt,
            generate=generate,
            namespace=case.context_id,
            policy=CachePolicy.READ_ONLY,
        )
        if result.similarity_score is None:
            raise ValueError("Isolated case has no candidate")
        return result.similarity_score, result.cache_hit
    finally:
        await cache.aclose()
        await store.aclose()


def split_score(
    cases: Sequence[QualityCase],
    similarities: Sequence[float],
    threshold: float,
    split: Split,
    category: str | None = None,
) -> Metrics:
    pairs = [
        (case.expected_reuse, value)
        for case, value in zip(cases, similarities, strict=True)
        if case.split == split and (category is None or case.category == category)
    ]
    return score([p[0] for p in pairs], [p[1] for p in pairs], threshold)


def git_state() -> tuple[str, bool]:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 -- fixed read-only Git command
        cwd=ROOT,
        text=True,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"],  # noqa: S607 -- fixed read-only Git command
        cwd=ROOT,
        text=True,
    )
    return sha, bool(dirty)


def check_schema(path: Path = SCHEMAS / "summary.schema.json") -> None:
    message = (
        "summary.schema.json drifted from the authoritative benchmark model. "
        f"From packages/cache explicitly run: {CLI} generate-schema; then {CLI} check-schema. "
        "Inspect the schema diff before regenerating reviewed evidence."
    )
    try:
        current = json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise ValueError(message) from error
    if current != Summary.model_json_schema():
        raise ValueError(message)


def generate_schema(path: Path = SCHEMAS / "summary.schema.json") -> None:
    """Explicit schema generation; never called by validation, hooks or CI."""
    path.write_text(
        json.dumps(Summary.model_json_schema(), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _source_paths(paths: Sequence[str]) -> list[str]:
    """Same complete input boundary for current files and a recorded Git tree."""
    fixed = {
        "packages/cache/benchmarks/__init__.py",
        "packages/cache/benchmarks/common.py",
        "packages/cache/pyproject.toml",
        "packages/cache/uv.lock",
        "packages/cache/benchmarks/reuse_quality/data/cases.jsonl",
        "packages/cache/benchmarks/reuse_quality/data/corpus.manifest.json",
        "packages/cache/benchmarks/reuse_quality/schemas/summary.schema.json",
    }
    return sorted(
        fixed
        | {
            path
            for path in paths
            if path.endswith(".py")
            and Path(path).parent.as_posix()
            in {
                "packages/cache/benchmarks/reuse_quality",
                "packages/cache/src/semantix_cache",
            }
        }
    )


def source_hashes() -> dict[str, str]:
    """Current MemoryStore execution inputs; excludes optional providers/stores."""
    paths = [
        p.relative_to(ROOT).as_posix()
        for directory in (
            "packages/cache/benchmarks/reuse_quality",
            "packages/cache/src/semantix_cache",
        )
        for p in (ROOT / directory).glob("*.py")
    ]
    return {path: file_digest(ROOT / path) for path in _source_paths(paths)}


def historical_source_hashes(source_sha: str) -> dict[str, str]:
    """Verify recorded inputs from immutable Git objects, without executing them."""
    if re.fullmatch(r"[a-f0-9]{40}", source_sha) is None:
        raise ValueError("Historical source revision must be a full commit SHA")

    def read(*args: str) -> bytes:
        return subprocess.check_output(  # noqa: S603 -- validated SHA and Git-owned paths; read-only arguments
            ["git", "--no-replace-objects", "--no-lazy-fetch", *args],  # noqa: S607 -- fixed local Git executable
            cwd=ROOT,
            stderr=subprocess.PIPE,
            timeout=10,
        )

    try:
        if read("cat-file", "-t", source_sha).strip() != b"commit":
            raise ValueError("Historical source revision is not a commit")
        paths = (
            read("ls-tree", "-rz", "--name-only", source_sha)
            .decode("utf-8")
            .split("\0")
        )
        return {
            path: hashlib.sha256(
                _canonical(read("show", source_sha + ":" + path))
            ).hexdigest()
            for path in _source_paths(paths)
        }
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ValueError(
            "Historical source revision is unavailable or unreadable; restore its Git history before validating evidence"
        ) from None


def check_corpus_accounting(summary: Summary, cases: Sequence[QualityCase]) -> None:
    """Check receipt populations against input labels, without model inference."""
    calibration = [case for case in cases if case.split == "calibration"]
    held_out = [case for case in cases if case.split == "held_out"]

    def check(metrics: Metrics, group: Sequence[QualityCase]) -> None:
        positives = sum(case.expected_reuse for case in group)
        if (
            metrics.true_positive + metrics.false_negative,
            metrics.false_positive + metrics.true_negative,
        ) != (positives, len(group) - positives):
            raise ValueError("Summary confusion counts disagree with corpus labels")

    for run in summary.runs:
        for point in run.sweep:
            check(point.calibration, calibration)
            check(point.held_out, held_out)
        if {category.category for category in run.held_out_categories} != {
            case.category for case in held_out
        }:
            raise ValueError("Summary categories disagree with corpus labels")
        for category in run.held_out_categories:
            group = [case for case in held_out if case.category == category.category]
            check(category.default, group)
            check(category.calibrated, group)


def validate_evidence(
    *,
    directory: Path = DATA,
    public: Path = PUBLIC,
) -> tuple[CorpusInfo, int, bool]:
    """Check frozen receipt integrity against its recorded source, not today's code."""
    info, cases = load_corpus(directory)
    check_schema(directory.parent / "schemas/summary.schema.json")
    if not public.exists():
        return info, len(cases), False
    try:
        summary = Summary.model_validate_json(public.read_bytes())
    except ValueError as error:
        raise ValueError(
            "Public summary is malformed or incompatible; inspect its schema and review state"
        ) from error
    require_completed_review(info)
    if (
        summary.source_dirty
        or summary.certification != "reviewed"
        or summary.evidence_kind != "certified-static-benchmark"
    ):
        raise ValueError(
            "Public summary must describe reviewed evidence from clean source"
        )
    if re.search(
        r"\b(?:pending|agent)[-\s]*(?:review|approval|maintainer)|\b(?:review|approval|maintainer)[-\w\s;]*pending",
        summary.model_dump_json(),
        flags=re.IGNORECASE,
    ):
        raise ValueError("Public summary contains workflow review wording")
    if summary.corpus != info:
        raise ValueError(
            "Historical receipt does not match the maintained frozen corpus"
        )
    if summary.source_files_sha256 != historical_source_hashes(summary.source_sha):
        raise ValueError(
            "Historical receipt source fingerprints do not match the recorded revision"
        )
    if (
        summary.threshold_grid != list(THRESHOLDS)
        or summary.default_threshold
        != inspect.signature(AsyncSemanticCache)
        .parameters["similarity_threshold"]
        .default
        or summary.calibration_cases != sum(c.split == "calibration" for c in cases)
        or summary.held_out_cases != sum(c.split == "held_out" for c in cases)
    ):
        raise ValueError(
            "Public summary configuration/counts disagree with current benchmark inputs"
        )
    check_corpus_accounting(summary, cases)
    return info, len(cases), True


async def benchmark(
    *,
    semantic: bool = False,
    download_model: bool = False,
    review_public: bool = False,
) -> tuple[Summary, list[dict[str, object]]]:
    info, cases = load_corpus()
    default = float(
        inspect.signature(AsyncSemanticCache).parameters["similarity_threshold"].default
    )
    runs: list[Run] = []
    raw: list[dict[str, object]] = []
    model = load_semantic_model(download=download_model) if semantic else None
    vectors: dict[str, list[float]] = {}
    baselines: tuple[Baseline, ...] = (
        ("minilm-l6-v2", "token-count", "char-trigram")
        if semantic
        else ("token-count", "char-trigram")
    )
    normalizations: tuple[Normalization, ...] = ("raw", "whitespace", "NFC")
    for baseline in baselines:
        for normalization in normalizations:
            embedder = (
                SemanticEmbedder(normalization, model, vectors)
                if baseline == "minilm-l6-v2"
                else LexicalEmbedder(baseline, normalization)
            )
            similarities: list[float] = []
            started = perf_counter_ns()
            for _ in range(100):
                for case in cases:
                    preprocess(case.source_prompt, normalization)
                    preprocess(case.candidate_prompt, normalization)
            cost = (perf_counter_ns() - started) / (200 * len(cases))
            for case in cases:
                similarity, _ = await measure(case, embedder, normalization)
                similarities.append(similarity)
                raw.append(
                    {
                        "case_id": case.id,
                        "embedding_identity": embedder.embedding_space.identity,
                        "similarity": similarity,
                    }
                )
            sweep = [
                SweepPoint(
                    threshold=t,
                    calibration=split_score(cases, similarities, t, "calibration"),
                    held_out=split_score(cases, similarities, t, "held_out"),
                )
                for t in THRESHOLDS
            ]
            selected = select_threshold(sweep)
            # Verify projected decisions against real resolve at both report thresholds.
            for threshold in {default, selected}:
                for case, similarity in zip(cases, similarities, strict=True):
                    _, hit = await measure(case, embedder, normalization, threshold)
                    if hit != (similarity >= threshold):
                        raise ValueError("Projection disagrees with public resolve")
            runs.append(
                Run(
                    embedding=embedder.evidence,
                    calibrated_threshold=selected,
                    sweep=sweep,
                    held_out_categories=[
                        CategoryResult(
                            category=category,
                            default=split_score(
                                cases, similarities, default, "held_out", category
                            ),
                            calibrated=split_score(
                                cases, similarities, selected, "held_out", category
                            ),
                        )
                        for category in sorted({c.category for c in cases})
                    ],
                    preprocessing_ns_per_prompt=cost,
                )
            )
    source_sha, source_dirty = await asyncio.to_thread(git_state)
    summary = Summary(
        schema_version=1,
        benchmark="semantix-reuse-quality",
        evidence_kind="certified-static-benchmark"
        if review_public
        else "development-benchmark",
        certification="reviewed" if review_public else "unreviewed",
        source_sha=source_sha,
        source_dirty=source_dirty,
        source_files_sha256=source_hashes(),
        generated_at_utc=datetime.now(UTC).isoformat(),
        corpus=info,
        calibration_cases=sum(c.split == "calibration" for c in cases),
        held_out_cases=sum(c.split == "held_out" for c in cases),
        default_threshold=default,
        threshold_grid=list(THRESHOLDS),
        selection_rule="calibration only: minimize FP, then maximize TP, then highest threshold",
        similarity_semantics="MemoryStore float64 cosine; inclusive >=; one seeded candidate per isolated case",
        runs=runs,
        limitations=[
            "Small independently authored synthetic corpus; label approval does not establish production-domain validity.",
            "MiniLM is one pinned English semantic baseline, not universal provider quality; its tokenizer can erase exact-character distinctions.",
            "Lexical controls are deterministic stress tests and do not establish semantic-model quality.",
            "Isolated single-candidate pairs do not measure retrieval competition, production hit rate, latency savings or token cost.",
            "Held-out sweep is descriptive; threshold selection uses calibration labels only. Do not retune on this holdout.",
            "Generation avoidance includes wrong reuse; zero observed false accepts is not a safety guarantee.",
            "MemoryStore only; PostgreSQL vector precision can differ near thresholds.",
            "Preprocessing timings are local microbenchmarks, excluding cache canonicalization/embedding; no confidence intervals or universal optimum.",
            "Runtime threshold and normalization defaults are unchanged.",
        ],
    )
    return summary, raw


def require_completed_review(info: CorpusInfo) -> None:
    if info.label_review != "maintainer-reviewed":
        raise ValueError(
            "Public summary requires explicit maintainer corpus-label approval"
        )


def write_reviewed_summary(
    summary: Summary,
    *,
    directory: Path = DATA,
    destination: Path = PUBLIC,
) -> None:
    """Guard both creation and replacement; recheck the canonical corpus on disk."""
    info, cases = load_corpus(directory)
    require_completed_review(info)
    if summary.source_dirty:
        raise ValueError("Public reviewed summary requires clean accepted source")
    source_sha, source_dirty = git_state()
    if source_dirty or source_sha != summary.source_sha:
        raise ValueError(
            "Public reviewed summary requires current clean accepted source"
        )
    if summary.source_files_sha256 != source_hashes():
        raise ValueError("Public reviewed summary source evidence is stale")
    checked = Summary.model_validate(summary.model_dump())
    if checked.corpus != info or checked.certification != "reviewed":
        raise ValueError("Reviewed summary does not match the approved corpus")
    check_corpus_accounting(checked, cases)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        checked.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def write_label_review(output: Path) -> None:
    """Generate all labels for human review in a Git-ignored Markdown artifact."""
    info, cases = load_corpus()
    check = subprocess.run(  # noqa: S603 -- fixed local Git command
        ["git", "check-ignore", "--quiet", str(output.resolve())],  # noqa: S607 -- fixed Git tool
        cwd=ROOT,
        check=False,
    )
    if check.returncode != 0:
        raise ValueError("Label review output must be in a Git-ignored directory")
    lines = [
        "# Semantix corpus label review",
        "",
        f"Version: {info.version}",
        f"Canonical cases SHA256: {info.sha256}",
        f"Label review state: {info.label_review}",
        f"Cases: {len(cases)}; calibration: "
        f"{sum(c.split == 'calibration' for c in cases)}; held-out: "
        f"{sum(c.split == 'held_out' for c in cases)}",
        "",
        "Review every source response against the candidate request in its stated task context.",
        "REUSE means that exact cached response satisfies the candidate; topic overlap is insufficient.",
        "Approve this version and hash explicitly, or list corrections by case ID.",
        "Approval changes metadata only. Content/label corrections recompute the hash and renew review; version according to the data README.",
        "No benchmark result or public certification is finalized by generating this view.",
        "JSON text escapes below expose tabs, newlines and non-ASCII Unicode code points without changing the input.",
        "",
    ]
    for case in cases:
        lines.extend(
            [
                f"## {case.id}",
                "",
                f"- id: {case.id}",
                f"- category: {case.category}",
                f"- split: {case.split}",
                f"- expected_reuse: {str(case.expected_reuse).lower()}",
                f"- context_id: {case.context_id}",
                "",
            ]
        )
        for field in ("source_prompt", "source_response", "candidate_prompt", "notes"):
            value = getattr(case, field)
            lines.extend(
                [
                    f"### {field}",
                    "",
                    "~~~text",
                    value,
                    "~~~",
                    "",
                ]
            )
            if field != "notes":
                lines.extend(["JSON text: " + json.dumps(value, ensure_ascii=True), ""])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "run",
            "validate",
            "refresh-manifest",
            "generate-schema",
            "check-schema",
        ),
        default="run",
    )
    parser.add_argument("--output", type=Path, help="Ignored raw result path")
    parser.add_argument(
        "--review-corpus", type=Path, help="Generate ignored label-review Markdown"
    )
    parser.add_argument(
        "--review-public",
        action="store_true",
        help="Replace the reviewed static manifest after explicit maintainer label approval",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Include the pinned local pretrained semantic baseline",
    )
    parser.add_argument(
        "--download-model",
        action="store_true",
        help="Explicitly allow downloading the pinned public model for --semantic",
    )
    args = parser.parse_args()
    if args.download_model and not args.semantic:
        parser.error("--download-model requires --semantic")
    if args.command != "run":
        if any(
            (
                args.output,
                args.review_corpus,
                args.review_public,
                args.semantic,
                args.download_model,
            )
        ):
            parser.error(
                f"{args.command} only validates state or explicitly updates metadata/schema; no model/output/review options"
            )
        try:
            if args.command == "validate":
                info, count, has_public = validate_evidence()
                print(  # noqa: T201 -- CLI validation status
                    f"Corpus valid: {info.version}, {count} cases, SHA256 {info.sha256}"
                )
                print(  # noqa: T201 -- CLI validation status
                    "Reviewed public summary valid against recorded historical source; no model evaluation rerun."
                    if has_public
                    else "Public summary absent; reviewed benchmark evidence is unavailable."
                )
            else:
                {
                    "refresh-manifest": refresh_manifest,
                    "generate-schema": generate_schema,
                    "check-schema": check_schema,
                }[args.command]()
        except (OSError, ValueError) as error:
            parser.exit(1, f"Reuse-quality {args.command} failed: {error}\n")
        return
    if args.review_corpus:
        if args.output or args.review_public or args.semantic or args.download_model:
            parser.error("--review-corpus is separate from benchmark execution")
        write_label_review(args.review_corpus)
        return
    if not args.output:
        parser.error("--output is required for benchmark execution")
    if args.review_public:
        if not args.semantic:
            parser.error("--review-public requires --semantic")
        require_completed_review(load_corpus()[0])
        if git_state()[1]:
            parser.error("--review-public requires clean accepted source")
    summary, raw = asyncio.run(
        benchmark(
            semantic=args.semantic,
            download_model=args.download_model,
            review_public=args.review_public,
        )
    )
    write_result(args.output, {"summary": summary.model_dump(), "scores": raw})
    if args.review_public:
        write_reviewed_summary(summary)


if __name__ == "__main__":
    main()
