import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def examples_dir() -> pathlib.Path:
    return ROOT / "examples"
