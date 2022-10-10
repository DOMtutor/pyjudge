# NOTE It seems to be important to import mysql.connector before many other imports, since these may load the wrong
# version of libcrypt, see https://bugs.mysql.com/bug.php?id=97220
from mysql.connector.cursor import MySQLCursor

import argparse
import dataclasses
import datetime
import itertools
import json
import logging
import pathlib
import re
import sys
from typing import List, Tuple, Collection, Optional, Dict, Set

import pyjudge.action.update as update
from problemtools.verifyproblem import VerifyError
from pyjudge.model import Contest, Verdict, Problem, ProblemSubmission, Team, User, Affiliation
from pyjudge.model.settings import JudgeInstance
from pyjudge.repository.kattis import Repository, RepositoryProblem, JurySubmission
from pyjudge.scripts.db import Database


@dataclasses.dataclass
class PyjudgeConfig(object):
    repository: Repository
    judge: JudgeInstance
    database: Database


def _update_problem_submissions(cursor: MySQLCursor,
                                problem: RepositoryProblem, config: Repository,
                                contest_ids: Optional[Collection[int]] = None):
    problem_submissions: Collection[JurySubmission] = problem.submissions
    submissions: List[Tuple[Team, ProblemSubmission]] = []
    for submission in sorted(problem_submissions, key=lambda s: s.path):
        language = submission.language
        if language is None:
            logging.warning("Did not find a language for submission %s", submission)
            continue

        submission_expected_results: Tuple[Verdict] = tuple(submission.expected_results)
        if set(submission_expected_results) == {Verdict.CORRECT}:
            submissions.append(((config.get_solution_team_of_language(language)), submission))

        author = submission.author
        if author is None:
            logging.debug("No author found for submission %s", submission)
        submissions.append((config.get_team_of_author(author), submission))

    teams = set(team for team, _ in submissions)
    affiliations = set(team.affiliation for team in teams if team.affiliation is not None)
    users: Set[User] = set()
    for team in teams:
        users.update(set(member for member in team.members))

    affiliation_ids = update.create_or_update_affiliations(cursor, affiliations)
    user_ids = update.create_or_update_users(cursor, users)
    team_ids = update.create_or_update_teams(cursor, teams, affiliation_ids, user_ids)

    update.create_problem_submissions(cursor, problem, submissions, team_ids, contest_ids)


def upload_contest(config: PyjudgeConfig, contest: Contest,
                   force=False, update_problems=True, verify_problems=True, update_submissions=True,
                   update_test_cases=True):
    if not force and contest.is_running(datetime.datetime.now().astimezone()):
        raise ValueError("Contest %s is running")

    if update_problems:
        if verify_problems:
            logging.info("Checking problems")
            try:
                for contest_problem in contest.problems:
                    contest_problem.problem.check()
            except VerifyError as e:
                logging.error("Problem verification failed", exc_info=e)
                return
        else:
            logging.info("Skipping problem verification")

    with config.database as connection:
        with connection.transaction_cursor(isolation_level='SERIALIZABLE', prepared_cursor=True) as cursor:
            contest_id = update.create_or_update_contest(cursor, contest, force=force)

        if update_problems:
            problem_ids: Dict[Problem, int] = {}
            for contest_problem in contest.problems:
                with connection.transaction_cursor(isolation_level='SERIALIZABLE', prepared_cursor=True) as cursor:
                    problem_ids[contest_problem.problem] = \
                        update.create_or_update_problem_data(cursor, config.judge, contest_problem.problem)
                    if update_test_cases:
                        update.create_or_update_problem_testcases(cursor, contest_problem.problem)

            with connection.transaction_cursor(isolation_level='SERIALIZABLE', prepared_cursor=True) as cursor:
                update.create_or_update_contest_problems(cursor, contest, contest_id, problem_ids)

        if update_submissions:
            for contest_problem in contest.problems:
                with connection.transaction_cursor(isolation_level='SERIALIZABLE', prepared_cursor=True) as cursor:
                    assert isinstance(contest_problem.problem, RepositoryProblem)
                    _update_problem_submissions(cursor, contest_problem.problem, config.repository, [contest_id])

    logging.info("Updated contest %s", contest)


def upload_problems(config: PyjudgeConfig, problems: List[RepositoryProblem],
                    update_submissions: bool = True, verify_problems: bool = False):
    if update_submissions:
        if verify_problems:
            logging.info("Checking problems")
            try:
                for problem in problems:
                    problem.check()
            except VerifyError as e:
                logging.error("Problem verification failed", exc_info=e)
                return
            logging.info("All ok, uploading")
        else:
            logging.info("Skipping verification")

    with config.database as connection:
        for problem in problems:
            with connection.transaction_cursor(prepared_cursor=True) as cursor:
                update.create_or_update_problem_data(cursor, config.judge, problem)
                update.create_or_update_problem_testcases(cursor, problem)
                if update_submissions:
                    _update_problem_submissions(cursor, problem, config.repository, None)


@dataclasses.dataclass
class UsersDescription(object):
    users: List[User]
    affiliations: List[Affiliation]
    teams: List[Team]

    @staticmethod
    def parse(data):
        users: List[User] = [User.parse(user) for user in data["users"]]
        user_by_login: Dict[str, User] = {user.login_name: user for user in users}
        affiliations: List[Affiliation] = [Affiliation.parse(affiliation) for affiliation in (data["affiliations"])]
        affiliation_by_name: Dict[str, Affiliation] = {affiliation.short_name: affiliation for affiliation in
                                                       affiliations}
        teams = [Team.parse(team, user_by_login, affiliation_by_name) for team in data["teams"]]
        return UsersDescription(users, affiliations, teams)

    def serialize(self):
        return {"users": [user.serialize()
                          for user in sorted(self.users, key=lambda u: u.login_name)],
                "affiliations": [affiliation.serialize()
                                 for affiliation in sorted(self.affiliations, key=lambda a: a.short_name)],
                "teams": [team.serialize()
                          for team in sorted(self.teams, key=lambda t: t.name)]}


