"""Focused integrity, arithmetic and public-behavior checks for reuse evidence."""

import asyncio
import inspect
import json
import re
import subprocess
import sys
import tomllib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import benchmarks.reuse_quality.benchmark as quality
from benchmarks.reuse_quality.benchmark import (
    DATA,
    PUBLIC,
    ROOT,
    SCHEMAS,
    THRESHOLDS,
    LexicalEmbedder,
    Summary,
    SweepPoint,
    benchmark,
    canonical_bytes,
    file_digest,
    load_corpus,
    measure,
    preprocess,
    score,
    select_threshold,
    split_score,
    validate_evidence,
    write_label_review,
    write_reviewed_summary,
)
from semantix_cache import AsyncSemanticCache


def semantic_fixture_runs(summary: Summary) -> list[dict[str, Any]]:
    """Synthetic test projections; never model results or approval of the actual corpus."""
    runs = [run.model_dump() for run in summary.runs]
    versions = {
        **quality.runtime_versions(),
        **quality.SEMANTIC_PACKAGES,
        "tokenizers": "test-fixture",
        "safetensors": "test-fixture",
    }
    for normalization in ("raw", "whitespace", "NFC"):
        run = deepcopy(runs[0])
        run["embedding"] = quality.Embedding(
            baseline="minilm-l6-v2",
            identity=f"semantix-quality:minilm-l6-v2:{quality.SEMANTIC_REVISION}:d384:{normalization}",
            dimensions=384,
            normalization=normalization,
            revision=quality.SEMANTIC_REVISION,
            kind="pretrained-semantic",
            model_id=quality.SEMANTIC_MODEL,
            model_preprocessing=quality.SEMANTIC_PREPROCESSING,
            runtime_versions=versions,
        ).model_dump()
        runs.append(run)
    return runs


def test_corpus_version_split_and_portable_hash(tmp_path: Path) -> None:
    info, cases = load_corpus()
    assert info.version == "1.0.0"
    assert len(cases) == 80
    assert sum(c.split == "calibration" for c in cases) == 40
    assert sum(c.split == "held_out" for c in cases) == 40
    lf = canonical_bytes(DATA / "cases.jsonl")
    path = tmp_path / "windows.jsonl"
    path.write_bytes(lf.replace(b"\n", b"\r\n"))
    assert file_digest(path) == info.sha256
    path.write_bytes(lf.replace(b"\n", b"\r"))
    assert file_digest(path) == info.sha256
    path.write_bytes(lf + b"\n")
    assert file_digest(path) == info.sha256
    path.write_bytes(lf.replace(b"Queue", b"queue", 1))
    assert file_digest(path) != info.sha256


