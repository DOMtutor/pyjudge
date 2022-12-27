import logging
import pathlib
import shutil
import subprocess
import platform

from pyjudge.repository.kattis import RepositoryProblem

force_copy = platform.system() == "Windows"


def mkdir(path):
    path.mkdir(exist_ok=True, parents=True)
    return path


def link_or_copy_problem(
    problem: RepositoryProblem, problem_build_directory: pathlib.Path, force=False
):
    problem_paths = ["problem_statement", "data/sample"]

    repository_path = problem.directory
    for sub_path in problem_paths:
        link_or_copy(
            repository_path / sub_path,
            problem_build_directory / problem.key / sub_path,
            force,
        )


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


def compile_latex(latex_file: pathlib.Path):
    process = subprocess.Popen(
        ["latexmk", "-halt-on-error", "--lualatex", latex_file.name],
        cwd=latex_file.parent,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    logging.debug("Compiling latex file %s", latex_file)
    output, error = process.communicate()
    if process.returncode:
        logging.warning("Compilation of %s failed", latex_file.name)
        logging.debug(output)
        logging.debug(error)
        return None
    compiled_file = latex_file.parent / latex_file.with_suffix(".pdf")
    if not compiled_file.exists():
        logging.warning("Compilation succeeded but %s does not exist", compiled_file)
        return None
    return compiled_file
