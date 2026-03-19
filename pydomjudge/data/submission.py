import base64
from typing import Annotated, Union, Any

import chardet
from pydantic import (
    BaseModel,
    PlainSerializer,
    BeforeValidator,
    Field,
    field_validator,
    field_serializer,
    Tag,
    Discriminator,
    model_validator,
)

from pydomjudge.data.teams import TeamDto, UserDto
from pydomjudge.model.submission import PydanticTestcaseVerdict, PydanticVerdict


def encode_b85(v: bytes) -> str:
    return base64.b85encode(v).decode("ascii")


def decode_b85(v: str | bytes) -> bytes:
    if isinstance(v, bytes):
        return v
    return base64.b85decode(v)


Base85Bytes = Annotated[
    bytes, PlainSerializer(encode_b85, when_used="json"), BeforeValidator(decode_b85)
]


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


class TestcaseResultDto(BaseModel):
    runtime: float
    verdict: PydanticTestcaseVerdict
    is_sample: bool = Field(serialization_alias="sample")
    test_name: str = Field(serialization_alias="name")


class SubmissionDto(BaseModel):
    team_key: str = Field(serialization_alias="team")
    contest_key: str = Field(serialization_alias="contest")
    contest_problem_key: str = Field(serialization_alias="contest_problem")
    problem_key: str = Field(serialization_alias="problem")
    language_key: str = Field(serialization_alias="language")
    submission_time: float = Field(serialization_alias="time")

    verdict: PydanticVerdict | None
    case_result: list[TestcaseResultDto] = Field(serialization_alias="results")
    too_late: bool


class SubmissionWithFilesDto(SubmissionDto):
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


def submission_type(v) -> str:
    if isinstance(v, SubmissionWithFilesDto):
        return "files"
    if isinstance(v, SubmissionDto):
        return "no_files"
    assert isinstance(v, dict), v
    return "files" if "files" in v else "no_files"


PydanticSubmission = Annotated[
    Union[
        Annotated[SubmissionDto, Tag("no_files")],
        Annotated[SubmissionWithFilesDto, Tag("files")],
    ],
    Discriminator(submission_type),
]


class ContestProblemDto(BaseModel):
    problem_key: str
    contest_problem_key: str
    points: int
    color: str | None


class ClarificationDto(BaseModel):
    key: str
    team_key: str = Field(serialization_alias="team")
    contest_key: str = Field(serialization_alias="contest")
    contest_problem_key: str | None = Field(serialization_alias="contest_problem")

    request_time: float = Field(serialization_alias="time")
    response_to: str | None
    from_jury: bool
    body: str


class ContestDescriptionDto(BaseModel):
    contest_key: str = Field(serialization_alias="key")
    start: float | None
    end: float | None


class ContestDataDto(BaseModel):
    description: ContestDescriptionDto
    users: dict[str, UserDto] | None = Field(default=None, init=False)
    teams: dict[str, TeamDto]
    languages: dict[str, str]
    problems: dict[str, str]
    submissions: list[PydanticSubmission]
    clarifications: list[ClarificationDto]

    @model_validator(mode="after")
    def _populate_users(self):
        assert self.users is None
        users = set.union(*(set(team.members) for team in self.teams.values()))
        self.users = {user.login_name: user for user in users}
        return self

    @field_validator("users", mode="before")
    @classmethod
    def _users_to_dict(cls, v: dict[str, Any] | None) -> dict[str, UserDto]:
        assert isinstance(v, dict)
        if all(isinstance(u, UserDto) for u in v.values()):
            return v
        return {
            name: UserDto.model_validate({**user, "login_name": name}, by_alias=True)
            for name, user in v.items()
        }

    @field_validator("teams", mode="before")
    @classmethod
    def _teams_to_dict(cls, v: dict[str, Any], info) -> dict[str, TeamDto]:
        assert isinstance(v, dict)
        if all(isinstance(t, TeamDto) for t in v.values()):
            return v
        users = info.data.get("users")
        return {
            key: TeamDto.model_validate(
                {
                    **data,
                    "key": key,
                    "members": [users.get(member) for member in data["members"]],
                },
                by_alias=True,
            )
            for key, data in v.items()
        }

    @field_serializer("users", when_used="json")
    def _users_to_map(self, users: dict[str, UserDto]):
        return {
            user.login_name: user.model_dump(exclude={"login_name"}, by_alias=True)
            for user in users.values()
        }

    @field_serializer("teams", when_used="json")
    def _teams_to_map(self, teams: dict[str, TeamDto]):
        return {
            team.key: {
                **team.model_dump(exclude={"key", "members"}, by_alias=True),
                "members": [user.login_name for user in team.members],
            }
            for team in teams.values()
        }
