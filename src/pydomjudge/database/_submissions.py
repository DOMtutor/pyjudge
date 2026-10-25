"""Jury submissions and their judgings.

Part of the writer, which works by key; see the package docstring.
"""

import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from pydomjudge.model import (
    Problem,
    ProblemSubmission,
    Team,
    Verdict,
)

from ._db import DBCursor as Cursor, list_param

log = logging.getLogger(__name__)


def clear_invalid_submissions(cursor: Cursor) -> None:
    cursor.execute(
        "DELETE FROM submission_file "
        "WHERE LENGTH(submission_file.sourcecode) = 0 OR LOCATE('\\0', submission_file.sourcecode) > 0"
    )
    if cursor.rowcount:
        log.warning("Dropped %d invalid submission files", cursor.rowcount)

    cursor.execute(
        "DELETE FROM submission "
        "WHERE NOT EXISTS(SELECT * FROM submission_file WHERE submitid = submission.submitid)"
    )
    if cursor.rowcount:
        log.warning("Dropped %d invalid submissions without files", cursor.rowcount)

    cursor.execute(
        "DELETE FROM submission "
        "WHERE NOT EXISTS(SELECT * FROM judging WHERE submission.submitid = judging.submitid)"
    )
    if cursor.rowcount:
        log.warning("Dropped %d submissions without judging", cursor.rowcount)


def jury_submission_external_id() -> str:
    return f"pydomjudge-{uuid.uuid4().hex}"


def _problem_contests(
    cursor: Cursor, problem_id: int, contest_ids: Collection[int] | None
) -> dict[int, Any]:
    """Start time by contest id: the given contests, or all with the problem."""
    contest_start = {}
    if contest_ids is None:
        cursor.execute(
            "SELECT c.cid, c.starttime FROM contest c JOIN contestproblem cp on c.cid = cp.cid "
            "WHERE cp.probid = %s",
            (problem_id,),
        )
        for contest_id, start_time in cursor:
            contest_start[contest_id] = start_time
        if not contest_start:
            log.info("Problem not used in any contests")
    elif not contest_ids:
        log.info("No contests specified")
    else:
        contest_ids = set(contest_ids)
        cursor.execute(
            f"SELECT cid, starttime FROM contest WHERE cid IN {list_param(contest_ids)}",
            tuple(contest_ids),
        )
        for contest_id, start_time in cursor:
            contest_start[contest_id] = start_time
        if len(contest_start) != len(contest_ids):
            raise KeyError("Not all given contests exist")
    return contest_start


@dataclass
class _ExistingSubmissions:
    """The jury submissions in the database for the teams of one upload."""

    # id -> (original submission id, team id, contest id, language id, expected)
    submissions: dict[int, tuple[int | None, int, int, str, tuple[Verdict, ...]]]
    # id -> file name -> MD5 of the source
    files: dict[int, dict[str, str]]
    # original submission id -> its successor
    successor: dict[int, int]
    invalid_ids: set[int]
    invalid_groups: set[tuple[int, int]]