def upload_users(config: PyjudgeConfig, description: UsersDescription, disable_unknown=False):
    with config.database as connection:
        with connection.transaction_cursor(isolation_level='SERIALIZABLE', prepared_cursor=True) as cursor:
            affiliation_ids = update.create_or_update_affiliations(cursor, description.affiliations)
            user_ids = update.create_or_update_users(cursor, description.users)
            update.create_or_update_teams(cursor, description.teams, affiliation_ids, user_ids)
            if disable_unknown:
                valid_users = set(itertools.chain([user.login_name for user in description.users],
                                                  config.judge.user_whitelist))
                update.disable_unknown_users(cursor, valid_users)


def update_settings(config: PyjudgeConfig):
    with config.database as connection:
        with connection.transaction_cursor(prepared_cursor=True) as cursor:
            update.update_settings(cursor, config.judge.settings)
            update.update_categories(cursor, lazy=False)
            update.set_languages(cursor, config.repository.languages)  # TODO Awkward


def command_problem(config: PyjudgeConfig, args):
    problems: List[RepositoryProblem] = []
    if args.regex:
        patterns = [re.compile(pattern) for pattern in args.regex]
        for problem in config.repository.problems.load_all_problems():
            if any(pattern.match(problem.repository_key) for pattern in patterns):
                problems.append(problem)
    problems.extend(config.repository.problems.load_problem(name) for name in args.name)
    for contest_json in args.contest:
        contest_json: pathlib.Path
        with contest_json.open(mode="rt") as f:
            data = json.load(f)
        contest = Contest.parse(data, config.repository.problems)
        problems.extend(contest_problem.problem for contest_problem in contest.problems)

    if not problems:
        sys.exit(f"No problems found")
    logging.info("Found problems %s", ' '.join(problem.name for problem in problems))

    upload_problems(config, problems,
                    verify_problems=args.verify,
                    update_submissions=args.update_submissions)


def command_contest(config: PyjudgeConfig, args):
    with args.contest.open(mode="rt") as file:
        contest_upload_data = json.load(file)
    upload_contest(config, Contest.parse(contest_upload_data, config.repository.problems),
                   force=args.force,
                   update_problems=args.update_problems,
                   verify_problems=args.verify,
                   update_submissions=args.update_submissions,
                   update_test_cases=args.update_testcases)


def command_users(config: PyjudgeConfig, args):
    with args.users.open("rt") as file:
        user_data = json.load(file)
    upload_users(config, UsersDescription.parse(user_data), disable_unknown=args.disable)


def command_settings(config: PyjudgeConfig, _):
    update_settings(config)


def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=pathlib.Path, required=True, help="Path to database config")
    parser.add_argument("--repository", "-r", type=pathlib.Path, default=pathlib.Path.cwd(), help="Path to repository")
    parser.add_argument("--instance", type=pathlib.Path, required=True, help="Path to instance specification")
    subparsers = parser.add_subparsers(help="Help for commands")
    problem_parser = subparsers.add_parser("problem", help="Upload problems")
    problem_parser.add_argument("--regex", nargs='*', help="Regexes to match problem name", default=[])
    problem_parser.add_argument("--name", nargs='*', help="Problem names", default=[])
    problem_parser.add_argument("--contest", nargs='*', type=pathlib.Path,
                                help="Update problems of contest description", default=[])
    problem_parser.add_argument("--skip-verify", action='store_false', dest='verify', help="Skip checking of problems",
                                default=False)
    problem_parser.add_argument("--skip-submissions", action='store_false', dest='update_submissions', default=True,
                                help="Skip uploading of sample submissions")
    problem_parser.add_argument("--skip-testcases", action='store_false', dest='update_testcases', default=True,
                                help="Skip updating of testcases")
    problem_parser.set_defaults(func=command_problem)

    contest_parser = subparsers.add_parser("contest", help="Upload a contest")
    contest_parser.add_argument("contest", type=pathlib.Path, help="Path to contest specification")
    contest_parser.add_argument("--force", action='store_true', help="Force update even if contest is running")
    contest_parser.add_argument("--skip-verify", action='store_false', dest='verify', default=True,
                                help="Skip checking of problems")
    contest_parser.add_argument("--skip-submissions", action='store_false', dest='update_submissions', default=True,
                                help="Skip uploading of sample submissions")
    contest_parser.add_argument("--skip-problems", action='store_false', dest='update_problems', default=True,
                                help="Skip updating the problems")
    contest_parser.add_argument("--skip-testcases", action='store_false', dest='update_testcases', default=True,
                                help="Skip updating of testcases")
    contest_parser.set_defaults(func=command_contest)

    users_parser = subparsers.add_parser("users", help="Upload user file")
    users_parser.add_argument("users", type=pathlib.Path, help="Path to user specification")
    users_parser.add_argument("--disable", action='store_true', help="Disable unknown users")
    users_parser.set_defaults(func=command_users)

    settings_parser = subparsers.add_parser("settings", help="Upload settings")
    settings_parser.set_defaults(func=command_settings)

    arguments = parser.parse_args()

    with arguments.instance.open(mode="rt") as f:
        instance_data = json.load(f)
    instance = JudgeInstance.parse_instance(instance_data)

    arguments.func(PyjudgeConfig(repository=Repository(arguments.repository),
                                 judge=instance, database=Database(arguments.db)), arguments)
