import base64
from typing import Annotated

import chardet
from pydantic import (
    BaseModel,
    PlainSerializer,
    BeforeValidator,
    Field,
    field_serializer,
    model_validator,
)

from pydomjudge.model import PydanticTestcaseVerdict, PydanticVerdict


def encode_b85(v: bytes) -> str:
    return base64.b85encode(v).decode("ascii")


def decode_b85(v: str | bytes) -> bytes:
    if isinstance(v, bytes):
        return v
    return base64.b85decode(v)


Base85Bytes = Annotated[
    bytes, PlainSerializer(encode_b85, when_used="json"), BeforeValidator(decode_b85)
]


class UserDto(BaseModel, frozen=True):
    login_name: str = Field(serialization_alias="login")
    display_name: str = Field(serialization_alias="name")
    external_id: str | None = Field(exclude_if=lambda x: x is None)
    email: str | None = Field(exclude_if=lambda x: x is None)

    def __str__(self):
        return self.display_name


class TeamDto(BaseModel, frozen=True):
    name: str
    display_name: str = Field(serialization_alias="name")
    category_name: str | None = Field(serialization_alias="category")
    affiliation_name: str | None = Field(serialization_alias="affiliation")
    external_id: str | None = Field(exclude_if=lambda x: x is None)
    label: str | None = Field(exclude_if=lambda x: x is None)
    member_login_names: list[str] = Field(serialization_alias="members")

    def __str__(self):
        return f"{self.display_name}"


class SubmissionFileDto(BaseModel):
    filename: str
    content: Base85Bytes

    @property
    def byte_size(self) -> int:
        return len(self.content)

    def _decode(self) -> str | None:
        if hasattr(self, "_str_content"):
            return self._str_content

        try:
            content = self.content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                result = chardet.detect(self.content, should_rename_legacy=True)
                if "encoding" in result:
                    content = self.content.decode(result["encoding"])
                else:
                    content = None
            except UnicodeDecodeError:
                content = None
        self._str_content = content
        return self._str_content

    @property
    def line_count(self) -> int | None:
        content = self._decode()
        if content is None:
            return None
        lines = [line.strip() for line in content.splitlines()]
        return len([line for line in lines if line])

    def content_safe(self, default=None) -> str | None:
        content = self._decode()
        return content if content is not None else default

    @property
    def is_text_file(self):
        return self._decode() is not None


class TeamCategoryDto(BaseModel, frozen=True):
    name: str
    color: str
    visible: bool
    order: int
    self_registration: bool
    external_id: str | None = Field(
        exclude_if=lambda x: x is None,
        description="External ID of the submission, if any. Must be unique per contest.",
    )


class TestcaseResultDto(BaseModel, frozen=True):
    runtime: float
    verdict: PydanticTestcaseVerdict
    is_sample: bool = Field(serialization_alias="sample")
    test_name: str = Field(serialization_alias="name")


class ContestProblemDto(BaseModel, frozen=True):
    short_name: str = Field(description="The short_name of the problem")
    points: int
    color: str
    problem_name: str
    problem_external_id: str | None


class SubmissionDto(BaseModel, frozen=True):
    team_name: str = Field(serialization_alias="team")
    contest_key: str = Field(serialization_alias="contest")
    contest_problem_key: str = Field(serialization_alias="contest_problem")
    problem_name: str = Field(serialization_alias="problem")
    language_key: str = Field(serialization_alias="language")
    submission_time: float = Field(serialization_alias="time")
    external_id: str | None = Field(
        exclude_if=lambda x: x is None,
        description="External ID of the submission, if any. Must be unique per contest.",
    )

    verdict: PydanticVerdict | None
    case_result: list[TestcaseResultDto] = Field(serialization_alias="results")
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
    team_name: str = Field(serialization_alias="team")
    contest_key: str = Field(
        serialization_alias="contest", description="The short_name of the contest"
    )
    contest_problem_key: str | None = Field(
        serialization_alias="contest_problem",
        description="The short_name of the contest",
    )
    external_id: str | None = Field(exclude_if=lambda x: x is None)

    request_time: float = Field(serialization_alias="time")
    identifier: str
    response_to: str | None
    from_jury: bool
    body: str


class ContestDescriptionDto(BaseModel, frozen=True):
    contest_key: str = Field(serialization_alias="key")
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

    @model_validator(mode="before")
    @classmethod
    def _resolve_users_and_teams(cls, data):
        if any(not isinstance(v, UserDto) for v in data["users"].values()):
            data["users"] = {
                login_name: UserDto.model_validate(
                    {**user, "login": login_name}, by_alias=True
                )
                for login_name, user in data["users"].items()
            }
        if any(not isinstance(v, TeamDto) for v in data["teams"].values()):
            data["teams"] = {
                name: TeamDto.model_validate(
                    {**data, "name": name},
                    by_alias=True,
                )
                for name, data in data["teams"].items()
            }
        return data

    @field_serializer("users", when_used="json")
    def _users_to_map(self, users: dict[str, UserDto]):
        return {
            user.login_name: user.model_dump(exclude={"login_name"}, by_alias=True)
            for user in users.values()
        }

    @field_serializer("teams", when_used="json")
    def _teams_to_map(self, teams: dict[str, TeamDto]):
        return {
            team.name: {
                **team.model_dump(exclude={"name"}, by_alias=True),
                "members": team.member_login_names,
            }
            for team in teams.values()
        }