def _existing_submissions(
    cursor: Cursor,
    problem_id: int,
    team_ids: Collection[int],
    contest_ids: Collection[int],
) -> _ExistingSubmissions:
    cursor.execute(
        f"SELECT "
        f"  submitid, origsubmitid, teamid, cid, expected_results, langid "
        f"FROM submission s "
        f"WHERE "
        f"  probid = %s AND "
        f"  teamid IN {list_param(team_ids)} AND "
        f"  cid IN {list_param(contest_ids)}",
        (problem_id,) + tuple(team_ids) + tuple(contest_ids),
    )
    existing = _ExistingSubmissions({}, defaultdict(dict), {}, set(), set())
    for (
        submission_id,
        original_submission_id,
        team_id,
        contest_id,
        expected_results_string,
        language_id,
    ) in cursor:
        try:
            expected_results: tuple[Verdict, ...] = tuple(
                Verdict.parse(str(verdict))
                for verdict in (
                    json.loads(expected_results_string)
                    if expected_results_string
                    else []
                )
            )
        except ValueError:
            log.warning(
                "Submission %s has invalid results %s",
                submission_id,
                expected_results_string,
            )
            existing.invalid_groups.add((contest_id, team_id))
            existing.invalid_ids.add(submission_id)
            continue
        if submission_id in existing.submissions:
            raise ValueError(f"Multiple submissions for id {submission_id}")

        if original_submission_id is not None:
            if original_submission_id in existing.successor:
                # TODO I think this is not allowed by domjudge, so raise an exception
                raise ValueError(
                    f"Multiple successors for submission {original_submission_id}: "
                    f"{submission_id} and {existing.successor[original_submission_id]}"
                )
            existing.successor[original_submission_id] = submission_id

        assert (
            (isinstance(original_submission_id, int) or original_submission_id is None)
            and isinstance(team_id, int)
            and isinstance(contest_id, int)
            and isinstance(language_id, str)
        ), (
            f"Expected identifiers, got {original_submission_id}, {team_id}, {contest_id}, {language_id}"
        )
        existing.submissions[submission_id] = (
            original_submission_id,
            team_id,
            contest_id,
            language_id,
            expected_results,
        )

    if existing.submissions:
        cursor.execute(
            f"SELECT submitid, submitfileid, filename, MD5(sourcecode) as source_md5 "
            f"FROM submission_file sf WHERE "
            f"submitid IN {list_param(existing.submissions)}",
            tuple(existing.submissions.keys()),
        )
        for submission_id, _file_id, file_name, file_md5 in cursor:
            files = existing.files[submission_id]
            if file_name in files:
                raise ValueError(f"Duplicate file names for submission {submission_id}")
            files[file_name] = file_md5
    return existing


