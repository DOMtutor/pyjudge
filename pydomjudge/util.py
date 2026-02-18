import typing
from typing import Callable
import gzip
import json
import logging
import pathlib
import platform
import shutil
import subprocess
import sys
from typing import Any, Iterable

force_copy = platform.system() == "Windows"
_wordlist_cache: list[str] | None = None


def default_wordlist() -> list[str]:
    global _wordlist_cache
    if _wordlist_cache is None:
        import importlib.resources

        _wordlist_cache = gzip.decompress(
            importlib.resources.files("pydomjudge")
            .joinpath("default_wordlist.gz")
            .read_bytes()
        ).splitlines()
    return _wordlist_cache


def list_if_not_none(iterable: Iterable[Any] | None):
    if iterable is None:
        return None
    return list(iterable)


def filter_none(data: dict[str, Any], except_keys: set[str] | None = None):
    if except_keys is None:
        except_keys = set()
    return {
        key: value
        for key, value in data.items()
        if value is not None or key in except_keys
    }


K = typing.TypeVar("K")
X = typing.TypeVar("X")
Y = typing.TypeVar("Y")


def get_map_if_present(d: dict[K, X], key: K, f: Callable[[X], Y]) -> Y | None:
    return f(d.get(key)) if key in d else None


def map_if_present(x: X | None, f: Callable[[X], Y]) -> Y | None:
    return f(x) if x is not None else None


def put_if_present(d: dict[K, Y], key: K, val: Y | None) -> dict[K, Y]:
    if val is not None:
        d[key] = val
    return d


def mkdir(path):
    path.mkdir(exist_ok=True, parents=True)
    return path


def link_or_copy(from_path: pathlib.Path, to_path: pathlib.Path, force=False):
    logging.debug("Linking %s to %s", from_path, to_path)

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
                logging.warning("Cannot create symlink, copying (%s)", e)
                link_failed = True
    if link_failed:
        if from_path.is_dir():
            shutil.copytree(from_path, to_path, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy(from_path, to_path)


def compile_latex(latex_file: pathlib.Path, shell_escape=False, timeout=None):
    invocation = ["latexmk", "-halt-on-error", "-pdflatex=lualatex"]
    if shell_escape:
        invocation.append("-shell-escape")
    invocation.append(latex_file.name)
    logging.debug("Compiling latex file %s", latex_file)
    process = subprocess.run(
        invocation,
        cwd=latex_file.parent,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        universal_newlines=True,
    )
    if process.returncode:
        logging.warning("Compilation of %s failed", latex_file.name)
        logging.debug(process.stdout)
        logging.debug(process.stderr)
        return None
    compiled_file = latex_file.parent / latex_file.with_suffix(".pdf")
    if not compiled_file.exists():
        logging.warning("Compilation succeeded but %s does not exist", compiled_file)
        return None
    return compiled_file


def check_output_defined_or_pipe(path: pathlib.Path | None):
    return path is not None or not sys.stdout.isatty()


def check_input_defined_or_pipe(path: pathlib.Path | None):
    return path is not None or not sys.stdin.isatty()


def read_json_from(source: pathlib.Path | None, read_from_terminal=False):
    if source is None:
        if not read_from_terminal and sys.stdin.isatty():
            raise ValueError("Refusing to read from terminal")
        return json.load(sys.stdin)
    if source.suffix in {".gz", ".gzip"}:
        with gzip.open(str(source), mode="rt") as f:
            return json.load(f)
    with source.open(mode="rt") as f:
        return json.load(f)


def write_json_to(data, destination: pathlib.Path | None, write_to_terminal=False):
    if destination is None:
        if not write_to_terminal and sys.stdout.isatty():
            raise ValueError("Refusing to write to terminal")
        json.dump(data, sys.stdout)
    else:
        if destination.suffix in {".gz", ".gzip"}:
            with gzip.open(str(destination), mode="wt") as f:
                json.dump(data, f)
        else:
            with destination.open(mode="wt") as f:
                json.dump(data, f)


def rasterize_pdf(
    source: pathlib.Path,
    destination: pathlib.Path,
    working_directory: pathlib.Path | None = None,
    super_sampling: float = 4,
):
    from pypdf import PdfReader, PdfWriter

    if working_directory is None:
        working_directory = source.parent

    metadata = PdfReader(source).metadata

    compressed_pdf = working_directory / f"{source.name}.rasterized.pdf"
    subprocess.run(
        [
            "gs",
            "-sDEVICE=pdfimage24",
            "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-r{int(300 * super_sampling)}",
            f"-dDownScaleFactor={super_sampling}",
            f"-sOutputFile={compressed_pdf.absolute()}",
            source,
        ],
        timeout=60,
        check=True,
        cwd=working_directory,
    )

    output_writer = PdfWriter(clone_from=compressed_pdf)
    output_writer.metadata = metadata
    with destination.open("wb") as f:
        output_writer.write(f)
