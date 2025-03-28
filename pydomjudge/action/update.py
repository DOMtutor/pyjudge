import datetime
import json
import logging
import time
import faulthandler

from collections import defaultdict
from typing import Dict, Collection, Optional, List, Tuple, Set, Mapping

from mysql.connector.cursor import MySQLCursor

from pydomjudge.scripts.db import list_param, field_not_in_list
from pydomjudge.model import (
    TeamCategory,
    Team,
    Executable,
    Language,
    Problem,
    ProblemTestCase,
    ExecutableType,
    JudgeSettings,
    Verdict,
    ProblemSubmission,
    Contest,
    UserRole,
    User,
    Affiliation,
)

from .data import DbTestCase, test_case_compare_key
from ..model.settings import JudgeInstance
from ..model.team import SystemCategory

# Debug MySQL in case it acts up
faulthandler.enable()

log = logging.getLogger(__name__)

user_role_to_database = {
    UserRole.Participant: ["team"],
    UserRole.Admin: ["admin"],
    UserRole.Organizer: ["admin", "jury", "team"],
    UserRole.Jury: ["jury", "team"],
}


def find_all_categories(
    cursor: MySQLCursor, categories: List[TeamCategory]
) -> Mapping[TeamCategory, int]:
    cursor.execute("SELECT categoryid, name FROM team_category")

    all_categories = list(categories) + list(SystemCategory)
    database_to_category: Dict[str, TeamCategory] = {
        category.database_name: category for category in all_categories
    }

    category_ids_by_name: Mapping[str, int] = {
        name: category_id for category_id, name in cursor
    }
    category_ids: Mapping[TeamCategory, int] = {
        database_to_category[name]: category_id
        for name, category_id in category_ids_by_name.items()
        if name in database_to_category
    }
    log.debug("Found existing categories %s", ", ".join(category_ids_by_name.keys()))
    return category_ids


def find_system_categories(cursor: MySQLCursor) -> Mapping[TeamCategory, int]:
    return find_all_categories(cursor, [])


def update_categories(
    cursor: MySQLCursor, categories: List[TeamCategory], lazy=False
) -> Mapping[TeamCategory, int]:
    expected_categories = set(categories) | set(SystemCategory)
    expected_categories_by_name = {
        category.database_name: category for category in expected_categories
    }

    cursor.execute("SELECT categoryid, name FROM team_category")
    existing_ids_by_name: Mapping[str, int] = {
        name: category_id for category_id, name in cursor
    }

    if lazy and existing_ids_by_name.keys() == expected_categories_by_name.keys():
        return {
            expected_categories_by_name[name]: category_id
            for name, category_id in existing_ids_by_name.items()
        }

    log.info("Updating judge categories")

    category_ids_to_delete: Collection[int] = {
        category_id
        for category_name, category_id in existing_ids_by_name.items()
        if category_name not in expected_categories_by_name
    }

    category_ids = {}

    for category in expected_categories:
        name = category.database_name
        cursor.execute("SELECT categoryid FROM team_category WHERE name = ?", (name,))
        result = cursor.fetchall()
        if result:
            if len(result) > 1:
                raise ValueError(f"Multiple categories with name {name}")
            category_id = result[0][0]
            log.debug("Found category %s", name)
        else:
            log.debug("Creating category %s", name)
            cursor.execute("INSERT INTO team_category (name) VALUES (?)", (name,))
            category_id = cursor.lastrowid

        category_ids[category] = category_id
        cursor.execute(
            "UPDATE team_category "
            "SET sortorder = ?, color = ?, visible = ?, allow_self_registration = ? "
            "WHERE categoryid = ?",
            (
                category.order,
                category.color,
                category.visible,
                category.self_registration,
                category_id,
            ),
        )

    if category_ids_to_delete:
        log.info("Deleting %d categories", len(category_ids_to_delete))
        cursor.execute(
            f"UPDATE team SET categoryid = NULL "
            f"WHERE categoryid IN {list_param(category_ids_to_delete)}",
            tuple(category_ids_to_delete),
        )
        cursor.execute(
            f"DELETE FROM team_category WHERE categoryid IN {list_param(category_ids_to_delete)}",
            tuple(category_ids_to_delete),
        )
    return category_ids