class _JudgingTasks:
    """Creates the judging of a new submission, like DOMjudge does when a team
    submits (webapp/src/Entity/{Judging, JudgeTask, JudgingRun, QueueTask}.php).

    The configuration, limits, scripts and test cases are the same for all
    submissions of a problem, so they are read once, at the first submission.
    """

    def __init__(self, cursor: Cursor, problem_id: int):
        cursor.execute(
            "SELECT name, value FROM configuration WHERE name IN "
            "('script_timelimit', 'script_memory_limit', 'script_filesize_limit', "
            "'memory_limit', 'output_limit', 'process_limit')"
        )
        self.config = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT p.timelimit, p.memlimit, p.outputlimit, p.special_compare_args, "
            "p.special_compare, p.multipass_limit "
            "FROM problem p WHERE p.probid = %s",
            (problem_id,),
        )
        (
            self.time_limit,
            mem_limit,
            output_limit,
            compare_args,
            special_compare,
            self.multipass_limit,
        ) = cursor.fetchone()  # ty:ignore[not-iterable]
        # Some default values if not set
        self.mem_limit = mem_limit or int(self.config.get("memory_limit", 2097152))
        self.output_limit = output_limit or int(self.config.get("output_limit", 8192))

        self.run_script_id, self.run_hash = self._script(cursor, "run")
        self.compare_script_id, compare_hash = self._script(
            cursor, special_compare or "compare"
        )
        self.compare_config = json.dumps(
            {
                "script_timelimit": int(self.config.get("script_timelimit", 30)),
                "script_memory_limit": int(
                    self.config.get("script_memory_limit", 2097152)
                ),
                "script_filesize_limit": int(
                    self.config.get("script_filesize_limit", 540672)
                ),
                "compare_args": compare_args if compare_args else "",
                "combined_run_compare": False,
                "hash": compare_hash,
            }
        )

        cursor.execute(
            "SELECT testcaseid, md5sum_input, md5sum_output FROM testcase WHERE probid = %s AND deleted = 0 ORDER BY ranknumber",
            (problem_id,),
        )
        self.testcases = cursor.fetchall()
        # language id -> (compile script id, compile config, run config)
        self._languages: dict[str, tuple[Any, str, str]] = {}

    @staticmethod
    def _script(cursor: Cursor, executable_id: str) -> tuple[Any, Any]:
        cursor.execute(
            "SELECT e.immutable_execid, ie.hash FROM executable e "
            "INNER JOIN immutable_executable ie ON e.immutable_execid = ie.immutable_execid "
            "WHERE e.execid = %s",
            (executable_id,),
        )
        result = cursor.fetchone()
        return (result[0], result[1]) if result else (None, None)

    def _language(self, cursor: Cursor, language_id: str) -> tuple[Any, str, str]:
        if language_id not in self._languages:
            cursor.execute(
                "SELECT l.extensions, l.filter_compiler_files, l.time_factor, "
                "e.immutable_execid, ie.hash "
                "FROM language l "
                "INNER JOIN executable e ON l.compile_script = e.execid "
                "INNER JOIN immutable_executable ie ON e.immutable_execid = ie.immutable_execid "
                "WHERE l.langid = %s",
                (language_id,),
            )
            lang_result = cursor.fetchone()
            if not lang_result:
                raise ValueError(f"Language {language_id} not found")
            (
                lang_extensions,
                filter_compiler_files,
                time_factor,
                compile_script_id,
                compile_hash,
            ) = lang_result
            compile_config = json.dumps(
                {
                    "script_timelimit": int(self.config.get("script_timelimit", 30)),
                    "script_memory_limit": int(
                        self.config.get("script_memory_limit", 2097152)
                    ),
                    "script_filesize_limit": int(
                        self.config.get("script_filesize_limit", 540672)
                    ),
                    "language_extensions": json.loads(lang_extensions)
                    if lang_extensions
                    else [],
                    "filter_compiler_files": bool(filter_compiler_files),
                    "hash": compile_hash,
                }
            )
            run_config = json.dumps(
                {
                    "time_limit": float(self.time_limit) * float(time_factor),
                    "memory_limit": int(self.mem_limit),
                    "output_limit": int(self.output_limit),
                    "process_limit": int(self.config.get("process_limit", 64)),
                    "entry_point": None,
                    "pass_limit": int(self.multipass_limit)
                    if self.multipass_limit
                    else 1,
                    "hash": self.run_hash,
                    "overshoot": 0,
                }
            )
            self._languages[language_id] = (
                compile_script_id,
                compile_config,
                run_config,
            )
        return self._languages[language_id]

    def create(
        self,
        cursor: Cursor,
        submission_id: int,
        contest_id: int,
        start_time: Any,
        language_id: str,
    ) -> None:
        compile_script_id, compile_config, run_config = self._language(
            cursor, language_id
        )
        judging_uuid = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO judging (submitid, cid, starttime, valid, uuid) "
            "VALUES (%s, %s, %s, 1, %s)",
            (submission_id, contest_id, start_time, judging_uuid),
        )
        judging_id = cursor.lastrowid

        # A judging task and a run for each test case
        for testcase_id, input_hash, output_hash in self.testcases:
            testcase_hash = (
                input_hash + "_" + output_hash if input_hash and output_hash else ""
            )
            cursor.execute(
                "INSERT INTO judgetask (type, priority, judgehostid, jobid, submitid, "
                "compile_script_id, run_script_id, compare_script_id, "
                "compile_config, run_config, compare_config, "
                "testcase_id, testcase_hash, valid, uuid) "
                "VALUES ('judging_run', 0, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)",
                (
                    judging_id,
                    submission_id,
                    compile_script_id,
                    self.run_script_id,
                    self.compare_script_id,
                    compile_config,
                    run_config,
                    self.compare_config,
                    testcase_id,
                    testcase_hash,
                    judging_uuid,
                ),
            )
            judge_task_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO judging_run (judgingid, judgetaskid, testcaseid) VALUES (%s, %s, %s)",
                (judging_id, judge_task_id, testcase_id),
            )

        cursor.execute(
            "INSERT INTO queuetask (judgingid, priority, teampriority, starttime) "
            "VALUES (%s, 0, 0, NULL)",
            (judging_id,),
        )