@pytest.mark.parametrize(
    "defect", ["duplicate", "malformed", "order", "secret", "label", "split", "hash"]
)
def test_bad_corpus_is_rejected(tmp_path: Path, defect: str) -> None:
    rows: list[dict[str, Any]] = [
        json.loads(line)
        for line in (DATA / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if defect == "duplicate":
        rows[1]["id"] = rows[0]["id"]
    elif defect == "malformed":
        rows[0]["id"] = "bad id"
    elif defect == "order":
        rows.reverse()
    elif defect == "secret":
        rows[0]["authorization"] = "test-only"
    elif defect == "label":
        rows[0]["expected_reuse"] = "true"
    elif defect == "split":
        rows[2]["source_prompt"] = rows[0]["source_prompt"]
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    info = json.loads((DATA / "corpus.manifest.json").read_text(encoding="utf-8"))
    if defect != "hash":
        info["sha256"] = file_digest(path)
    (tmp_path / "corpus.manifest.json").write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises((ValueError, ValidationError)):
        load_corpus(tmp_path)


def test_confusion_matrix_boundary_and_zero_denominators() -> None:
    result = score([True, False, True, False], [0.92, 0.92, 0.91, 0.91], 0.92)
    assert (
        result.true_positive,
        result.false_positive,
        result.false_negative,
        result.true_negative,
    ) == (1, 1, 1, 1)
    assert result.reuse_precision == result.reuse_recall == pytest.approx(0.5)
    assert (
        result.false_accept_rate
        == result.wrong_among_accepted
        == result.false_reject_rate
        == result.generation_avoidance
        == pytest.approx(0.5)
    )
    empty = score([], [], 0.92)
    assert empty.cases == 0
    assert (
        empty.wrong_among_accepted
        is empty.reuse_precision
        is empty.reuse_recall
        is empty.generation_avoidance
        is None
    )
    rejected = score([False], [0.1], 0.92)
    assert (
        rejected.wrong_among_accepted
        is rejected.reuse_precision
        is rejected.reuse_recall
        is rejected.false_reject_rate
        is None
    )
    assert rejected.false_accept_rate == rejected.generation_avoidance == 0


@pytest.mark.parametrize(
    ("labels", "scores", "threshold"),
    [
        ([True], [], 0.9),
        ([True], [float("nan")], 0.9),
        ([True], [1.1], 0.9),
        ([True], [1.0], float("inf")),
        ([True], [0.5], -0.1),
    ],
)
def test_malformed_score_inputs(
    labels: list[bool], scores: list[float], threshold: float
) -> None:
    with pytest.raises(ValueError, match="Invalid"):
        score(labels, scores, threshold)


def test_selection_ignores_held_out_labels() -> None:
    sweep = [
        SweepPoint(
            threshold=0.75,
            calibration=score([True, False], [0.85, 0.8], 0.75),
            held_out=score([True, False], [1, 0], 0.75),
        ),
        SweepPoint(
            threshold=0.85,
            calibration=score([True, False], [0.85, 0.8], 0.85),
            held_out=score([True, False], [0, 1], 0.85),
        ),
        SweepPoint(
            threshold=0.92,
            calibration=score([True, False], [0.85, 0.8], 0.92),
            held_out=score([True, False], [1, 0], 0.92),
        ),
    ]
    assert select_threshold(sweep) == pytest.approx(0.85)
    changed = [
        p.model_copy(update={"held_out": score([], [], p.threshold)}) for p in sweep
    ]
    assert select_threshold(changed) == pytest.approx(0.85)


async def test_fixed_embedding_scores_and_normalization_counterexamples() -> None:
    _, cases = load_corpus()
    case = next(c for c in cases if c.id == "unicode-004")
    raw = LexicalEmbedder("char-trigram", "raw")
    first = await raw.embed(case.source_prompt)
    assert first == await raw.embed(case.source_prompt)
    raw_score, _ = await measure(case, raw, "raw", 1.0)
    nfc_score, hit = await measure(
        case, LexicalEmbedder("char-trigram", "NFC"), "NFC", 0.97
    )
    assert raw_score < 0.97 <= nfc_score
    assert hit
    assert not case.expected_reuse
    assert preprocess("Queue", "NFC") != preprocess("queue", "NFC")
    assert preprocess("a+b", "whitespace") != preprocess("a-b", "whitespace")
    assert preprocess("1.25", "NFC") != preprocess("12.5", "NFC")
    assert preprocess("2.4", "NFC") != preprocess("4.2", "NFC")
    assert preprocess("A\u2009B", "whitespace") == "A B"
    assert inspect.signature(AsyncSemanticCache).parameters[
        "similarity_threshold"
    ].default == pytest.approx(0.92)
    assert (
        inspect.signature(AsyncSemanticCache).parameters["prompt_normalizer"].default
        is None
    )


@pytest.fixture(scope="module")
def development_result() -> tuple[Summary, list[dict[str, object]]]:
    return asyncio.run(benchmark())


def test_schema_accounting_privacy_and_source_hashes(
    development_result: tuple[Summary, list[dict[str, object]]],
) -> None:
    summary, _ = development_result
    assert summary.threshold_grid == list(THRESHOLDS)
    for relative, digest in summary.source_files_sha256.items():
        assert file_digest(ROOT / relative) == digest
    schema = json.loads((SCHEMAS / "summary.schema.json").read_text(encoding="utf-8"))
    assert schema == Summary.model_json_schema()
    dump = summary.model_dump()
    assert "source_prompt" not in json.dumps(dump)
    assert "source_response" not in json.dumps(dump)
    for key in (
        "authorization",
        "api_key",
        "environment",
        "account_id",
        "provider_raw_body",
    ):
        changed = {**dump, key: "test-only"}
        with pytest.raises(ValidationError):
            Summary.model_validate(changed)
    wrong = deepcopy(dump)
    wrong["runs"][0]["sweep"][0]["held_out"]["true_positive"] += 1
    with pytest.raises(ValidationError):
        Summary.model_validate(wrong)
    wrong = deepcopy(dump)
    wrong["runs"][0]["calibrated_threshold"] = 0.123
    with pytest.raises(ValidationError):
        Summary.model_validate(wrong)


@pytest.mark.parametrize(
    "receipt_host", [None, {"python": "3.11.0", "platform": "Linux-test-host"}]
)
def test_metrics_reproduce_from_fixed_offline_scores(
    development_result: tuple[Summary, list[dict[str, object]]],
    receipt_host: dict[str, str] | None,
) -> None:
    actual, raw = development_result
    _, cases = load_corpus()
    assert len(raw) == len(cases) * len(actual.runs)
    for run in actual.runs:
        rows = [
            row for row in raw if row["embedding_identity"] == run.embedding.identity
        ]
        assert [row["case_id"] for row in rows] == [case.id for case in cases]
        similarities = [float(str(row["similarity"])) for row in rows]
        for point in run.sweep:
            assert point.calibration == split_score(
                cases, similarities, point.threshold, "calibration"
            )
            assert point.held_out == split_score(
                cases, similarities, point.threshold, "held_out"
            )
    if PUBLIC.exists():
        expected = Summary.model_validate_json(PUBLIC.read_bytes())
        if receipt_host is not None:
            for run in expected.runs:
                run.embedding.runtime_versions.update(receipt_host)
        assert actual.corpus == expected.corpus
        assert actual.source_files_sha256 == expected.source_files_sha256
        # Host identity varies across the CI matrix; package versions and metrics do not.
        assert [
            r.model_dump(
                exclude={
                    "preprocessing_ns_per_prompt": True,
                    "embedding": {"runtime_versions": {"python", "platform"}},
                }
            )
            for r in actual.runs
        ] == [
            r.model_dump(
                exclude={
                    "preprocessing_ns_per_prompt": True,
                    "embedding": {"runtime_versions": {"python", "platform"}},
                }
            )
            for r in expected.runs
            if r.embedding.kind == "lexical-control"
        ]
    else:
        # Approved labels do not certify development computation or create a receipt.
        assert actual.corpus == load_corpus()[0]
        assert actual.evidence_kind == "development-benchmark"
        assert actual.certification == "unreviewed"


@pytest.mark.parametrize("existing", [False, True])
def test_public_creation_and_replacement_require_completed_review(
    tmp_path: Path,
    development_result: tuple[Summary, list[dict[str, object]]],
    existing: bool,
) -> None:
    summary, _ = development_result
    unreviewed = summary.model_copy(
        update={
            "corpus": summary.corpus.model_copy(update={"label_review": "unreviewed"}),
            "certification": "unreviewed",
            "evidence_kind": "development-benchmark",
        }
    )
    (tmp_path / "cases.jsonl").write_bytes(canonical_bytes(DATA / "cases.jsonl"))
    (tmp_path / "corpus.manifest.json").write_text(
        unreviewed.corpus.model_dump_json(), encoding="utf-8"
    )
    destination = tmp_path / "public/summary.json"
    if existing:
        destination.parent.mkdir()
        destination.write_text("preserve existing receipt", encoding="utf-8")
    with pytest.raises(ValueError, match="explicit maintainer"):
        write_reviewed_summary(unreviewed, directory=tmp_path, destination=destination)
    assert (
        destination.read_text(encoding="utf-8") == "preserve existing receipt"
        if existing
        else not destination.exists()
    )


@pytest.mark.parametrize("source_dirty", [False, True])
def test_reviewed_writer_checks_hash_and_matches_review_metadata(
    tmp_path: Path,
    development_result: tuple[Summary, list[dict[str, object]]],
    monkeypatch: pytest.MonkeyPatch,
    source_dirty: bool,
) -> None:
    # Review-complete metadata is a temporary test fixture, never written to the actual corpus.
    summary, _ = development_result
    summary = summary.model_copy(update={"source_dirty": source_dirty})
    info = summary.corpus.model_copy(update={"label_review": "maintainer-reviewed"})
    reviewed = Summary.model_validate(
        {
            **summary.model_dump(),
            "runs": semantic_fixture_runs(summary),
            "corpus": info.model_dump(),
            "source_dirty": False,
            "certification": "reviewed",
            "evidence_kind": "certified-static-benchmark",
        }
    )
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_bytes(canonical_bytes(DATA / "cases.jsonl"))
    manifest = tmp_path / "corpus.manifest.json"
    manifest.write_text(info.model_dump_json(), encoding="utf-8")
    destination = tmp_path / "summary.json"
    monkeypatch.setattr(
        "benchmarks.reuse_quality.benchmark.git_state",
        lambda: (summary.source_sha, False),
    )
    wrong_corpus = reviewed.model_copy(
        update={"corpus": info.model_copy(update={"version": "different"})}
    )
    with pytest.raises(ValueError, match="does not match"):
        write_reviewed_summary(
            wrong_corpus, directory=tmp_path, destination=destination
        )
    with pytest.raises(
        ValueError,
        match="clean accepted source"
        if source_dirty
        else "does not match the approved corpus",
    ):
        write_reviewed_summary(summary, directory=tmp_path, destination=destination)
    assert not destination.exists()
    write_reviewed_summary(reviewed, directory=tmp_path, destination=destination)
    assert Summary.model_validate_json(destination.read_bytes()) == reviewed
    # Replacement follows the same guard and validates canonical cases again.
    cases_path.write_text("changed", encoding="utf-8")
    before = destination.read_bytes()
    with pytest.raises(ValueError, match="hash mismatch"):
        write_reviewed_summary(reviewed, directory=tmp_path, destination=destination)
    assert destination.read_bytes() == before


def test_certification_cannot_claim_review_without_reviewed_labels(
    development_result: tuple[Summary, list[dict[str, object]]],
) -> None:
    summary, _ = development_result
    data = summary.model_dump()
    data["corpus"]["label_review"] = "unreviewed"
    data["certification"] = "reviewed"
    data["evidence_kind"] = "certified-static-benchmark"
    with pytest.raises(ValidationError, match="Certification"):
        Summary.model_validate(data)


def test_label_review_contains_every_case_and_required_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmarks.reuse_quality.benchmark.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    output = tmp_path / "review.md"
    write_label_review(output)
    text = output.read_text(encoding="utf-8")
    info, cases = load_corpus()
    assert info.sha256 in text
    for case in cases:
        assert f"## {case.id}\n" in text
        section = text.split(f"## {case.id}\n", 1)[1].split("\n## ", 1)[0]
        assert f"- expected_reuse: {str(case.expected_reuse).lower()}" in section
        assert f"- category: {case.category}" in section
        assert f"- split: {case.split}" in section
        for field in (
            "id",
            "category",
            "split",
            "source_prompt",
            "source_response",
            "candidate_prompt",
            "expected_reuse",
            "notes",
        ):
            assert field in section
        for field in ("source_prompt", "source_response", "candidate_prompt", "notes"):
            assert getattr(case, field) in section
    assert "\\u" in text


def test_label_review_refuses_unignored_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Git-ignored"):
        write_label_review(tmp_path / "unignored.md")


def test_public_reviewed_writer_refuses_dirty_or_stale_source(
    tmp_path: Path,
    development_result: tuple[Summary, list[dict[str, object]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, _ = development_result
    info = summary.corpus.model_copy(update={"label_review": "maintainer-reviewed"})
    (tmp_path / "cases.jsonl").write_bytes(canonical_bytes(DATA / "cases.jsonl"))
    (tmp_path / "corpus.manifest.json").write_text(
        info.model_dump_json(), encoding="utf-8"
    )
    reviewed = Summary.model_validate(
        {
            **summary.model_dump(),
            "runs": semantic_fixture_runs(summary),
            "source_dirty": False,
            "corpus": info.model_dump(),
            "certification": "reviewed",
            "evidence_kind": "certified-static-benchmark",
        }
    )
    destination = tmp_path / "summary.json"
    monkeypatch.setattr(
        "benchmarks.reuse_quality.benchmark.git_state",
        lambda: (summary.source_sha, True),
    )
    with pytest.raises(ValueError, match="clean accepted source"):
        write_reviewed_summary(reviewed, directory=tmp_path, destination=destination)
    monkeypatch.setattr(
        "benchmarks.reuse_quality.benchmark.git_state", lambda: ("0" * 40, False)
    )
    with pytest.raises(ValueError, match="clean accepted source"):
        write_reviewed_summary(reviewed, directory=tmp_path, destination=destination)
    monkeypatch.setattr(
        "benchmarks.reuse_quality.benchmark.git_state",
        lambda: (summary.source_sha, False),
    )
    stale = reviewed.model_copy(
        update={
            "source_files_sha256": {
                "packages/cache/benchmarks/reuse_quality/benchmark.py": "0" * 64
            }
        }
    )
    with pytest.raises(ValueError, match="stale"):
        write_reviewed_summary(stale, directory=tmp_path, destination=destination)
    assert not destination.exists()


@pytest.fixture
def reviewed_project(
    tmp_path: Path,
    development_result: tuple[Summary, list[dict[str, object]]],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Summary]:
    """Temporary reviewed receipt fixture; never approves or publishes actual evidence."""
    summary, _ = development_result
    for relative in quality.source_hashes():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    directory = tmp_path / "packages/cache/benchmarks/reuse_quality/data"
    info = summary.corpus.model_copy(update={"label_review": "maintainer-reviewed"})
    (directory / "corpus.manifest.json").write_text(
        info.model_dump_json(), encoding="utf-8"
    )
    monkeypatch.setattr(quality, "ROOT", tmp_path)
    reviewed = Summary.model_validate(
        {
            **summary.model_dump(),
            "runs": semantic_fixture_runs(summary),
            "source_dirty": False,
            "corpus": info.model_dump(),
            "certification": "reviewed",
            "evidence_kind": "certified-static-benchmark",
            "source_files_sha256": quality.source_hashes(),
        }
    )
    public = tmp_path / "apps/web/public/benchmarks/reuse-quality-summary.json"
    public.parent.mkdir(parents=True)
    public.write_text(reviewed.model_dump_json(), encoding="utf-8")
    return directory, public, reviewed


def test_validation_accepts_corpus_without_creating_public_evidence(
    tmp_path: Path,
) -> None:
    public = tmp_path / "absent.json"
    info, count, has_public = validate_evidence(public=public)
    assert info == load_corpus()[0]
    assert count == 80
    assert not has_public
    assert not public.exists()


@pytest.mark.parametrize(
    "change",
    [
        "cases",
        "cases-and-hash",
        "manifest",
        "runtime",
        "benchmark",
        "dependencies",
        "omitted-source",
    ],
)
def test_validation_rejects_changed_evidence_inputs(
    reviewed_project: tuple[Path, Path, Summary],
    change: str,
) -> None:
    directory, public, reviewed = reviewed_project
    if change in {"cases", "cases-and-hash"}:
        path = directory / "cases.jsonl"
        path.write_bytes(path.read_bytes().replace(b"Queue", b"QUEUE", 1))
        if change == "cases-and-hash":
            manifest = directory / "corpus.manifest.json"
            info = json.loads(manifest.read_bytes())
            info["sha256"] = file_digest(path)
            manifest.write_text(json.dumps(info), encoding="utf-8")
    elif change == "manifest":
        manifest = directory / "corpus.manifest.json"
        data = json.loads(manifest.read_bytes())
        data["version"] = "1.0.1"
        manifest.write_text(json.dumps(data), encoding="utf-8")
    elif change == "omitted-source":
        data = reviewed.model_dump()
        del data["source_files_sha256"]["packages/cache/src/semantix_cache/memory.py"]
        public.write_text(json.dumps(data), encoding="utf-8")
    else:
        relative = {
            "runtime": "packages/cache/src/semantix_cache/memory.py",
            "benchmark": "packages/cache/benchmarks/reuse_quality/benchmark.py",
            "dependencies": "packages/cache/uv.lock",
        }[change]
        path = quality.ROOT / relative
        path.write_bytes(path.read_bytes() + b"# intentional input change\n")
    with pytest.raises(ValueError, match=r"hash mismatch|stale"):
        validate_evidence(directory=directory, public=public)


@pytest.mark.parametrize(
    "defect",
    [
        "json",
        "schema-version",
        "corpus-schema",
        "review",
        "dirty",
        "workflow",
        "secret",
        "payload",
        "selection",
    ],
)
def test_validation_rejects_incompatible_public_artifacts(
    reviewed_project: tuple[Path, Path, Summary],
    defect: str,
) -> None:
    directory, public, reviewed = reviewed_project
    data = reviewed.model_dump()
    if defect == "json":
        public.write_text("{", encoding="utf-8")
    elif defect == "corpus-schema":
        manifest = directory / "corpus.manifest.json"
        info = json.loads(manifest.read_bytes())
        info["schema_version"] = 999
        manifest.write_text(json.dumps(info), encoding="utf-8")
    else:
        if defect == "schema-version":
            data["schema_version"] = 999
        elif defect == "review":
            data["certification"] = "unreviewed"
        elif defect == "dirty":
            data["source_dirty"] = True
        elif defect == "workflow":
            data["limitations"].append("Pending maintainer review of this receipt.")
        elif defect == "secret":
            data["api_key"] = "test-only"
        elif defect == "payload":
            data["source_prompt"] = "test-only"
        elif defect == "selection":
            data["runs"][0]["calibrated_threshold"] = 0.5
        public.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=r"malformed|workflow|schema_version"):
        validate_evidence(directory=directory, public=public)


@pytest.mark.parametrize(
    "defect",
    ["calibration-labels", "held-out-labels", "category-labels", "category-name"],
)
def test_receipt_counts_must_match_approved_corpus_labels(
    reviewed_project: tuple[Path, Path, Summary],
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    directory, public, reviewed = reviewed_project
    data = reviewed.model_dump()
    for run in data["runs"]:
        if defect == "category-name":
            run["held_out_categories"][0]["category"] = "not-in-corpus"
            run["held_out_categories"].sort(key=lambda item: item["category"])
        elif defect == "calibration-labels":
            for point in run["sweep"]:
                point["calibration"] = score(
                    [True] * 21 + [False] * 19, [0.0] * 40, point["threshold"]
                ).model_dump()
            run["calibrated_threshold"] = 1.0
        else:
            labels: list[bool] = []
            for index, category in enumerate(run["held_out_categories"]):
                category_labels = (
                    [True, True]
                    if index == 0
                    else [False, False]
                    if defect == "category-labels" and index == 1
                    else [True, False]
                )
                labels.extend(category_labels)
                metrics = score(category_labels, [0.0, 0.0], 1.0).model_dump()
                category["default"] = metrics
                category["calibrated"] = metrics
            for point in run["sweep"]:
                point["held_out"] = score(
                    labels, [0.0] * len(labels), point["threshold"]
                ).model_dump()
    # Arithmetic and category sums are valid; disagreement with input labels is not.
    incompatible = Summary.model_validate(data)
    public.write_text(incompatible.model_dump_json(), encoding="utf-8")
    before = public.read_bytes()
    with pytest.raises(ValueError, match="corpus labels"):
        validate_evidence(directory=directory, public=public)
    monkeypatch.setattr(quality, "git_state", lambda: (reviewed.source_sha, False))
    destination = directory.parent / "refused.json"
    with pytest.raises(ValueError, match="corpus labels"):
        write_reviewed_summary(
            incompatible, directory=directory, destination=destination
        )
    assert public.read_bytes() == before
    assert not destination.exists()


def test_validation_is_portable_and_ignores_head_unrelated_changes(
    reviewed_project: tuple[Path, Path, Summary],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, public, reviewed = reviewed_project
    monkeypatch.setattr(quality, "git_state", lambda: ("0" * 40, True))
    assert reviewed.source_sha != quality.git_state()[0]
    for relative in reviewed.source_files_sha256:
        path = quality.ROOT / relative
        path.write_bytes(
            path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        )
    docs = quality.ROOT / "docs/unrelated.md"
    docs.parent.mkdir()
    docs.write_text("Unrelated documentation change", encoding="utf-8")
    css = quality.ROOT / "apps/web/unrelated.css"
    css.write_text("/* unrelated frontend styling */", encoding="utf-8")
    assert validate_evidence(directory=directory, public=public)[2]


def test_validation_function_and_cli_make_no_file_writes(
    reviewed_project: tuple[Path, Path, Summary],
) -> None:
    directory, public, _ = reviewed_project

    def snapshot() -> dict[str, tuple[int, bytes]]:
        return {
            p.relative_to(quality.ROOT).as_posix(): (
                p.stat().st_mtime_ns,
                p.read_bytes(),
            )
            for p in quality.ROOT.rglob("*")
            if p.is_file()
        }

    before = snapshot()
    assert validate_evidence(directory=directory, public=public)[2]
    result = subprocess.run(
        [sys.executable, "-B", "-m", "benchmarks.reuse_quality.benchmark", "validate"],
        cwd=quality.ROOT / "packages/cache",
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Reviewed public summary valid" in result.stdout
    assert snapshot() == before


def test_precommit_filter_selects_only_benchmark_evidence_paths() -> None:
    text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    match = re.search(r"files: '(.+)'", text)
    assert match is not None
    pattern = re.compile(match.group(1))
    assert "always_run:" not in text
    for path in [
        "packages/cache/benchmarks/reuse_quality/benchmark.py",
        "packages/cache/benchmarks/reuse_quality/data/cases.jsonl",
        "packages/cache/benchmarks/reuse_quality/schemas/summary.schema.json",
        "apps/web/public/benchmarks/reuse-quality-summary.json",
        *quality.source_hashes(),
    ]:
        assert pattern.search(path), path
    for path in [
        "PRODUCT_PRINCIPLES.md",
        "docs/translation/guide.md",
        "apps/web/src/features/benchmark/quality/ReuseQuality.tsx",
        "apps/web/src/features/benchmark/quality/qualitySummary.ts",
        "apps/web/src/style.css",
        "apps/server/app/main.py",
        "packages/client/src/semantix_client/client.py",
        "packages/cache/src/semantix_cache/adapters/openai.py",
        "packages/cache/src/semantix_cache/stores/pgvector.py",
        "packages/cache/benchmarks/workloads.json",
    ]:
        assert not pattern.search(path), path


def test_explicit_refresh_recomputes_digest_without_approving_or_bumping(
    reviewed_project: tuple[Path, Path, Summary],
) -> None:
    directory, public, reviewed = reviewed_project
    path = directory / "cases.jsonl"
    changed = path.read_bytes().replace(b"Queue", b"QUEUE", 1)
    path.write_bytes(changed)
    before_receipt = public.read_bytes()
    with pytest.raises(ValueError, match="refresh-manifest"):
        validate_evidence(directory=directory, public=public)
    refreshed = quality.refresh_manifest(directory)
    assert refreshed.sha256 == file_digest(path)
    assert refreshed.version == reviewed.corpus.version
    assert refreshed.label_review == "unreviewed"
    assert path.read_bytes() == changed
    assert public.read_bytes() == before_receipt
    assert load_corpus(directory)[0] == refreshed


def test_schema_drift_prints_explicit_commands_and_never_refreshes(
    reviewed_project: tuple[Path, Path, Summary],
) -> None:
    directory, public, _ = reviewed_project
    path = directory.parent / "schemas/summary.schema.json"
    path.write_text('{"schema_version": 999}', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match=r"generate-schema.*check-schema"):
        validate_evidence(directory=directory, public=public)
    assert path.read_bytes() == before
    quality.generate_schema(path)
    quality.check_schema(path)


def test_existing_ci_and_hook_only_validate_state() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    hook = (ROOT / "ops/ci/validate_reuse_quality.py").read_text(encoding="utf-8")
    assert "python -B -m benchmarks.reuse_quality.benchmark validate" in workflow
    assert '"validate"' in hook
    for forbidden in ("--review-public", "refresh-manifest", "generate-schema"):
        assert forbidden not in workflow
        assert forbidden not in hook


def test_false_accept_denominators_cannot_be_interchanged() -> None:
    # TP=3, FP=1, FN=2, TN=4: distinct accepted/negative denominators.
    metrics = score([True] * 5 + [False] * 5, [1, 1, 1, 0, 0, 1, 0, 0, 0, 0], 0.92)
    assert metrics.false_positive == 1
    assert metrics.false_accept_rate == pytest.approx(1 / 5)
    assert metrics.wrong_among_accepted == pytest.approx(1 / 4)
    assert metrics.reuse_precision == pytest.approx(3 / 4)
    assert metrics.reuse_precision is not None
    assert metrics.wrong_among_accepted == pytest.approx(1 - metrics.reuse_precision)
    for field, wrong in (("false_accept_rate", 1 / 4), ("wrong_among_accepted", 1 / 5)):
        with pytest.raises(ValidationError, match="arithmetic"):
            quality.Metrics.model_validate({**metrics.model_dump(), field: wrong})


def test_whitespace_negative_has_a_literal_output_contract() -> None:
    info, cases = load_corpus()
    case = next(c for c in cases if c.id == "whitespace-002")
    assert '"A B"' in case.source_prompt
    assert case.source_response == "A B"
    assert '"AB"' in case.candidate_prompt
    assert "exactly" in case.source_prompt
    assert "exactly" in case.candidate_prompt
    assert not case.expected_reuse
    assert info.version == "1.0.0"


def test_semantic_packages_are_opt_in_and_match_identity_pins() -> None:
    project = tomllib.loads(
        (ROOT / "packages/cache/pyproject.toml").read_text(encoding="utf-8")
    )
    assert project["dependency-groups"]["reuse-quality"] == [
        f"{name}=={version}" for name, version in quality.SEMANTIC_PACKAGES.items()
    ]
    assert all(
        name not in " ".join(project["project"]["dependencies"])
        for name in quality.SEMANTIC_PACKAGES
    )
    assert "torch" not in sys.modules
    assert "sentence_transformers" not in sys.modules


@pytest.mark.parametrize(
    "change",
    [
        {"revision": "main"},
        {"dimensions": 2048},
        {"model_id": "unknown/model"},
        {"model_preprocessing": "unknown"},
        {"kind": "lexical-control"},
        {"runtime_versions": {"python": "test-fixture"}},
    ],
)
def test_semantic_model_identity_drift_is_rejected(
    development_result: tuple[Summary, list[dict[str, object]]],
    change: dict[str, Any],
) -> None:
    data = semantic_fixture_runs(development_result[0])[-1]["embedding"]
    with pytest.raises(ValidationError, match=r"model/configuration|revision"):
        quality.Embedding.model_validate({**data, **change})


async def test_semantic_adapter_uses_public_decisions_without_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    versions = {
        **quality.runtime_versions(),
        **quality.SEMANTIC_PACKAGES,
        "tokenizers": "test-fixture",
        "safetensors": "test-fixture",
    }
    monkeypatch.setattr(quality, "runtime_versions", lambda **kwargs: versions)

    class Model:
        def encode(self, text: str, **kwargs: Any) -> Any:
            calls.append(text)
            assert kwargs == {
                "batch_size": 1,
                "normalize_embeddings": True,
                "show_progress_bar": False,
                "convert_to_numpy": True,
                "precision": "float32",
            }
            return SimpleNamespace(tolist=lambda: [1.0] + [0.0] * 383)

    vectors: dict[str, list[float]] = {}
    embedder = quality.SemanticEmbedder("raw", Model(), vectors)
    case = load_corpus()[1][0]
    similarity, hit = await measure(case, embedder, "raw", 0.92)
    assert similarity == pytest.approx(1)
    assert hit
    assert calls == [case.source_prompt, case.candidate_prompt]
    await measure(case, embedder, "raw", 0.92)
    assert len(calls) == 2
    assert case.source_response not in calls
    assert case.notes not in calls


def test_reviewed_evidence_requires_all_semantic_ablations(
    development_result: tuple[Summary, list[dict[str, object]]],
) -> None:
    summary = development_result[0]
    data = {
        **summary.model_dump(),
        "corpus": summary.corpus.model_copy(
            update={"label_review": "maintainer-reviewed"}
        ).model_dump(),
        "source_dirty": False,
        "certification": "reviewed",
        "evidence_kind": "certified-static-benchmark",
    }
    with pytest.raises(ValidationError, match="pinned semantic"):
        Summary.model_validate(data)
    data["runs"] = semantic_fixture_runs(summary)
    assert Summary.model_validate(data).certification == "reviewed"
    data["runs"].pop()
    with pytest.raises(ValidationError, match="pinned semantic"):
        Summary.model_validate(data)