def create_or_update_teams(
    cursor: MySQLCursor,
    teams: Collection[Team],
    affiliation_ids: Dict[Affiliation, int],
    user_ids: Dict[User, int],
) -> Dict[Team, int]:
    log.info("Updating %d teams", len(teams))
    if not teams:
        return {}

    categories = set(team.category for team in teams if team.category is not None)
    category_ids = find_all_categories(cursor, list(categories))

    teams_by_name: Dict[str, Team] = {team.name: team for team in teams}
    cursor.execute(
        f"SELECT teamid, name FROM team WHERE name IN {list_param(teams)}",
        tuple(team.name for team in teams),
    )
    existing_teams: Dict[Team, int] = {
        teams_by_name[name]: team_id for team_id, name in cursor
    }

    for team in teams:
        team_category = category_ids[team.category] if team.category else None
        affiliation_id = affiliation_ids[team.affiliation] if team.affiliation else None

        if team in existing_teams:
            team_id = existing_teams[team]
            cursor.execute(
                "UPDATE team SET display_name = ?, categoryid = ?, affilid = ? WHERE teamid = ?",
                (team.display_name, team_category, affiliation_id, team_id),
            )
        else:
            log.debug("Creating team %s", team.name)
            cursor.execute(
                "INSERT INTO team (name, display_name, categoryid, affilid) "
                "VALUES (?, ?, ?, ?)",
                (team.name, team.display_name, team_category, affiliation_id),
            )
            team_id = cursor.lastrowid
            existing_teams[team] = team_id

        if team.members:
            member_ids = [user_ids[user] for user in team.members]
            cursor.execute(
                f"UPDATE `user` SET teamid = ? WHERE userid IN {list_param(member_ids)}",
                (team_id, *member_ids),
            )
            cursor.execute(
                f"UPDATE `user` SET teamid = NULL "
                f"WHERE teamid = ? AND userid NOT IN {list_param(team.members)}",
                (team_id, *member_ids),
            )

    return existing_teams


def create_or_update_executable(cursor: MySQLCursor, executable: Executable):
    log.debug("Updating executable %s", executable)
    data, md5 = executable.make_zip()
    cursor.execute(
        "REPLACE INTO executable (execid, type, description, zipfile, md5sum) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            executable.key,
            executable.executable_type.value,
            executable.description,
            data,
            md5,
        ),
    )


def create_or_update_language(
    cursor: MySQLCursor, language: Language, allow_submit: bool = True
):
    create_or_update_executable(cursor, language.compile_script)
    log.debug("Updating language %s", language)
    cursor.execute(
        "INSERT INTO language (langid, "
        "externalid, compile_script, name, extensions, "
        "time_factor, entry_point_description, require_entry_point, "
        "allow_submit, allow_judge) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE) "
        "ON DUPLICATE KEY UPDATE "
        "externalid = ?, compile_script = ?, name = ?, extensions = ?, "
        "time_factor = ?, entry_point_description = ?, require_entry_point = ?,"
        "allow_submit = ?, allow_judge = TRUE",
        (
            language.key,
            language.key,
            language.compile_script.key,
            language.name,
            json.dumps(list(language.extensions)),
            language.time_factor,
            language.entry_point_description,
            language.entry_point_required,
            allow_submit,
            language.key,
            language.compile_script.key,
            language.name,
            json.dumps(list(language.extensions)),
            language.time_factor,
            language.entry_point_description,
            language.entry_point_required,
            allow_submit,
        ),
    )


def update_problem_statement(cursor: MySQLCursor, problem: Problem) -> int:
    cursor.execute("SELECT probid FROM problem WHERE externalid = ?", (problem.key,))
    id_query = cursor.fetchone()
    if not id_query:
        raise KeyError(f"Problem {problem.key} does not exist in database")

    problem_id = id_query[0]
    cursor.execute(
        "UPDATE problem SET name = ? WHERE probid = ?", (problem.name, problem_id)
    )

    text_data, text_type = problem.problem_text
    cursor.execute(
        "UPDATE problem SET problemtext = ?, problemtext_type = ? WHERE probid = ?",
        (text_data, text_type, problem_id),
    )
    return problem_id


def create_or_update_problem_data(
    cursor: MySQLCursor,
    instance: JudgeInstance,
    problem: Problem,
    assignment=False,  # TODO
) -> int:
    log.debug("Updating problem %s", problem)

    cursor.execute("SELECT probid FROM problem WHERE externalid = ?", (problem.key,))
    id_query = cursor.fetchone()
    if id_query:
        problem_id = id_query[0]
        log.debug("Problem present in database with id %d", problem_id)
        cursor.execute(
            "UPDATE problem SET name = ? WHERE probid = ?", (problem.name, problem_id)
        )
    else:
        log.debug("Creating problem %s in database", problem)
        cursor.execute(
            "INSERT INTO problem (externalid, name) VALUES (?, ?)",
            (problem.key, problem.name),
        )
        problem_id = cursor.lastrowid

    text_data, text_type = problem.problem_text(assignment=assignment)

    time_factor = problem.limits.time_factor
    if time_factor is None or time_factor <= 0.0:
        raise ValueError(f"Invalid time factor {time_factor} on problem {problem}")
    time_limit = round(instance.base_time * time_factor, 1)
    if time_limit <= 0:
        time_limit = 0.1

    cursor.execute(
        "UPDATE problem "
        "SET problemtext = ?, problemtext_type = ?, special_compare_args = ?, "
        "timelimit = ?, memlimit = ?, outputlimit = ? "
        "WHERE probid = ?",
        (
            text_data,
            text_type,
            problem.checker_flags,
            time_limit,
            problem.limits.memory_kib,
            problem.limits.output_kib,
            problem_id,
        ),
    )

    checker = problem.checker
    if checker is None:
        cursor.execute(
            "UPDATE problem SET special_compare = NULL WHERE probid = ?", (problem_id,)
        )
    if checker is not None:
        assert checker.executable_type == ExecutableType.Compare
        create_or_update_executable(cursor, checker)
        cursor.execute(
            "UPDATE problem SET special_compare = ? WHERE probid = ?",
            (checker.key, problem_id),
        )
        log.debug("Updated checker")

    return problem_id


