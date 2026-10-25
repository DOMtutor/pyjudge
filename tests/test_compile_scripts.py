"""The compile scripts in repository/compiler/, run the way DOMjudge's
judge/compile.sh runs them: the executable's files in compile-script/ (after
its build script), the sources in compile/ as working directory, then
``compile-script/run program <memory limit> <sources>`` with an almost empty
environment. Languages whose compiler is not installed are skipped.
"""

import importlib.resources
import os
import pathlib
import re
import shutil
import subprocess

import pytest

COMPILER = (
    pathlib.Path(str(importlib.resources.files("pydomjudge.repository"))) / "compiler"
)

# language: (tools needed, file name, program printing "hello", syntax error or None)
PROGRAMS = {
    "c": (
        ["gcc"],
        "hello.c",
        '#include <stdio.h>\n#ifndef DOMJUDGE\n#error "no -DDOMJUDGE"\n#endif\n'
        'int main(void) { puts("hello"); return 0; }\n',
        "int main(void) { return }\n",
    ),
    "cpp": (
        ["g++"],
        "hello.cpp",
        "#include <iostream>\n#ifndef DOMJUDGE\n#error no -DDOMJUDGE\n#endif\n"
        'int main() { std::cout << "hello" << std::endl; }\n',
        "int main() { return }\n",
    ),
    "java": (
        ["javac", "java"],
        "Greeting.java",
        "public class Greeting { public static void main(String[] args) {"
        ' System.out.println(System.getProperty("DOMJUDGE") != null ? "hello" : "no"); } }\n',
        "public class Greeting { void f( }\n",
    ),
    "python": (
        ["pypy3"],
        "hello.py",
        # asserts are disabled (pypy3 -O)
        'assert False, "asserts are on"\nprint("hello")\n',
        "print(\n",
    ),
    "javascript": (
        ["nodejs"],
        "hello.js",
        'console.log("hello");\n',
        "console.log(;\n",
    ),
    "rust": (
        ["rustc"],
        "hello.rs",
        '#[cfg(DOMJUDGE)]\nfn main() { println!("hello"); }\n',
        "fn main() {\n",
    ),
    "haskell": (
        ["ghc"],
        "hello.hs",
        '{-# LANGUAGE CPP #-}\n#ifdef DOMJUDGE\nmain = putStrLn "hello"\n#endif\n',
        "main = \n",
    ),
    "pascal": (
        ["fpc"],
        "hello.pas",
        "program hello;\nbegin\n{$IFDEF DOMJUDGE}writeln('hello');{$ENDIF}\nend.\n",
        "program hello;\nbegin\n",
    ),
    "julia": (["julia"], "hello.jl", 'println("hello")\n', None),
}


def _skip_without(tools: list[str]) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"not installed: {', '.join(missing)}")
    if "rustc" in tools:
        version = subprocess.run(
            ["rustc", "--version"], capture_output=True, text=True
        ).stdout
        match = re.search(r"(\d+)\.(\d+)", version)
        if match and (int(match[1]), int(match[2])) < (1, 85):
            pytest.skip(f"edition 2024 needs rustc >= 1.85, found {version.strip()}")


def _compile(tmp_path: pathlib.Path, language: str, name: str, source: str):
    script = tmp_path / "compile-script"
    shutil.copytree(COMPILER / language, script)
    environment = {"PATH": os.environ["PATH"]}
    build = subprocess.run(
        [str(script / "build")], cwd=script, env=environment, capture_output=True
    )
    assert build.returncode == 0, build.stderr
    work = tmp_path / "compile"
    work.mkdir()
    (work / name).write_text(source)
    result = subprocess.run(
        [str(script / "run"), "program", "2097152", name],
        cwd=work,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return work, result


@pytest.mark.parametrize("language", sorted(PROGRAMS))
def test_compile_and_run(tmp_path: pathlib.Path, language: str):
    tools, name, source, _ = PROGRAMS[language]
    _skip_without(tools)
    work, result = _compile(tmp_path, language, name, source)
    assert result.returncode == 0, result.stdout + result.stderr
    run = subprocess.run(
        [str(work / "program")],
        cwd=work,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert (run.returncode, run.stdout.strip()) == (0, "hello"), run.stderr
    if language in {"java", "python", "javascript", "julia"}:
        # compile.sh records the entry point from this line
        assert re.search(r"[Dd]etected entry_point: ", result.stdout), result.stdout


@pytest.mark.parametrize(
    "language", sorted(name for name, program in PROGRAMS.items() if program[3])
)
def test_syntax_error_fails_to_compile(tmp_path: pathlib.Path, language: str):
    tools, name, _, broken = PROGRAMS[language]
    _skip_without(tools)
    assert broken is not None
    _, result = _compile(tmp_path, language, name, broken)
    assert result.returncode != 0, result.stdout + result.stderr


def test_every_language_is_tested():
    assert {path.name for path in COMPILER.iterdir() if path.is_dir()} == set(PROGRAMS)
