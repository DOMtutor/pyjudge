"""pyjudge check: the consistency report."""

import argparse
import dataclasses
import json
import sys

from pydomjudge.database import ERROR, WARNING, check_consistency
from pydomjudge.scripts import _cli


def run(args: argparse.Namespace) -> None:
    findings = check_consistency(_cli.load_database(args))
    if args.json:
        print(
            json.dumps([dataclasses.asdict(finding) for finding in findings], indent=2)
        )
    else:
        for finding in findings:
            print(f"{finding.severity}: {finding.message} [{finding.check}]")
        counts = {
            severity: sum(finding.severity == severity for finding in findings)
            for severity in ("error", "warning", "info")
        }
        print(
            ", ".join(
                f"{count} {severity}{'' if count == 1 else 's'}"
                for severity, count in counts.items()
            )
            if findings
            else "No findings"
        )
    if any(finding.severity in (ERROR, WARNING) for finding in findings):
        sys.exit(1)
