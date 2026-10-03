"""Inspect archives without trusting package imports or server dependencies."""

import re
import tarfile
import zipfile
from email import message_from_bytes
from pathlib import Path


def main() -> None:
    wheels = list(Path("dist").glob("*.whl"))
    sdists = list(Path("dist").glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        assert all(
            name.startswith("semantix_cache/")
            or re.fullmatch(r"semantix_cache-[^/]+\.dist-info/.+", name)
            for name in names
        )
        assert all(".." not in Path(name).parts for name in names)
        assert "semantix_cache/py.typed" in names
        licenses = [
            name for name in names if name.endswith(".dist-info/licenses/LICENSE")
        ]
        assert len(licenses) == 1
        assert archive.read(licenses[0]) == Path("LICENSE").read_bytes()
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        assert len(metadata_names) == 1
        metadata = message_from_bytes(archive.read(metadata_names[0]))
        assert metadata["Name"] == "semantix-cache"
        assert metadata["Version"] == "0.1.0"
        assert set(metadata["Requires-Python"].split(",")) == {">=3.11", "<3.15"}
        requirements = metadata.get_all("Requires-Dist", [])
        runtime = [
            requirement for requirement in requirements if "extra ==" not in requirement
        ]
        assert {re.split(r"[<>=!~ ;]", requirement)[0] for requirement in runtime} == {
            "numpy",
            "pydantic",
        }
        extras = {"providers", "openai", "huggingface", "gemini", "ollama", "anthropic"}
        assert set(metadata.get_all("Provides-Extra", [])) == extras | {"dev"}
        for extra in extras:
            selected = [item for item in requirements if f'extra == "{extra}"' in item]
            assert len(selected) == 1
            assert selected[0].startswith("httpx")
            assert ">=0.28.1" in selected[0]
            assert "<0.29" in selected[0]
        for module in (
            "__init__",
            "_http",
            "_parsing",
            "openai",
            "huggingface",
            "gemini",
            "ollama",
            "anthropic",
        ):
            assert f"semantix_cache/adapters/{module}.py" in names
    with tarfile.open(sdists[0]) as archive:
        root = "semantix_cache-0.1.0"
        top_files = {
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "PKG-INFO",
            "setup.cfg",
            "MANIFEST.in",
        }
        dirs = {
            "src",
            "src/semantix_cache",
            "src/semantix_cache.egg-info",
            "tests",
            "examples",
        }
        for member in archive.getmembers():
            assert member.isfile() or member.isdir()
            assert ".." not in Path(member.name).parts
            if member.name == root:
                continue
            assert member.name.startswith(root + "/")
            relative = member.name.removeprefix(root + "/")
            assert (
                relative in top_files
                or relative.rstrip("/") in dirs
                or relative.startswith(
                    (
                        "src/semantix_cache/",
                        "src/semantix_cache.egg-info/",
                        "tests/",
                        "examples/",
                    )
                )
            ), relative
        assert f"{root}/src/semantix_cache/py.typed" in archive.getnames()
        assert f"{root}/examples/custom_integration.py" in archive.getnames()
    print("Embedded archive, namespace, license and dependency allowlists verified")


if __name__ == "__main__":
    main()
