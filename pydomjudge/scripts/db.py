import argparse
import pathlib

import yaml

from pydomjudge.database import Database


def make_argparse(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--db", type=pathlib.Path, default="db.yml", help="Path to database config"
    )


def from_args(args: argparse.Namespace) -> Database:
    config = args.db
    if isinstance(config, pathlib.Path):
        with config.open(mode="rt") as f:
            config = yaml.safe_load(f)
    return Database(**config)
