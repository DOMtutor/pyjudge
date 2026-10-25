import functools
import gzip
import logging
import pathlib
import platform
import shutil
import sys
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Annotated, TypeVar

from pydantic import AfterValidator

log = logging.getLogger(__name__)

force_copy = platform.system() == "Windows"


@functools.cache
def default_wordlist() -> list[str]:
    import importlib.resources

    return (
        gzip.decompress(
            importlib.resources.files("pydomjudge")
            .joinpath("default_wordlist.gz")
            .read_bytes()
        )
        .decode()
        .splitlines()
    )


def mkdir(path: pathlib.Path) -> pathlib.Path:
    path.mkdir(exist_ok=True, parents=True)
    return path


def link_or_copy(from_path: pathlib.Path, to_path: pathlib.Path, force=False):
    log.debug("Linking %s to %s", from_path, to_path)

    from_path = from_path.resolve()
    if not from_path.exists():
        raise ValueError(f"Path does not exist {from_path}")
    if to_path.is_symlink():
        if not force_copy and to_path.resolve().absolute() == from_path.absolute():
            return
        to_path.unlink()
    elif to_path.exists():
        if not force:
            return

    link_failed = False
    if not to_path.exists():
        if force_copy:
            link_failed = True
        else:
            try:
                if not to_path.parent.exists():
                    to_path.parent.mkdir(parents=True, exist_ok=True)
                to_path.symlink_to(
                    from_path.absolute(), target_is_directory=from_path.is_dir()
                )
            except OSError as e:
                log.warning("Cannot create symlink, copying (%s)", e)
                link_failed = True
    if link_failed:
        if from_path.is_dir():
            shutil.copytree(from_path, to_path, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy(from_path, to_path)


def read_str_from(source: pathlib.Path | None, read_from_terminal=False) -> str:
    if source is None:
        if not read_from_terminal and sys.stdin.isatty():
            raise ValueError("Refusing to read from terminal")
        return sys.stdin.read()
    if source.suffix in {".gz", ".gzip"}:
        with gzip.open(str(source), mode="rt") as f:
            return f.read()
    return source.read_text()


def write_str_to(data: str, destination: pathlib.Path | None, write_to_terminal=False):
    if destination is None:
        if not write_to_terminal and sys.stdout.isatty():
            raise ValueError("Refusing to write to terminal")
        sys.stdout.write(data)
    else:
        if destination.suffix in {".gz", ".gzip"}:
            with gzip.open(str(destination), mode="wt") as f:
                f.write(data)
        else:
            with destination.open(mode="wt") as f:
                f.write(data)


@contextmanager
def open_file_or_stdout(filename: str | None, mode="w", encoding="utf-8"):
    if filename is None or filename == "-":
        yield sys.stdout
    else:
        # Standard context manager handles opening and closing automatically
        with open(filename, mode, encoding=encoding) as f:
            yield f


AsTuple = AfterValidator(tuple)

T = TypeVar("T")
FrozenSequence = Annotated[Sequence[T], AsTuple]
