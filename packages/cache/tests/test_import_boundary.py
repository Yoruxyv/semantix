import ast
from pathlib import Path


def test_core_and_optional_provider_import_boundaries() -> None:
    root = Path(__file__).parents[1] / "src" / "semantix_cache"
    permitted = {
        "asyncio",
        "array",
        "collections",
        "contextlib",
        "dataclasses",
        "datetime",
        "enum",
        "hashlib",
        "inspect",
        "math",
        "numbers",
        "re",
        "sys",
        "threading",
        "time",
        "types",
        "typing",
        "numpy",
        "pydantic",
    }
    mysql_imports = {
        "stores/mysql.py": {"pathlib"},
        "stores/_backends/mysql/cleanup.py": {"os", "uuid"},
        "stores/_backends/mysql/config.py": {"ipaddress", "pathlib"},
        "stores/_backends/mysql/format.py": {"struct"},
        "stores/_backends/mysql/transport.py": {"socket", "ssl", "typing_extensions"},
        "stores/_backends/mysql/worker.py": {"concurrent", "os", "pymysql", "socket"},
    }
    for source in root.rglob("*.py"):
        allowed = permitted | (
            {"httpx", "json", "urllib"}
            if "adapters" in source.relative_to(root).parts
            else set()
        )
        if source.relative_to(root).as_posix() == "memory.py":
            allowed |= {"contextvars", "functools"}
        if "stores" in source.relative_to(root).parts:
            allowed |= {"asyncpg", "importlib", "__future__", "redis", "json", "urllib"}
        if source.relative_to(root).as_posix() in {
            "stores/sqlite.py",
            "stores/_backends/sqlite/format.py",
            "stores/_backends/sqlite/worker.py",
            "stores/_backends/sqlite/database.py",
        }:
            allowed |= {"concurrent", "os", "pathlib", "sqlite3", "stat", "struct"}
        allowed |= mysql_imports.get(source.relative_to(root).as_posix(), set())
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module is not None
                assert node.module.split(".")[0] in allowed


def test_conformance_kit_uses_only_public_store_types() -> None:
    root = Path(__file__).parents[1] / "examples" / "store_conformance"
    allowed = {
        "asyncio",
        "collections",
        "collections.abc",
        "contextlib",
        "dataclasses",
        "datetime",
        "hashlib",
        "typing",
        "pytest",
        "semantix_cache",
    }
    for source in root.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module in allowed
                assert all(not alias.name.startswith("_") for alias in node.names)
