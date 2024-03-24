import argparse
import logging


def add_logging(parser: argparse.ArgumentParser):
    logging_group = parser.add_mutually_exclusive_group()

    logging_group.add_argument(
        "--debug", help="Enable debug messages", action="store_true"
    )

    logging_levels = list()
    for level in range(logging.DEBUG, logging.CRITICAL + 1):
        name = logging.getLevelName(level)
        if isinstance(name, str) and not name.startswith("Level"):
            logging_levels.append(name)

    logging_group.add_argument("--log", help="Log level", choices=list(logging_levels))


def apply_logging(args: argparse.Namespace):

    if args.debug or args.log == "DEBUG":
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("pyjudge").setLevel(level=logging.DEBUG)
        logging.getLogger("problemtools").setLevel(logging.DEBUG)
    elif args.log:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("problemtools").setLevel(logging.WARNING)
        logging.getLogger("pyjudge").setLevel(level=args.log)
