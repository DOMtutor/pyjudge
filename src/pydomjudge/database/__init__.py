"""Access to the DOMjudge database.

The writer (``_users``, ``_executables``, ``_settings``, ``_problems``,
``_submissions``, ``_contest``) identifies every object by its key, stored as
DOMjudge's ``externalid``, so names and all other properties can change freely
and are synchronised on the next upload. The reader (``_query``, used by
exports) works by names (contest short name, team name, login), so it also
works on databases that were not created by pydomjudge.
"""

from ._check import (
    ERROR as ERROR,
    INFO as INFO,
    WARNING as WARNING,
    Finding as Finding,
    check_consistency as check_consistency,
)
from ._contest import (
    create_or_update_contest as create_or_update_contest,
    create_or_update_contest_problems as create_or_update_contest_problems,
)
from ._data import (
    ClarificationDto as ClarificationDto,
    ContestDataExport as ContestDataExport,
    ContestDescriptionDto as ContestDescriptionDto,
    ContestProblemDto as ContestProblemDto,
    SubmissionDto as SubmissionDto,
    SubmissionFileDto as SubmissionFileDto,
    TeamCategoryDto as TeamCategoryDto,
    TeamDto as TeamDto,
    TestcaseResultDto as TestcaseResultDto,
    UserDto as UserDto,
)
from ._db import (
    Database as Database,
    DBCursor as DBCursor,
)
from ._executables import (
    create_or_update_executable as create_or_update_executable,
    create_or_update_language as create_or_update_language,
    set_global_languages as set_global_languages,
)
from ._problems import (
    create_or_update_problem_data as create_or_update_problem_data,
    create_or_update_problem_testcases as create_or_update_problem_testcases,
)
from ._query import (
    find_clarifications as find_clarifications,
    find_contest_description as find_contest_description,
    find_contest_keys as find_contest_keys,
    find_contest_problems as find_contest_problems,
    find_languages as find_languages,
    find_submissions as find_submissions,
    find_teams as find_teams,
    find_teams_by_name as find_teams_by_name,
    find_users_by_login as find_users_by_login,
)
from ._settings import update_settings as update_settings
from ._submissions import (
    clear_invalid_submissions as clear_invalid_submissions,
    create_problem_submissions as create_problem_submissions,
)
from ._users import (
    create_or_update_affiliations as create_or_update_affiliations,
    create_or_update_teams as create_or_update_teams,
    create_or_update_users as create_or_update_users,
    disable_unknown_users as disable_unknown_users,
    find_team_id as find_team_id,
    find_user_id as find_user_id,
    update_categories as update_categories,
    update_user_password as update_user_password,
)
