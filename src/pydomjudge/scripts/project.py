"""pyjudge init and pyjudge config."""

import argparse
import pathlib

from pydomjudge.exc import display_path
from pydomjudge.scripts import _config


def run_init(args: argparse.Namespace) -> None:
    """Create pyjudge.yaml, db.yml and instance.json in the working directory."""
    from pydomjudge.scripts.default_instance import make_settings

    files = {
        _config.PROJECT_FILE: _config.PROJECT_TEMPLATE,
        "db.yml": _config.DATABASE_TEMPLATE,
        "instance.json": make_settings().model_dump_json(indent=2) + "\n",
    }
    for name, content in files.items():
        path = pathlib.Path(name)
        if path.exists() and not args.force:
            print(f"{name} exists, left alone (--force overwrites)")
            continue
        path.write_text(content)
        print(f"Wrote {name}")
    print(
        "Keep db.yml out of version control; edit it to match your DOMjudge database."
    )


def _shown_path(path: pathlib.Path) -> str:
    shown = display_path(path)
    home = str(pathlib.Path.home())
    return "~" + shown[len(home) :] if shown.startswith(home + "/") else shown


def _show(value) -> str:
    if isinstance(value, _config.DatabaseConfig):
        password = (
            f"password from ${value.password_env}" if value.password_env else "password"
        )
        return f"{value.user}@{value.host}:{value.port}/{value.database} ({password})"
    if isinstance(value, pathlib.Path):
        return _shown_path(value)
    return str(value)


DEFAULTS = {
    "database": "db.yml",
    "repository": "./repository, or . and its parents",
    "instance": "instance.json",
    "users": "none",
    "contest": "none",
}
OPTIONS = {"database": "db", "repository": "repository", "instance": "instance"}


def run_config(args: argparse.Namespace) -> None:
    """Show the effective settings, grouped by where they come from."""
    layers = _config.layers()
    print("Configuration files (the first one wins):")
    for layer in layers:
        print(f"  {_shown_path(layer.path)}")
    if not layers:
        print("  none (pyjudge init creates pyjudge.yaml)")

    by_source: dict[str, list[str]] = {}
    for name in _config.SETTINGS:
        option = OPTIONS.get(name)
        value, source = _config.lookup(
            name, getattr(args, option, None) if option else None
        )
        if value is None:
            heading, shown = "Defaults", DEFAULTS[name]
        elif source == "command line":
            heading, shown = "From the command line", _show(value)
        else:
            heading, shown = f"From {_shown_path(pathlib.Path(source))}", _show(value)
        by_source.setdefault(heading, []).append(f"  {name:11s} {shown}")
    for heading, lines in by_source.items():
        print(f"\n{heading}:")
        print("\n".join(lines))