def create_or_update_problem_testcases(cursor: MySQLCursor, problem: Problem) -> int:
    log.debug("Updating problem test cases %s", problem)
    cursor.execute("SELECT probid FROM problem WHERE externalid = ?", (problem.key,))
    problem_id = cursor.fetchone()[0]

    problem_testcases = problem.testcases

    testcases_by_name: Dict[str, DbTestCase] = {}
    leftover_cases = []
    cursor.execute(
        "SELECT t.testcaseid, t.orig_input_filename, t.description, t.`rank`, "
        "t.md5sum_input, t.md5sum_output "
        "FROM testcase t "
        "WHERE t.probid = ?",
        (problem_id,),
    )

    maximal_rank = 0
    for case_id, file_name, description, rank, input_md5, output_md5 in cursor:
        maximal_rank = max(maximal_rank, rank)
        test_case = DbTestCase(
            case_id, file_name, description, rank, input_md5, output_md5
        )
        if not file_name or file_name in testcases_by_name:
            leftover_cases.append(test_case)
        else:
            if file_name in testcases_by_name:
                raise KeyError(f"Duplicate case for problem {problem_id}")
            testcases_by_name[file_name] = test_case

    log.debug(
        "Found %d test cases in database, %d invalid entries",
        len(testcases_by_name),
        len(leftover_cases),
    )

    matched_cases: List[Tuple[ProblemTestCase, DbTestCase]] = []
    missing_cases: List[ProblemTestCase] = []

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
        if description and len(description) >= 255:
            description = description[:255]
        if description != database_case.description:
            cursor.execute(
                "UPDATE testcase SET description = ? WHERE testcaseid = ?",
                (database_case.case_id, description),
            )
            database_case.description = description

        cursor.execute(
            "SELECT EXISTS(SELECT * FROM testcase_content WHERE testcaseid = ?)",
            (database_case.case_id,),
        )
        if cursor.fetchone()[0]:
            if (
                problem_testcase.input_md5 != database_case.input_md5
                or problem_testcase.output_md5 != database_case.output_md5
            ):
                update_testcase_content.append((problem_testcase, database_case))
                cursor.execute(
                    "UPDATE testcase "
                    "SET md5sum_input = ?, md5sum_output = ? "
                    "WHERE testcaseid = ?",
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

    existing_cases: List[Tuple[ProblemTestCase, DbTestCase]] = matched_cases.copy()

    for problem_testcase in missing_cases:
        description = problem_testcase.description
        if problem_testcase.description and len(description) >= 255:
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
                "orig_input_filename = ?, description = ?, md5sum_input = ?, md5sum_output = ?, "
                "sample = ?, image_type = ?, deleted = 0 "
                "WHERE testcaseid = ?",
                tuple(testcase_data),
            )
        else:
            maximal_rank += 1
            case_rank = maximal_rank
            testcase_data.extend([maximal_rank, problem_id])
            cursor.execute(
                "INSERT INTO testcase (orig_input_filename, description, md5sum_input, md5sum_output, "
                "sample, image_type, deleted, `rank`, probid) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                testcase_data,
            )
            case_id = cursor.lastrowid

        database_case = DbTestCase(
            case_id,
            problem_testcase.unique_name,
            problem_testcase.description,
            case_rank,
            problem_testcase.input_md5,
            problem_testcase.output_md5,
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

    # cursor.execute("SELECT COUNT(*) FROM testcase WHERE probid = %s", (problem_id,))
    # database_testcase_count = cursor.next()[0]
    # if database_testcase_count != len(existing_cases):
    #     raise ValueError(f"Expected {len(existing_cases)} cases in DB, got {database_testcase_count}")

    sorted_cases: List[DbTestCase] = sorted(
        [database_case for _, database_case in existing_cases],
        key=test_case_compare_key,
    )
    rank_update: List[Tuple[int, DbTestCase]] = []
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
                "UPDATE testcase SET `rank` = ? WHERE testcaseid = ?",
                (maximal_rank, case.case_id),
            )
        for new_rank, case in rank_update:
            cursor.execute(
                "UPDATE testcase SET `rank` = ? WHERE testcaseid = ?",
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

            cursor.execute(
                "REPLACE INTO testcase_content (testcaseid, input, output, image, image_thumb)"
                "VALUES (?, ?, ?, ?, ?)",
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


def update_settings(cursor: MySQLCursor, settings: JudgeSettings):
    log.info("Updating judge settings")
    verdict_names = {
        Verdict.COMPILER_ERROR: "compiler-error",
        Verdict.PRESENTATION_ERROR: "presentation-error",
        Verdict.CORRECT: "correct",
        Verdict.WRONG_ANSWER: "wrong-answer",
        Verdict.OUTPUT_LIMIT: "output-limit",
        Verdict.RUN_ERROR: "run-error",
        Verdict.TIME_LIMIT: "timelimit",
        Verdict.MEMORY_LIMIT: "memory-limit",
        Verdict.NO_OUTPUT: "no-output",
    }

    def write(key, value):
        cursor.execute(
            "REPLACE INTO configuration (name, value) VALUES (?, ?)", (key, value)
        )

    scoring = settings.scoring
    write("penalty_time", scoring.penalty_time)
    write(
        "results_prio",
        json.dumps(
            {
                f"{verdict_names[verdict]}": str(priority)
                for verdict, priority in scoring.result_priority.items()
            }
        ),
    )

    judging = settings.judging
    write("memory_limit", judging.memory_limit)
    write("output_limit", judging.output_limit)
    write("timelimit_overshoot", f'"{judging.time_overshoot}"')
    write("sourcesize_limit", judging.source_size_limit)
    write("sourcefiles_limit", judging.source_file_limit)
    write("script_memory_limit", judging.script_memory_limit)
    write("script_timelimit", judging.script_time_limit)
    write("script_filesize_limit", judging.script_size_limit)
    write("output_storage_limit", judging.output_storage_limit)
    write("output_display_limit", judging.output_display_limit)
    write("lazy_eval_results", judging.lazy_eval)

    display = settings.display
    write("show_pending", display.show_pending)
    write("show_flags", display.show_flags)
    write("show_affiliations", display.show_affiliations)
    write("show_affiliation_logos", display.show_affiliation_logos)
    write("show_teams_submissions", display.show_teams_submissions)
    write("show_sample_output", display.show_sample_output)
    write("show_compile", display.show_compile)

    clarification = settings.clarification
    if not isinstance(clarification.answers, list):
        raise ValueError
    write("clar_answers", json.dumps(clarification.answers))


def set_languages(
    cursor: MySQLCursor,
    languages: Collection[Language],
    allowed_for_submission: Optional[Set[str]],
):
    if allowed_for_submission is None:
        log.debug("Using all available languages")
        allowed_keys = {language.key for language in languages}
    else:
        allowed_keys = set()
        language_by_key = {language.key: language for language in languages}
        for key in allowed_for_submission:
            if key not in language_by_key:
                raise ValueError(
                    f"Unknown language {key}, known languages are {' '.join(language_by_key.keys())}"
                )
            allowed_keys.add(key)

    log.info(
        "Setting the list of languages to %s", [language.name for language in languages]
    )
    cursor.execute("UPDATE language SET externalid = langid WHERE externalid != langid")
    for language in languages:
        create_or_update_language(
            cursor, language, allow_submit=language.key in allowed_keys
        )

    cursor.execute(
        "SELECT langid, compile_script, EXISTS(SELECT * FROM submission "
        "  WHERE submission.langid = language.langid) as has_submission "
        f"FROM language WHERE {field_not_in_list('langid', languages)}",
        tuple(language.key for language in languages),
    )
    languages_to_delete = []
    scripts_to_delete = []
    languages_to_disallow = []
    for language_id, script, has_submission in cursor:
        if has_submission:
            languages_to_disallow.append(language_id)
        else:
            languages_to_delete.append(language_id)
            if script:
                scripts_to_delete.append(script)
    if scripts_to_delete:
        cursor.execute(
            f"DELETE FROM executable WHERE execid IN {list_param(scripts_to_delete)} "
            f"AND type = 'compile'",
            tuple(scripts_to_delete),
        )  # Safeguard
    if languages_to_delete:
        cursor.execute(
            f"DELETE FROM language WHERE langid IN {list_param(languages_to_delete)}",
            tuple(languages_to_delete),
        )
    if languages_to_disallow:
        log.warning(
            "There are some non-configured languages with submissions: %s",
            ",".join(languages_to_disallow),
        )
        cursor.execute(
            f"UPDATE language SET allow_submit = FALSE "
            f"WHERE langid IN {list_param(languages_to_disallow)}",
            tuple(languages_to_disallow),
        )


def clear_invalid_submissions(cursor):
    cursor.execute(
        "DELETE FROM submission_file "
        "WHERE LENGTH(submission_file.sourcecode) = '' OR LOCATE('\\0', submission_file.sourcecode) > 0"
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


# TODO Should be for multiple problems :-)
# TODO Submission time


def create_problem_submissions(
    cursor: MySQLCursor,
    problem: Problem,
    existing_submissions: Collection[Tuple[Team, ProblemSubmission]],
    team_ids: Dict[Team, int],
    contest_ids: Optional[List[int]] = None,
):
    log.info("Updating submissions of problem %s", problem.name)
    cursor.execute("SELECT probid FROM problem WHERE externalid = ?", (problem.key,))
    id_query = cursor.fetchone()
    if not id_query:
        raise KeyError(f"No problem found for key {problem.key}")
    problem_id = id_query[0]

    contest_start = {}
    if contest_ids is None:
        cursor.execute(
            "SELECT c.cid, c.starttime FROM contest c JOIN contestproblem cp on c.cid = cp.cid "
            "WHERE cp.probid = ?",
            (problem_id,),
        )
        contest_ids = set()
        for contest_id, start_time in cursor:
            contest_ids.add(contest_id)
            contest_start[contest_id] = start_time
        if not contest_ids:
            log.info("Problem not used in any contests")
            return
    elif not contest_ids:
        log.info("No contests specified")
        return
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
    log.debug("Updating for contests with ids %s", ",".join(map(str, contest_ids)))

    submissions_grouped: Dict[Tuple[int, Tuple[str, ...]], ProblemSubmission] = dict()
    used_team_ids = dict()
    for team, submission in existing_submissions:
        team_id = team_ids[team]
        key = team_id, (submission.file_name,)
        if key in submissions_grouped:
            log.warning(
                "Multiple submissions for %s/%s (same file name)", team, submission
            )
            continue
        used_team_ids[team_id] = team
        submissions_grouped[key] = submission

    cursor.execute(
        f"SELECT "
        f"  submitid, origsubmitid, teamid, cid, expected_results, langid "
        f"FROM submission s "
        f"WHERE "
        f"  probid = ? AND "
        f"  teamid IN {list_param(used_team_ids.keys())} AND "
        f"  cid IN {list_param(contest_ids)}",
        (problem_id,) + tuple(used_team_ids.keys()) + tuple(contest_ids),
    )
    invalid_submission_ids = set()
    invalid_submissions_groups = set()
    existing_submissions: Dict[int, Tuple[int, int, int, int, Tuple[Verdict, ...]]] = {}
    submission_successor: Dict[int, int] = {}
    for (
        submission_id,
        original_submission_id,
        team_id,
        contest_id,
        expected_results_string,
        language_id,
    ) in cursor:
        expected_results_list = (
            json.loads(expected_results_string) if expected_results_string else []
        )
        try:
            expected_results: Tuple[Verdict, ...] = tuple(
                Verdict.parse_from_judge(verdict) for verdict in expected_results_list
            )
        except KeyError:
            log.warning(
                "Submission %s has invalid results %s",
                submission_id,
                expected_results_string,
            )
            invalid_submissions_groups.add((contest_id, team_id))
            invalid_submission_ids.add(submission_id)
            continue
        if submission_id in existing_submissions:
            raise ValueError(f"Multiple submissions for id {submission_id}")

        if original_submission_id is not None:
            if original_submission_id in submission_successor:
                # TODO I think this is not allowed by domjudge, so raise exception
                raise ValueError(
                    f"Multiple successors for submission {original_submission_id}: "
                    f"{submission_id} and {submission_successor[original_submission_id]}"
                )
            submission_successor[original_submission_id] = submission_id

        existing_submissions[submission_id] = (
            original_submission_id,
            team_id,
            contest_id,
            language_id,
            expected_results,
        )

    submission_files: Dict[int, Dict[str, str]] = defaultdict(dict)
    if existing_submissions:
        cursor.execute(
            f"SELECT submitid, submitfileid, filename, MD5(sourcecode) as source_md5 "
            f"FROM submission_file sf WHERE "
            f"submitid IN {list_param(existing_submissions)}",
            tuple(existing_submissions.keys()),
        )
        for submission_id, file_id, file_name, file_md5 in cursor:
            files = submission_files[submission_id]
            if file_name in files:
                raise ValueError(f"Duplicate file names for submission {submission_id}")
            files[file_name] = file_md5
    submission_file_names: dict[int, Collection[str]] = {
        submission_id: tuple(sorted(files.keys()))
        for submission_id, files in submission_files.items()
    }

    # contest -> team -> file name(s) -> submission ids
    submissions_by_contest_and_team: Dict[
        int, Dict[int, Dict[Collection[str], List[int]]]
    ] = {
        contest_id: {team_id: defaultdict(list) for team_id in used_team_ids.keys()}
        for contest_id in contest_ids
    }

    for submission_id, (
        _,
        team_id,
        contest_id,
        expected_results,
        language_id,
    ) in existing_submissions.items():
        file_names = submission_file_names.get(submission_id, tuple())
        if not file_names:
            log.warning("No files for submission %d", submission_id)

        assert team_id in used_team_ids, (
            f"{team_id} not in given teams {' '.join(map(str, team_ids.keys()))}"
        )
        submissions_by_contest_and_team[contest_id][team_id][file_names].append(
            submission_id
        )

    for contest_id, team_id in invalid_submissions_groups:
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
        len(existing_submissions),
        sum(map(len, submission_file_names.values())),
        len(invalid_submission_ids),
    )

    old_submission_ids: List[int] = []
    current_submissions: Dict[int, Dict[Tuple[int, Collection[str]], int]] = {
        contest_id: dict() for contest_id in contest_ids
    }

    for contest_id, team_submissions in submissions_by_contest_and_team.items():
        for team_id, by_file_name_tuples in team_submissions.items():
            for file_names, submission_ids in by_file_name_tuples.items():
                if not submission_ids:
                    continue
                if (team_id, file_names) in submissions_grouped:
                    most_recent = next(iter(submission_ids))
                    visited = set()
                    while most_recent in submission_successor:
                        visited.add(most_recent)
                        most_recent = submission_successor[most_recent]
                        if most_recent in visited:
                            raise ValueError(
                                f"Cyclic submission {' '.join(map(str, submission_ids))}"
                            )
                    current_submissions[contest_id][(team_id, file_names)] = most_recent
                else:
                    old_submission_ids.extend(submission_ids)

    new_submissions = 0
    updated_submissions = 0
    for contest_id in contest_ids:
        for (team_id, file_names), submission in submissions_grouped.items():
            existing_id = current_submissions[contest_id].get(
                (team_id, file_names), None
            )
            language = submission.language
            insert = False

            if existing_id is None:
                insert = True
                new_submissions += 1
            else:
                existing_language_id = existing_submissions[existing_id][3]
                existing_file_hashes = submission_files[existing_id]

                if language.key != existing_language_id:
                    log.info("%s changed language?", submission)
                    insert = True
                elif set(file_names) != set(existing_file_hashes.keys()):
                    log.debug(
                        "%s changed files from %s to %s",
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
            expected_keys = [
                expected_result.judge_key()
                for expected_result in submission.expected_results
            ]
            expected_results_string = json.dumps(expected_keys)
            if insert:
                source_code: str = submission.source
                log.debug(
                    "Adding submission %s by %s to contest %s, problem %s",
                    submission.file_name,
                    used_team_ids[team_id],
                    contest_id,
                    problem_id,
                )

                # Sleep is needed to prevent segfault of the mysql-connector?!
                time.sleep(0.2)
                cursor.execute(
                    "INSERT INTO submission (origsubmitid, cid, teamid, probid, langid, submittime, "
                    "judgehost, valid, expected_results) "
                    "VALUES (?, ?, ?, ?, ?, ?, NULL, 1, ?)",
                    (
                        existing_id,
                        contest_id,
                        team_id,
                        problem_id,
                        language.key,
                        contest_start[contest_id],
                        expected_results_string,
                    ),
                )
                new_submission_id = cursor.lastrowid
                source_bytes = source_code.encode("utf-8")
                log.debug(
                    "Inserting file %s for submission %s",
                    submission.file_name,
                    new_submission_id,
                )

                time.sleep(0.2)
                cursor.execute(
                    "INSERT INTO submission_file (submitid, filename, `rank`, sourcecode) "
                    "VALUES (?, ? , 1, ?)",
                    (new_submission_id, submission.file_name, source_bytes),
                )
                time.sleep(0.2)
            else:
                cursor.execute(
                    "UPDATE submission "
                    "SET submittime = ?, expected_results = ? "
                    "WHERE submitid = ?",
                    (contest_start[contest_id], expected_results_string, existing_id),
                )
                time.sleep(0.2)

    submissions_to_delete = invalid_submission_ids | set(old_submission_ids)
    if submissions_to_delete:
        log.debug(
            "Deleting %d submissions (%s)",
            len(submissions_to_delete),
            ",".join(map(str, submissions_to_delete)),
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


def create_or_update_contest_problems(
    cursor: MySQLCursor,
    contest: Contest,
    contest_id: int,
    problem_ids: Dict[Problem, int],
):
    # TODO Does not yet handle the case when contest problem is changed

    for contest_problem in contest.problems:
        # Cannot REPLACE INTO because of database triggers
        problem_id = problem_ids[contest_problem.problem]
        cursor.execute(
            "SELECT EXISTS(SELECT * FROM contestproblem WHERE cid = ? AND probid = ?)",
            (contest_id, problem_id),
        )
        if cursor.fetchone()[0]:
            cursor.execute(
                "UPDATE contestproblem SET "
                "shortname = ?, points = ?, allow_submit = TRUE, allow_judge = TRUE,"
                "color = ?, lazy_eval_results = NULL "
                "WHERE cid = ? AND probid = ?",
                (
                    contest_problem.name,
                    contest_problem.points,
                    contest_problem.color,
                    contest_id,
                    problem_id,
                ),
            )
        else:
            cursor.execute(
                "INSERT INTO contestproblem (cid, probid, shortname, points, allow_submit, "
                "allow_judge, color, lazy_eval_results) VALUES (?, ?, ?, ?, TRUE, TRUE, ?, NULL)",
                (
                    contest_id,
                    problem_id,
                    contest_problem.name,
                    contest_problem.points,
                    contest_problem.color,
                ),
            )


def create_or_update_contest(cursor: MySQLCursor, contest: Contest, force=False) -> int:
    date_format = "%Y-%m-%d %H:%M:%S"

    def format_datetime(dt: Optional[datetime.datetime]):
        if dt is None:
            return None
        return f"{dt.strftime(date_format)} {dt.tzinfo}"

    cursor.execute(
        "SELECT cid, starttime, endtime FROM contest WHERE shortname = ?",
        (contest.key,),
    )
    id_query = cursor.fetchone()
    if id_query:
        contest_id, current_start, current_end = id_query

        if float(current_start) <= time.time() <= float(current_end):
            if force:
                log.warning("Modified contest is currently running")
            else:
                raise ValueError("Modified contest is currently running")

        cursor.execute(
            "UPDATE contest SET "
            "externalid = ?, name = ?, shortname = ?, "
            "activatetime = ?, activatetime_string = ?, "
            "deactivatetime = ?, deactivatetime_string = ?, "
            "starttime = ?, starttime_string = ?, "
            "endtime = ?, endtime_string = ?, "
            "freezetime = ?, freezetime_string = ?, "
            "b = 0, enabled = TRUE, starttime_enabled = TRUE, process_balloons = FALSE, "
            "public = ?, open_to_all_teams = ? "
            "WHERE cid = ?",
            (
                contest.key,
                contest.name,
                contest.key,
                str(contest.activation_time.timestamp()),
                format_datetime(contest.activation_time),
                str(contest.deactivation_time.timestamp())
                if contest.deactivation_time
                else None,
                format_datetime(contest.deactivation_time),
                str(contest.start_time.timestamp()),
                format_datetime(contest.start_time),
                str(contest.end_time.timestamp()),
                format_datetime(contest.end_time),
                str(contest.freeze_time.timestamp()) if contest.freeze_time else None,
                format_datetime(contest.freeze_time),
                contest.public_scoreboard,
                contest.access is None,
                contest_id,
            ),
        )
    else:
        cursor.execute(
            "INSERT INTO contest (externalid, name, shortname, "
            "activatetime, activatetime_string, "
            "deactivatetime, deactivatetime_string, "
            "starttime, starttime_string, "
            "endtime, endtime_string, "
            "freezetime, freezetime_string, "
            "b, enabled, starttime_enabled, process_balloons, public, open_to_all_teams) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, TRUE, TRUE, FALSE, ?, ?)",
            (
                contest.key,
                contest.name,
                contest.key,
                str(contest.activation_time.timestamp()),
                format_datetime(contest.activation_time),
                str(contest.deactivation_time.timestamp())
                if contest.deactivation_time
                else None,
                format_datetime(contest.deactivation_time),
                str(contest.start_time.timestamp()),
                format_datetime(contest.start_time),
                str(contest.end_time.timestamp()),
                format_datetime(contest.end_time),
                str(contest.freeze_time.timestamp()) if contest.freeze_time else None,
                format_datetime(contest.freeze_time),
                contest.public_scoreboard,
                contest.access is None,
            ),
        )
        contest_id = cursor.lastrowid

    cursor.execute("DELETE FROM contestteam WHERE cid = ?", (contest_id,))
    cursor.execute("DELETE FROM contestteamcategory WHERE cid = ?", (contest_id,))

    if contest.access is not None:
        team_names = contest.access.team_names
        if team_names:
            cursor.execute(
                f"SELECT teamid FROM team WHERE name IN {list_param(team_names)}",
                tuple(team_names),
            )
            team_ids = cursor.fetchall()
            if len(team_ids) != len(team_names):
                raise ValueError("Non-existing teams specified")
            for (team_id,) in team_ids:
                cursor.execute(
                    "INSERT INTO contestteam (cid, teamid) VALUES (?, ?)",
                    (contest_id, team_id),
                )
        team_categories = contest.access.team_categories
        if team_categories:
            cursor.execute(
                f"SELECT categoryid FROM team_category WHERE name IN {list_param(team_categories)}",
                tuple(category.database_name for category in team_categories),
            )
            category_ids = cursor.fetchall()
            if len(category_ids) != len(team_categories):
                raise ValueError("Non-existing teams specified")
            for (category_id,) in category_ids:
                cursor.execute(
                    "INSERT INTO contestteamcategory (cid, categoryid) VALUES (?, ?)",
                    (contest_id, category_id),
                )

    return contest_id


def fetch_user_roles(cursor: MySQLCursor) -> Dict[str, int]:
    cursor.execute("SELECT roleid, role FROM role")
    return {role: role_id for role_id, role in cursor}


def create_or_update_affiliations(
    cursor: MySQLCursor, affiliations: Collection[Affiliation]
) -> Dict[Affiliation, int]:
    log.info("Updating %d affiliations", len(affiliations))
    if not affiliations:
        return {}
    affiliations_by_id = {
        affiliation.short_name: affiliation for affiliation in affiliations
    }

    cursor.execute(
        f"SELECT affilid, externalid FROM team_affiliation "
        f"WHERE externalid IN {list_param(affiliations)}",
        tuple(affiliation.short_name for affiliation in affiliations),
    )
    affiliation_ids: Dict[Affiliation, int] = {
        affiliations_by_id[key]: affiliation_id for affiliation_id, key in cursor
    }
    for affiliation in affiliations:
        if affiliation in affiliation_ids:
            cursor.execute(
                "UPDATE team_affiliation SET "
                "externalid = ?, shortname = ?, name = ?, country = ?, comments = NULL "
                "WHERE affilid = ?",
                (
                    affiliation.short_name,
                    affiliation.short_name,
                    affiliation.name,
                    affiliation.country,
                    affiliation_ids[affiliation],
                ),
            )
        else:
            cursor.execute(
                "INSERT INTO team_affiliation (externalid, shortname, name, country, comments) "
                "VALUES (?, ?, ?, ?, NULL) ",
                (
                    affiliation.short_name,
                    affiliation.short_name,
                    affiliation.name,
                    affiliation.country,
                ),
            )
            affiliation_ids[affiliation] = cursor.lastrowid
    return affiliation_ids


def create_or_update_users(
    cursor: MySQLCursor, users: Collection[User], overwrite_passwords=False
) -> Dict[User, int]:
    log.info("Updating %d users", len(users))
    if not users:
        return {}
    for user in users:
        if user.role not in user_role_to_database:
            raise KeyError(f"Invalid role {user.role}")

    role_ids_by_name = fetch_user_roles(cursor)

    users_by_login = {user.login_name: user for user in users}
    cursor.execute(
        f"SELECT userid, username FROM `user` WHERE username IN {list_param(users)}",
        tuple(user.login_name for user in users),
    )
    user_ids = {users_by_login[name]: user_id for user_id, name in cursor}

    for user in users:
        if user in user_ids:
            user_id = user_ids[user]

            cursor.execute(
                "UPDATE `user` SET username = ?, name = ?, email = ?, enabled = TRUE WHERE userid = ?",
                (user.login_name, user.display_name, user.email, user_id),
            )
            if overwrite_passwords and user.password_hash:
                cursor.execute(
                    "UPDATE `user` SET password = ? WHERE userid = ?",
                    (user.password_hash, user_id),
                )
        else:
            cursor.execute(
                "INSERT INTO `user` (username, name, email, password, enabled) VALUES (?, ?, ?, ?, TRUE)",
                (user.login_name, user.display_name, user.email, user.password_hash),
            )
            user_id = cursor.lastrowid
            user_ids[user] = user_id

        user_roles = set(
            role_ids_by_name[role] for role in user_role_to_database[user.role]
        )
        cursor.execute("SELECT roleid FROM userrole WHERE userid = ?", (user_id,))
        current_roles = set(role_id for (role_id,) in cursor)
        obsolete_roles = current_roles - user_roles
        if obsolete_roles:
            cursor.execute(
                f"DELETE FROM userrole WHERE userid = ? AND roleid IN {list_param(obsolete_roles)}",
                (user_id, *obsolete_roles),
            )
        missing_roles = user_roles - current_roles
        for role_id in missing_roles:
            cursor.execute(
                "INSERT INTO userrole (userid, roleid) VALUES (?, ?)",
                (user_id, role_id),
            )

    return user_ids


def disable_unknown_users(cursor: MySQLCursor, user_login_names: Set[str]):
    valid_users = {"admin", "judgehost"}
    valid_users.update(user_login_names)
    cursor.execute(
        f"UPDATE `user` SET enabled = FALSE WHERE username NOT IN {list_param(valid_users)}",
        tuple(valid_users),
    )
    if cursor.rowcount:
        log.warning("Disabled %d users", cursor.rowcount)
