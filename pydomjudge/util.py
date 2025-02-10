from typing import Any, Dict, Set, Optional, Iterable

import logging
import pathlib
import shutil
import subprocess
import platform

force_copy = platform.system() == "Windows"


def list_if_not_none(iterable: Optional[Iterable[Any]]):
    if iterable is None:
        return None
    return list(iterable)


def filter_none(data: Dict[str, Any], except_keys: Optional[Set[str]] = None):
    if except_keys is None:
        except_keys = {}
    return {
        key: value
        for key, value in data.items()
        if value is not None or key in except_keys
    }


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


def rasterize_pdf(
    source: pathlib.Path,
    destination: pathlib.Path,
    working_directory: pathlib.Path | None = None,
):
    from pypdf import PdfReader, PdfWriter

    if working_directory is None:
        working_directory = source.parent

    metadata = PdfReader(source).metadata

    rasterized_pdf = working_directory / f"{source.name}.rasterized.pdf"
    subprocess.run(
        [
            "convert",
            "-render",
            "-density",
            "150",
            source,
            rasterized_pdf,
        ],
        timeout=60,
        check=True,
        cwd=working_directory,
    )
    compressed_pdf = working_directory / f"{source.name}.compressed.pdf"
    subprocess.run(
        [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={compressed_pdf.absolute()}",
            rasterized_pdf,
        ],
        timeout=60,
        check=True,
        cwd=working_directory,
    )

    output_writer = PdfWriter(clone_from=compressed_pdf)
    output_writer.metadata = metadata
    with destination.open("wb") as f:
        output_writer.write(f)
