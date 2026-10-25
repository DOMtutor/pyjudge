"""Problems: data, statement, checker and test cases.

Part of the writer, which works by key; see the package docstring.
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydomjudge.exc import ElementNotFoundError
from pydomjudge.model import (
    ExecutableType,
    JudgeInstance,
    Problem,
    ProblemTestCase,
)

from ._db import DBCursor as Cursor, get_scalar, list_param
from ._executables import (
    create_or_update_executable,
    delete_unused_immutable_executables,
)

log = logging.getLogger(__name__)


def _write_problem_statement(cursor: Cursor, problem_id: int, content: bytes) -> None:
    """Store the statement, unless the database already has the same one."""
    cursor.execute(
        "SELECT MD5(content) FROM problem_statement_content WHERE probid = %s",
        (problem_id,),
    )
    current = cursor.fetchone()
    if current is not None and current[0] == hashlib.md5(content).hexdigest():
        return
    cursor.execute(
        "INSERT INTO problem_statement_content (probid, content) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE content = VALUES(content)",
        (problem_id, content),
    )


def create_or_update_problem_data(
    cursor: Cursor, instance: JudgeInstance, problem: Problem
) -> int:
    log.debug("Updating problem %s", problem)

    cursor.execute("SELECT probid FROM problem WHERE externalid = %s", (problem.key,))
    id_query = cursor.fetchone()
    if id_query:
        problem_id = id_query[0]
        log.debug("Problem present in database with id %d", problem_id)
        cursor.execute(
            "UPDATE problem SET name = %s WHERE probid = %s", (problem.name, problem_id)
        )
    else:
        log.debug("Creating problem %s in database", problem)
        # Type 1 = [pass-fail], see domjudge/webapp/src/Entity/Problem.php
        cursor.execute(
            "INSERT INTO problem (externalid, name, types) VALUES (%s, %s, %s)",
            (problem.key, problem.name, 1),
        )
        problem_id = cursor.lastrowid
    assert problem_id is not None

    text_data, text_type = problem.problem_text()

    time_factor = problem.limits.time_factor
    if time_factor is None or time_factor <= 0.0:
        raise ValueError(f"Invalid time factor {time_factor} on problem {problem}")
    time_limit = round(instance.base_time * time_factor, 1)
    if time_limit <= 0:
        time_limit = 0.1

    cursor.execute(
        "UPDATE problem "
        "SET problemstatement_type = %s, special_compare_args = %s, "
        "timelimit = %s, memlimit = %s, outputlimit = %s "
        "WHERE probid = %s",
        (
            text_type,
            problem.checker_flags,
            time_limit,
            problem.limits.memory_kib,
            problem.limits.output_kib,
            problem_id,
        ),
    )

    _write_problem_statement(cursor, problem_id, text_data)

    checker = problem.checker
    if checker is None:
        cursor.execute(
            "UPDATE problem SET special_compare = NULL WHERE probid = %s", (problem_id,)
        )
    if checker is not None:
        assert checker.executable_type == ExecutableType.Compare
        create_or_update_executable(cursor, checker)
        cursor.execute(
            "UPDATE problem SET special_compare = %s WHERE probid = %s",
            (checker.key, problem_id),
        )
        log.debug("Updated checker")
        delete_unused_immutable_executables(cursor)

    return problem_id


@dataclass
class DbTestCase:
    case_id: int
    name: str
    description: str | None
    rank: int
    input_md5: str
    output_md5: str

    def __str__(self):
        return f"TC({self.name})"


def test_case_compare_key(case: DbTestCase):
    order = [
        "sample",
        "secret/tiny",
        "secret/small",
        "secret/medium",
        "secret/large",
        "secret/huge",
        "secret/xlarge",
        "secret/test-",
        "secret/special",
        "secret/sparse",
    ]
    for i, prefix in enumerate(order):
        if case.name.startswith(prefix):
            return i, case.name[len(prefix) :]
    if case.description is None:
        log.debug("Case %s name does not start with regular key", case)
    return len(order), case.name


def create_or_update_problem_testcases(
    cursor: Cursor,
    problem: Problem,
    test_case_sort_order: Callable[[DbTestCase], Any] = test_case_compare_key,
) -> int:
    log.debug("Updating problem test cases %s", problem)
    cursor.execute("SELECT probid FROM problem WHERE externalid = %s", (problem.key,))
    query_result = cursor.fetchone()
    if not query_result:
        raise ElementNotFoundError(f"No problem found for key {problem.key}")
    problem_id = query_result[0]

    problem_testcases = problem.testcases

    testcases_by_name: dict[str, DbTestCase] = {}
    leftover_cases = []
    cursor.execute(
        "SELECT t.testcaseid, t.orig_input_filename, t.description, t.ranknumber, "
        "t.md5sum_input, t.md5sum_output "
        "FROM testcase t "
        "WHERE t.probid = %s",
        (problem_id,),
    )

    maximal_rank = 0
    for case_id, file_name, description, rank, input_md5, output_md5 in cursor:
        maximal_rank = max(maximal_rank, rank)
        test_case = DbTestCase(
            case_id=case_id,
            name=file_name,
            description=description,
            rank=rank,
            input_md5=input_md5,
            output_md5=output_md5,
        )
        if not file_name or file_name in testcases_by_name:
            # Unnamed or duplicate: reused for new cases or deleted below
            leftover_cases.append(test_case)
        else:
            testcases_by_name[file_name] = test_case

    log.debug(
        "Found %d test cases in database, %d invalid entries",
        len(testcases_by_name),
        len(leftover_cases),
    )

    matched_cases: list[tuple[ProblemTestCase, DbTestCase]] = []
    missing_cases: list[ProblemTestCase] = []

    for problem_testcase in problem_testcases:
        testcase_name = problem_testcase.unique_name

        if testcase_name in testcases_by_name:
            database_case = testcases_by_name.pop(testcase_name)
            matched_cases.append((problem_testcase, database_case))
        else:
            missing_cases.append(problem_testcase)
    leftover_cases.extend(testcases_by_name.values())

    log.debug(
        "Matched %d cases, creating %d new, %d leftovers",
        len(matched_cases),
        len(missing_cases),
        len(leftover_cases),
    )

    update_testcase_content = []
    for problem_testcase, database_case in matched_cases:
        description = problem_testcase.description
        if description != database_case.description:
            cursor.execute(
                "UPDATE testcase SET description = %s WHERE testcaseid = %s",
                (description, database_case.case_id),
            )
            database_case.description = description

        cursor.execute(
            "SELECT EXISTS(SELECT * FROM testcase_content WHERE testcaseid = %s)",
            (database_case.case_id,),
        )
        if get_scalar(cursor):
            if (
                problem_testcase.input_md5 != database_case.input_md5
                or problem_testcase.output_md5 != database_case.output_md5
            ):
                update_testcase_content.append((problem_testcase, database_case))
                cursor.execute(
                    "UPDATE testcase "
                    "SET md5sum_input = %s, md5sum_output = %s "
                    "WHERE testcaseid = %s",
                    (
                        problem_testcase.input_md5,
                        problem_testcase.output_md5,
                        database_case.case_id,
                    ),
                )
                database_case.input_md5 = problem_testcase.input_md5
                database_case.output_md5 = problem_testcase.output_md5
        else:
            log.warning(
                "Missing test case content on existing case %s", problem_testcase
            )
            update_testcase_content.append((problem_testcase, database_case))

    existing_cases: list[tuple[ProblemTestCase, DbTestCase]] = matched_cases.copy()

    for problem_testcase in missing_cases:
        description = problem_testcase.description
        if description is not None and len(description) >= 255:
            description = description[:255]

        testcase_data = [
            problem_testcase.unique_name,
            description,
            problem_testcase.input_md5,
            problem_testcase.output_md5,
            1 if problem_testcase.is_sample() else 0,
            problem_testcase.image_extension,
        ]
        if leftover_cases:
            leftover_case = leftover_cases.pop()
            case_id = leftover_case.case_id
            case_rank = leftover_case.rank
            testcase_data.append(case_id)
            cursor.execute(
                "UPDATE testcase "
                "SET "
                "orig_input_filename = %s, description = %s, md5sum_input = %s, md5sum_output = %s, "
                "sample = %s, image_type = %s, deleted = 0 "
                "WHERE testcaseid = %s",
                tuple(testcase_data),
            )
        else:
            maximal_rank += 1
            case_rank = maximal_rank
            testcase_data.extend([maximal_rank, problem_id])
            cursor.execute(
                "INSERT INTO testcase (orig_input_filename, description, md5sum_input, md5sum_output, "
                "sample, image_type, deleted, ranknumber, probid) "
                "VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s)",
                testcase_data,
            )
            case_id = cursor.lastrowid

        assert case_id is not None
        database_case = DbTestCase(
            case_id=case_id,
            name=problem_testcase.unique_name,
            description=problem_testcase.description,
            rank=case_rank,
            input_md5=problem_testcase.input_md5,
            output_md5=problem_testcase.output_md5,
        )
        existing_cases.append((problem_testcase, database_case))
        update_testcase_content.append((problem_testcase, database_case))

    if leftover_cases:
        log.debug("Deleting %d leftover cases", len(leftover_cases))
        leftover_ids = tuple(case.case_id for case in leftover_cases)
        cursor.execute(
            f"DELETE FROM testcase_content WHERE testcaseid IN {list_param(leftover_ids)}",
            leftover_ids,
        )
        cursor.execute(
            f"DELETE FROM testcase WHERE testcaseid IN {list_param(leftover_ids)}",
            leftover_ids,
        )

    if len(existing_cases) != len(problem_testcases):
        raise ValueError(
            f"Expected {len(problem_testcases)} cases, got {len(existing_cases)}"
        )

    sorted_cases: list[DbTestCase] = sorted(
        [database_case for _, database_case in existing_cases],
        key=test_case_sort_order,
    )
    rank_update: list[tuple[int, DbTestCase]] = []
    for i, case in enumerate(sorted_cases):
        rank = i + 1
        if rank != case.rank:
            rank_update.append((rank, case))

    if rank_update:
        log.debug("Updating ranks of %d elements", len(rank_update))
        # Ugly hack
        maximal_rank = (
            max(database_case.rank for _, database_case in existing_cases) + 1
        )
        for _, case in rank_update:
            maximal_rank += 1
            cursor.execute(
                "UPDATE testcase SET ranknumber = %s WHERE testcaseid = %s",
                (maximal_rank, case.case_id),
            )
        for new_rank, case in rank_update:
            cursor.execute(
                "UPDATE testcase SET ranknumber = %s WHERE testcaseid = %s",
                (new_rank, case.case_id),
            )
            case.rank = new_rank
    else:
        log.debug("No rank updates required")

    if update_testcase_content:
        log.debug("Updating content of %d cases", len(update_testcase_content))
        for problem_testcase, database_case in update_testcase_content:
            image_data = problem_testcase.image
            if image_data is None:
                image, thumbnail = None, None
            else:
                image, thumbnail = image_data

            # Cannot `REPLACE INTO` or `ON DUPLICATE KEY UPDATE`, because the primary key is auto-incrementing, so we delete and re-insert
            cursor.execute(
                "DELETE FROM testcase_content WHERE testcaseid = %s",
                (database_case.case_id,),
            )
            cursor.execute(
                "INSERT INTO testcase_content (testcaseid, input, output, image, image_thumb)"
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    database_case.case_id,
                    problem_testcase.input,
                    problem_testcase.output,
                    image,
                    thumbnail,
                ),
            )

    testcases_without_image_ids = [
        database_case.case_id
        for case, database_case in existing_cases
        if case.image_extension is None
    ]
    if testcases_without_image_ids:
        cursor.execute(
            "UPDATE testcase_content SET image = NULL, image_thumb = NULL "
            f"WHERE testcaseid IN {list_param(testcases_without_image_ids)}",
            tuple(testcases_without_image_ids),
        )
        if cursor.rowcount:
            log.debug("Removed images from %d cases", cursor.rowcount)

    return problem_id
