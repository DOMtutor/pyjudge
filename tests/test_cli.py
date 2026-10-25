"""The dt_* tools: shared options and the pure parts of the scripts."""

import argparse
import logging
import pathlib
import tarfile

import jinja2
import pytest

from pydomjudge.database import ContestDataExport
from pydomjudge.scripts import _cli
from pydomjudge.scripts.anonymize import anonymize
from pydomjudge.scripts.generate_seed import render_content
from pydomjudge.scripts.get import content_writer


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings}


def test_make_parser_options():
    assert _options(_cli.make_parser()) == {"-h", "--help", "--debug", "--log"}
    full = _cli.make_parser(
        database=True, repository=True, instance=True, problem_filters=True
    )
    assert _options(full) >= {
        "--db",
        "--repository",
        "--instance",
        "--name",
        "--keyword",
        "--exclude",
        "--contest",
    }
    args = full.parse_args([])
    assert args.db == pathlib.Path("db.yml")
    assert args.instance == pathlib.Path("instance.json")
    assert args.name == [] and args.contest == []


@pytest.fixture
def restore_log_levels():
    loggers = [logging.getLogger(name) for name in ("pydomjudge", "problemtools")]
    levels = [logger.level for logger in loggers]
    yield
    for logger, level in zip(loggers, levels, strict=True):
        logger.setLevel(level)


@pytest.mark.parametrize(
    ("argv", "pydomjudge", "problemtools"),
    [
        ([], logging.INFO, logging.WARNING),
        (["--log", "WARNING"], logging.WARNING, logging.WARNING),
        (["--debug"], logging.DEBUG, logging.DEBUG),
    ],
)
def test_configure_logging(argv, pydomjudge, problemtools, restore_log_levels):
    _cli.configure_logging(_cli.make_parser().parse_args(argv))
    assert logging.getLogger("pydomjudge").level == pydomjudge
    assert logging.getLogger("problemtools").level == problemtools


def test_find_problems_filters(examples_dir: pathlib.Path):
    parser = _cli.make_parser(repository=True, problem_filters=True)
    repository_args = ["--repository", str(examples_dir / "repository")]
    args = parser.parse_args([*repository_args, "--keyword", "easy"])
    repository = _cli.load_repository(args)
    keys = {problem.key for problem in _cli.find_problems(repository, args)}
    assert keys == {"helloworld", "dfamin"}
    args = parser.parse_args(
        [*repository_args, "--contest", str(examples_dir / "contest.json")]
        + ["--exclude", "hello"]
    )
    keys = [problem.key for problem in _cli.find_problems(repository, args)]
    assert keys == ["pastryperfection", "dfamin"]


def test_seed_rendering_is_deterministic():
    template = jinja2.Environment().from_string("{{ seed }} {{ random.randint(1, 9) }}")
    first = render_content(3, "small_{n:02d}.seed", template)
    assert first == render_content(3, "small_{n:02d}.seed", template)
    assert first[0] == "small_03.seed"
    assert first != render_content(4, "small_{n:02d}.seed", template)


def test_tar_writer_accepts_bytes(tmp_path: pathlib.Path):
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"%PDF")
    destination = tmp_path / "out.tar"
    with content_writer(destination) as add_content:
        add_content(b"1 2\n", "p/1.in")
        add_content(source, "p.pdf")
    with tarfile.open(destination) as tar:
        member = tar.extractfile("p/1.in")
        assert member is not None and member.read() == b"1 2\n"
        assert set(tar.getnames()) == {"p/1.in", "p.pdf"}


def test_anonymize(contest_export: ContestDataExport):
    result = anonymize(contest_export)
    assert result == anonymize(contest_export)  # deterministic

    assert not set(result.users) & set(contest_export.users)
    assert not set(result.teams) & set(contest_export.teams)
    (team,) = result.teams.values()
    assert set(team.member_login_names) == set(result.users)
    assert team.display_name != "Team T"

    start, new_start = contest_export.description.start, result.description.start
    assert start is not None and new_start is not None
    delta = new_start - start
    assert delta > 0
    for old, new in zip(contest_export.submissions, result.submissions, strict=True):
        assert new.team_name == team.name
        assert new.submission_time == old.submission_time + delta
    assert result.clarifications[0].request_time == pytest.approx(2.0 + delta)

    dumped = result.model_dump_json()
    assert "u@x" not in dumped and "Team T" not in dumped
    assert ContestDataExport.model_validate_json(dumped) == result
