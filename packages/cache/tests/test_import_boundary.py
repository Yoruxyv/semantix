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
    for source in root.rglob("*.py"):
        allowed = permitted | (
            {"httpx", "json", "urllib"}
            if "adapters" in source.relative_to(root).parts
            else set()
        )
        if "stores" in source.relative_to(root).parts:
            allowed |= {"asyncpg", "importlib", "__future__"}
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module is not None
                assert node.module.split(".")[0] in allowed
