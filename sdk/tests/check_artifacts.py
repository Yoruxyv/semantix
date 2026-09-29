"""Validate release archives from ``sdk/dist`` without importing the backend."""

import re
import tarfile
import zipfile
from email import message_from_bytes
from pathlib import Path


def main() -> None:
    dist = Path("dist")
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    license_bytes = Path("LICENSE").read_bytes()

    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        assert all(
            not name.startswith("/") and ".." not in Path(name).parts for name in names
        )
        assert all(
            name.startswith("semantix_client/")
            or re.fullmatch(r"semantix_client-[^/]+\.dist-info/.+", name)
            for name in names
        )
        assert "semantix_client/py.typed" in names
        licenses = [
            name for name in names if name.endswith(".dist-info/licenses/LICENSE")
        ]
        assert len(licenses) == 1
        assert archive.read(licenses[0]) == license_bytes
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        assert len(metadata_names) == 1
        metadata = message_from_bytes(archive.read(metadata_names[0]))
        assert metadata["Name"] == "semantix-client"
        assert metadata["Version"] == "0.1.0"
        assert set(metadata["Requires-Python"].split(",")) == {">=3.11", "<3.15"}
        requirements = metadata.get_all("Requires-Dist", [])
        runtime = [
            requirement for requirement in requirements if "extra ==" not in requirement
        ]
        assert len(runtime) == 1
        assert re.match(r"^httpx(?:[ <>=!~]|$)", runtime[0])
        forbidden = {
            "fastapi",
            "asyncpg",
            "numpy",
            "pydantic",
            "sqlalchemy",
            "starlette",
            "psycopg",
        }
        assert not any(
            re.findall(r"^[A-Za-z0-9._-]+", requirement)[0].lower() in forbidden
            for requirement in requirements
        )

    with tarfile.open(sdists[0]) as archive:
        members = archive.getmembers()
        roots = {member.name.split("/", 1)[0] for member in members}
        assert len(roots) == 1
        root = roots.pop()
        assert root == "semantix_client-0.1.0"
        allowed_files = {
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "PKG-INFO",
            "setup.cfg",
            "MANIFEST.in",
        }
        allowed_dirs = (
            "src/semantix_client/",
            "src/semantix_client.egg-info/",
            "tests/",
        )
        for member in members:
            assert member.isfile() or member.isdir()
            if member.name == root:
                continue
            relative = member.name.removeprefix(root + "/")
            assert ".." not in Path(relative).parts
            assert (
                relative in allowed_files
                or relative.rstrip("/")
                in {
                    "src",
                    "src/semantix_client",
                    "src/semantix_client.egg-info",
                    "tests",
                }
                or relative.startswith(allowed_dirs)
            ), relative
        sdist_names = {member.name for member in members}
        assert f"{root}/src/semantix_client/py.typed" in sdist_names
        assert f"{root}/tests/conftest.py" in sdist_names
        license_file = archive.extractfile(f"{root}/LICENSE")
        assert license_file is not None and license_file.read() == license_bytes
    print("SDK wheel, sdist, license, and runtime dependency allowlists verified")


if __name__ == "__main__":
    main()
