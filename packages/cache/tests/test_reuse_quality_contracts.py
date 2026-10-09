"""Import-boundary and calibration regressions for pure benchmark contracts."""

import math
import subprocess
import sys
import typing
from pathlib import Path

import pydantic
import pytest

from benchmarks.reuse_quality import _contracts as contracts
from benchmarks.reuse_quality import benchmark as quality


@pytest.mark.parametrize(
    "name",
    [
        "DIMENSIONS",
        "SEMANTIC_MODEL",
        "SEMANTIC_REVISION",
        "SEMANTIC_PACKAGES",
        "SEMANTIC_PREPROCESSING",
        "LEXICAL_PREPROCESSING",
        "Normalization",
        "LexicalBaseline",
        "Baseline",
        "Split",
        "Count",
        "Rate",
        "Digest",
        "Identifier",
        "StrictModel",
        "QualityCase",
        "CorpusInfo",
        "Metrics",
        "SweepPoint",
        "CategoryResult",
        "Embedding",
        "Run",
        "Summary",
        "ratio",
        "score",
        "select_threshold",
    ],
)
def test_existing_benchmark_names_reexport_the_same_contract(name: str) -> None:
    assert getattr(quality, name) is getattr(contracts, name)


def test_runner_retains_incidental_imports_without_export_restrictions() -> None:
    expected = {
        "Annotated": typing.Annotated,
        "Literal": typing.Literal,
        "Self": typing.Self,
        "BaseModel": pydantic.BaseModel,
        "ConfigDict": pydantic.ConfigDict,
        "Field": pydantic.Field,
        "model_validator": pydantic.model_validator,
        "math": math,
    }
    assert "__all__" not in vars(quality)
    for name, original in expected.items():
        assert getattr(quality, name) is original


@pytest.mark.parametrize(
    ("thresholds", "true_positives", "expected"),
    [
        ((0.75, 0.85, 0.9), (2, 1, 1), 0.75),
        ((0.5, 0.85, 0.92), (1, 1, 1), 0.92),
    ],
    ids=["maximize-tp-before-threshold", "highest-threshold-breaks-full-tie"],
)
def test_calibration_ties_prefer_tp_then_highest_threshold(
    thresholds: tuple[float, ...],
    true_positives: tuple[int, ...],
    expected: float,
) -> None:
    sweep = [
        contracts.SweepPoint(
            threshold=threshold,
            calibration=contracts.score(
                [True, True, False],
                [1.0, 1.0 if tp == 2 else 0.0, 0.0],
                threshold,
            ),
            held_out=contracts.score([True, False], [0.0, 1.0], threshold),
        )
        for threshold, tp in zip(thresholds, true_positives, strict=True)
    ]
    assert contracts.select_threshold(sweep) == expected


def test_contracts_import_and_validate_without_runner_or_external_io() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
import subprocess
import sys
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Initialize Pydantic's dependency-plugin discovery before guarding benchmark IO.
class DependencyBootstrap(BaseModel):
    pass

blocked = Mock(side_effect=AssertionError("Contracts attempted external IO"))
with patch.multiple(
    Path, read_bytes=blocked, read_text=blocked, write_bytes=blocked,
    write_text=blocked, glob=blocked,
), patch.object(subprocess, "Popen", blocked), patch.object(
    urllib.request, "urlopen", blocked,
):
    from benchmarks.reuse_quality import _contracts as contracts

    metrics = contracts.score([True, False], [1.0, 0.0], 0.92)
    point = contracts.SweepPoint(
        threshold=0.92, calibration=metrics, held_out=metrics,
    )
    assert contracts.select_threshold([point]) == 0.92
    assert contracts.Summary.model_json_schema()["title"] == "Summary"
    assert "benchmarks.reuse_quality.benchmark" not in sys.modules
    assert "semantix_cache" not in sys.modules
    assert "torch" not in sys.modules
    assert "sentence_transformers" not in sys.modules
    blocked.assert_not_called()
""",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
