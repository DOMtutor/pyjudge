import base64
import functools
from typing import Annotated, Any

import chardet
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_serializer,
    field_validator,
)

from pydomjudge.model import PydanticVerdict


def encode_b85(v: bytes) -> str:
    return base64.b85encode(v).decode("ascii")


def decode_b85(v: str | bytes) -> bytes:
    if isinstance(v, bytes):
        return v
    return base64.b85decode(v)


Base85Bytes = Annotated[
    bytes, PlainSerializer(encode_b85, when_used="json"), BeforeValidator(decode_b85)
]


# Users and teams use short JSON names in exports. With this configuration, the
# alias is used for JSON in both directions, while Python code may still pass
# the field names (UserDto(login_name=...)).
_ALIASED = ConfigDict(
    frozen=True,
    validate_by_name=True,
    validate_by_alias=True,
    serialize_by_alias=True,
)


def _decode_text(content: bytes) -> str | None:
    """Decode a source file: UTF-8, else the encoding chardet guesses."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    encoding = chardet.detect(content)["encoding"]
    if encoding is None:
        return None
    try:
        return content.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None


class UserDto(BaseModel):
    model_config = _ALIASED

    login_name: str = Field(alias="login")
    display_name: str = Field(alias="name")
    external_id: str | None = Field(default=None, exclude_if=lambda x: x is None)
    email: str | None = Field(default=None, exclude_if=lambda x: x is None)

    def __str__(self):
        return self.display_name


class TeamDto(BaseModel):
    model_config = _ALIASED

    # No alias "name" for display_name: it would clash with the field name in
    # TeamDto(name=..., display_name=...). ContestDataExport maps it instead.
    name: str
    display_name: str
    category_name: str | None = Field(alias="category")
    affiliation_name: str | None = Field(alias="affiliation")
    external_id: str | None = Field(default=None, exclude_if=lambda x: x is None)
    label: str | None = Field(default=None, exclude_if=lambda x: x is None)
    member_login_names: list[str] = Field(alias="members")

    def __str__(self):
        return f"{self.display_name}"


class SubmissionFileDto(BaseModel):
    filename: str
    content: Base85Bytes

    @property
    def byte_size(self) -> int:
        return len(self.content)

    @functools.cached_property
    def _text(self) -> str | None:
        # Decoding may run chardet, so it is cached; pydantic leaves cached
        # properties out of validation, serialisation and equality
        return _decode_text(self.content)

    @property
    def line_count(self) -> int | None:
        content = self._text
        if content is None:
            return None
        lines = [line.strip() for line in content.splitlines()]
        return len([line for line in lines if line])

    def content_safe(self, default=None) -> str | None:
        content = self._text
        return content if content is not None else default

    @property
    def is_text_file(self):
        return self._text is not None


class TeamCategoryDto(BaseModel, frozen=True):
    name: str
    color: str
    visible: bool
    order: int
    self_registration: bool
    external_id: str | None = Field(
        default=None,
        exclude_if=lambda x: x is None,
        description="External ID of the category, if any.",
    )


class TestcaseResultDto(BaseModel, frozen=True):
    runtime: float
    verdict: PydanticVerdict
    is_sample: bool
    test_name: str


class ContestProblemDto(BaseModel, frozen=True):
    short_name: str = Field(description="The short_name of the problem")
    points: int
    color: str
    problem_name: str
    problem_external_id: str | None


class SubmissionDto(BaseModel, frozen=True):
    team_name: str
    contest_key: str
    contest_problem_key: str
    problem_name: str
    language_key: str
    submission_time: float
    external_id: str | None = Field(
        default=None,
        exclude_if=lambda x: x is None,
        description="External ID of the submission, if any. Must be unique per contest.",
    )

    verdict: PydanticVerdict | None
    case_result: list[TestcaseResultDto]
    too_late: bool

    files: list[SubmissionFileDto]

    @property
    def line_count(self):
        return sum(
            file.line_count for file in self.files if file.line_count is not None
        )

    @property
    def maximum_runtime(self) -> float | None:
        return max(
            (res.runtime for res in self.case_result if res.runtime is not None),
            default=None,
        )

    @property
    def is_source_submission(self):
        return all(file.is_text_file for file in self.files)

    @property
    def byte_size(self):
        return sum(file.byte_size for file in self.files)


class ClarificationDto(BaseModel, frozen=True):
    team_name: str
    contest_key: str = Field(description="The short_name of the contest")
    contest_problem_key: str | None = Field(
        description="The short_name of the contest problem",
    )
    external_id: str | None = Field(default=None, exclude_if=lambda x: x is None)

    request_time: float
    identifier: str
    response_to: str | None
    from_jury: bool
    body: str


class ContestDescriptionDto(BaseModel, frozen=True):
    contest_key: str
    start: float | None
    end: float | None


class ContestDataExport(BaseModel):
    description: ContestDescriptionDto
    users: dict[str, UserDto]
    teams: dict[str, TeamDto]
    languages: dict[str, str]
    problems: dict[str, str]
    submissions: list[SubmissionDto]
    clarifications: list[ClarificationDto]

    # In JSON, users and teams are maps from login / team name to the remaining
    # fields; the key is put back into the object when reading

    @field_validator("users", mode="before")
    @classmethod
    def _users_from_map(cls, users: Any) -> Any:
        if not isinstance(users, dict):
            return users
        return {
            login: {**user, "login": login} if isinstance(user, dict) else user
            for login, user in users.items()
        }

    @field_validator("teams", mode="before")
    @classmethod
    def _teams_from_map(cls, teams: Any) -> Any:
        if not isinstance(teams, dict):
            return teams
        result = {}
        for name, team in teams.items():
            if isinstance(team, dict) and "display_name" not in team:
                # JSON form: "name" holds the display name
                team = {**team, "display_name": team.get("name"), "name": name}
            result[name] = team
        return result

    @field_serializer("users", when_used="json")
    def _users_to_map(self, users: dict[str, UserDto]):
        return {
            user.login_name: user.model_dump(exclude={"login_name"})
            for user in users.values()
        }

    @field_serializer("teams", when_used="json")
    def _teams_to_map(self, teams: dict[str, TeamDto]):
        return {
            team.name: {
                "name": team.display_name,
                **team.model_dump(exclude={"name", "display_name"}),
            }
            for team in teams.values()
        }
