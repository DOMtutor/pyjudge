"""pydomjudge-course as a package: it imports and keeps to pydomjudge's public API."""

import ast
import pathlib

import pydomjudge_course

SOURCES = pathlib.Path(pydomjudge_course.__file__).parent


def test_imports():
    assert pydomjudge_course.__doc__


def test_uses_only_public_pydomjudge_modules():
    private = []
    for path in sorted(SOURCES.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [
                    f"{node.module}.{alias.name}" for alias in node.names
                ]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                parts = name.split(".")
                if parts[0] == "pydomjudge" and any(p.startswith("_") for p in parts):
                    private.append(f"{path.name}:{node.lineno}: {name}")
    assert not private, "\n".join(private)
