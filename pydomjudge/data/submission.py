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
    users: dict[str, UserDto] = Field(init=False)
    teams: dict[str, TeamDto]
    languages: dict[str, str]
    problems: dict[str, str]
    submissions: list[SubmissionDto]
    clarifications: list[ClarificationDto]

    @model_validator(mode="before")
    @classmethod
    def _resolve_users_and_teams(cls, data):
        users = data.get("users", {})
        if users:
            parsed_users = {
                login_name: UserDto.model_validate(
                    {**user, "login": login_name}, by_alias=True
                )
                for login_name, user in users.items()
            }
            data["users"] = parsed_users
            data["teams"] = {
                key: TeamDto.model_validate(
                    {
                        **data,
                        "key": key,
                        "members": [
                            parsed_users.get(member) for member in data["members"]
                        ],
                    },
                    by_alias=True,
                )
                for key, data in data["teams"].items()
            }
        else:
            teams: dict[str, TeamDto] = data["teams"]
            users = set.union(*(set(team.members) for team in teams.values()))
            data["users"] = {user.login_name: user for user in users}
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
            team.key: {
                **team.model_dump(exclude={"key", "members"}, by_alias=True),
                "members": [user.login_name for user in team.members],
            }
            for team in teams.values()
        }
