"""The command line tools, and helpers for scripts of your own.

``add_logging_arguments(parser)`` adds ``--debug`` and ``--log`` to an
argparse parser, ``configure_logging(args)`` applies them as the pyjudge
commands do, and ``load_database(path=None)`` returns the database of a db.yml
file or, without path, the one the pyjudge commands would use (pyjudge.yaml,
user configuration, db.yml in the working directory).
"""

from ._cli import (
    add_logging_options as add_logging_arguments,
    configure_logging as configure_logging,
    load_database_from as load_database,
)

__all__ = ["add_logging_arguments", "configure_logging", "load_database"]
