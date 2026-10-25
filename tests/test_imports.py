"""Every module must at least import; this catches broken relative imports early."""

import importlib
import pkgutil

import pytest

import pydomjudge


def _modules():
    for module in pkgutil.walk_packages(pydomjudge.__path__, "pydomjudge."):
        yield module.name


@pytest.mark.parametrize("name", sorted(_modules()))
def test_import(name: str):
    importlib.import_module(name)