def _insert_submission(
    cursor: Cursor,
    tasks: _JudgingTasks,
    submission: ProblemSubmission,
    previous_id: int | None,
    contest_id: int,
    start_time: Any,
    team_id: int,
    problem_id: int,
    expected_results: str,
) -> None:
    language = submission.language
    assert language is not None
    cursor.execute(
        "INSERT INTO submission (origsubmitid, cid, teamid, probid, "
        "langid, submittime, valid, expected_results, externalid, source) "
        "VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, 'unknown')",
        (
            previous_id,
            contest_id,
            team_id,
            problem_id,
            language.key,
            start_time,
            expected_results,
            jury_submission_external_id(),
        ),
    )
    submission_id = cursor.lastrowid
    assert submission_id is not None
    log.debug(
        "Inserting file %s for submission %s", submission.file_name, submission_id
    )
    cursor.execute(
        "INSERT INTO submission_file (submitid, filename, ranknumber, sourcecode) "
        "VALUES (%s, %s, 1, %s)",
        (submission_id, submission.file_name, submission.source.encode("utf-8")),
    )
    tasks.create(cursor, submission_id, contest_id, start_time, language.key)


def create_problem_submissions(
    cursor: Cursor,
    problem: Problem,
    submissions: Collection[tuple[Team, ProblemSubmission]],
    team_ids: dict[Team, int],
    contest_ids: Collection[int] | None = None,
):
    """Synchronise the jury submissions of a problem in its contests.

    A submission is identified by team and file name. A changed submission
    (content, language) is inserted as a new submission whose origsubmitid
    points to the previous version; submissions of the given teams whose file
    is gone are deleted.
    """
    log.info("Updating submissions of problem %s", problem.name)
    cursor.execute("SELECT probid FROM problem WHERE externalid = %s", (problem.key,))
    id_query = cursor.fetchone()
    if not id_query:
        raise KeyError(f"No problem found for key {problem.key}")
    problem_id = id_query[0]

    contest_start = _problem_contests(cursor, problem_id, contest_ids)
    if not contest_start:
        return
    contest_ids = set(contest_start)
    log.debug(
        "Updating for contests with ids %s", ",".join([str(i) for i in contest_ids])
    )

    submissions_grouped: dict[tuple[int, tuple[str, ...]], ProblemSubmission] = {}
    used_team_ids = {}
    for team, submission in submissions:
        team_id = team_ids[team]
        key = team_id, (submission.file_name,)
        if key in submissions_grouped:
            log.warning(
                "Multiple submissions for %s/%s (same file name)", team, submission
            )
            continue
        used_team_ids[team_id] = team
        submissions_grouped[key] = submission
    if not submissions_grouped:
        # Existing jury submissions are only matched per team of this call
        log.info("No jury submissions for problem %s", problem.name)
        return

    existing = _existing_submissions(
        cursor, problem_id, list(used_team_ids.keys()), contest_ids
    )
    submission_file_names: dict[int, Collection[str]] = {
        submission_id: tuple(sorted(files.keys()))
        for submission_id, files in existing.files.items()
    }

    # contest -> team -> file name(s) -> submission ids
    submissions_by_contest_and_team: dict[
        int, dict[int, dict[Collection[str], list[int]]]
    ] = {
        contest_id: {team_id: defaultdict(list) for team_id in used_team_ids.keys()}
        for contest_id in contest_ids
    }

    for submission_id, (
        _,
        team_id,
        contest_id,
        _language_id,
        _expected_results,
    ) in existing.submissions.items():
        file_names = submission_file_names.get(submission_id, ())
        if not file_names:
            log.warning("No files for submission %d", submission_id)

        assert team_id in used_team_ids, (
            f"{team_id} not in given teams {' '.join(map(str, team_ids.keys()))}"
        )
        submissions_by_contest_and_team[contest_id][team_id][file_names].append(
            submission_id
        )

    invalid_submission_ids = existing.invalid_ids
    for contest_id, team_id in existing.invalid_groups:
        if (
            contest_id in submissions_by_contest_and_team
            and team_id in submissions_by_contest_and_team[contest_id]
        ):
            for submission_ids in (
                submissions_by_contest_and_team[contest_id].pop(team_id).values()
            ):
                invalid_submission_ids.update(set(submission_ids))

    log.debug(
        "Found %d submissions, %d files, %d invalid submissions",
        len(existing.submissions),
        sum(map(len, submission_file_names.values())),
        len(invalid_submission_ids),
    )

    old_submission_ids: list[int] = []
    current_submissions: dict[int, dict[tuple[int, Collection[str]], int]] = {
        contest_id: {} for contest_id in contest_ids
    }

    for contest_id, team_submissions in submissions_by_contest_and_team.items():
        for team_id, by_file_name_tuples in team_submissions.items():
            for file_names, submission_ids in by_file_name_tuples.items():
                if not submission_ids:
                    continue
                if (team_id, file_names) in submissions_grouped:
                    most_recent = next(iter(submission_ids))
                    visited = set()
                    while most_recent in existing.successor:
                        visited.add(most_recent)
                        most_recent = existing.successor[most_recent]
                        if most_recent in visited:
                            raise ValueError(
                                f"Cyclic submission {' '.join(str(i) for i in submission_ids)}"
                            )
                    current_submissions[contest_id][(team_id, file_names)] = most_recent
                else:
                    old_submission_ids.extend(submission_ids)

    tasks: _JudgingTasks | None = None
    new_submissions = 0
    updated_submissions = 0
    for contest_id in contest_ids:
        for (team_id, file_names), submission in submissions_grouped.items():
            existing_id = current_submissions[contest_id].get(
                (team_id, file_names), None
            )
            language = submission.language
            assert language is not None
            insert = False

            if existing_id is None:
                insert = True
                new_submissions += 1
            else:
                existing_language_id = existing.submissions[existing_id][3]
                existing_file_hashes = existing.files[existing_id]

                if language.key != existing_language_id:
                    log.info("%s changed language?", submission)
                    insert = True
                elif set(file_names) != set(existing_file_hashes.keys()):
                    log.debug(
                        "%s changed files from %s to %s",
                        submission,
                        ",".join(file_names),
                        ",".join(existing_file_hashes.keys()),
                    )
                    insert = True
                else:
                    # TODO Multiple file submissions
                    assert len(file_names) == 1
                    if (
                        submission.source_md5()
                        != existing_file_hashes[submission.file_name]
                    ):
                        log.debug("%s changed hash", submission)
                        insert = True
                if insert:
                    updated_submissions += 1

            assert submission.expected_results is not None
            # DOMjudge compares these with the upper-cased judging result
            expected_keys = sorted(
                expected_result.expected_result_key()
                for expected_result in submission.expected_results
            )
            expected_results_string = json.dumps(expected_keys)
            if insert:
                log.debug(
                    "Adding submission %s by %s to contest %s, problem %s",
                    submission.file_name,
                    used_team_ids[team_id],
                    contest_id,
                    problem_id,
                )
                if tasks is None:
                    tasks = _JudgingTasks(cursor, problem_id)
                _insert_submission(
                    cursor,
                    tasks,
                    submission,
                    existing_id,
                    contest_id,
                    contest_start[contest_id],
                    team_id,
                    problem_id,
                    expected_results_string,
                )
            else:
                cursor.execute(
                    "UPDATE submission "
                    "SET submittime = %s, expected_results = %s "
                    "WHERE submitid = %s",
                    (contest_start[contest_id], expected_results_string, existing_id),
                )

    submissions_to_delete = invalid_submission_ids | set(old_submission_ids)
    if submissions_to_delete:
        log.debug(
            "Deleting %d submissions (%s)",
            len(submissions_to_delete),
            ",".join(str(i) for i in submissions_to_delete),
        )
        cursor.execute(
            "DELETE FROM submission_file "
            f"WHERE submitid IN {list_param(submissions_to_delete)}",
            tuple(submissions_to_delete),
        )
        cursor.execute(
            "DELETE FROM submission "
            f"WHERE submitid IN {list_param(submissions_to_delete)}",
            tuple(submissions_to_delete),
        )

    if new_submissions or updated_submissions or submissions_to_delete:
        log.info(
            "Updated submissions, created %d, updated %d, and deleted %d",
            new_submissions,
            updated_submissions,
            len(submissions_to_delete),
        )
    else:
        log.info("Updated submissions, no changes required")
