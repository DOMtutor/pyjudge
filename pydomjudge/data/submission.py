import base64
import dataclasses

import chardet

from pydomjudge import util
from pydomjudge.data.teams import TeamDto
from pydomjudge.model import Verdict
from pydomjudge.model.submission import TestcaseVerdict
from pydomjudge.util import get_map_if_present, put_if_present


@dataclasses.dataclass
class SubmissionFileDto:
    filename: str
    content: bytes

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

    def serialize(self):
        return {
            "name": self.filename,
            "content": base64.b85encode(self.content).decode("utf-8"),
        }

    @staticmethod
    def parse(data):
        return SubmissionFileDto(
            filename=data["name"],
            content=base64.b85decode(data["content"].encode("utf-8")),
        )


@dataclasses.dataclass
class TestcaseResultDto:
    runtime: float
    verdict: TestcaseVerdict
    is_sample: bool
    test_name: str

    def serialize(self):
        return util.filter_none(
            {
                "time": self.runtime,
                "verdict": self.verdict.serialize(),
                "sample": self.is_sample,
                "name": self.test_name,
            }
        )

    @staticmethod
    def parse(data):
        return TestcaseResultDto(
            runtime=data["time"],
            verdict=TestcaseVerdict.parse(data["verdict"]),
            is_sample=data["sample"],
            test_name=data["name"],
        )


@dataclasses.dataclass
class SubmissionDto:
    team_key: str
    contest_key: str
    contest_problem_key: str
    problem_key: str
    language_key: str
    submission_time: float

    verdict: Verdict | None
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

    def serialize(self, exclude_files_if_present=False):
        data = {
            "team": self.team_key,
            "contest": self.contest_key,
            "contest_problem": self.contest_problem_key,
            "problem": self.problem_key,
            "language": self.language_key,
            "time": self.submission_time,
            "too_late": self.too_late,
            "results": [c.serialize() for c in self.case_result],
        }
        put_if_present(data, "runtime", self.maximum_runtime)
        if self.verdict is not None:
            data["verdict"] = self.verdict.serialize()
        if self.files and not exclude_files_if_present:
            data["files"] = [file.serialize() for file in self.files]
        return data

    @staticmethod
    def parse(data):
        return SubmissionDto(
            team_key=data["team"],
            contest_key=data["contest"],
            contest_problem_key=data["contest_problem"],
            problem_key=data["problem"],
            language_key=data["language"],
            submission_time=data["time"],
            verdict=get_map_if_present(data, "verdict", Verdict.parse),
            too_late=data["too_late"],
            files=[SubmissionFileDto.parse(file) for file in data.get("files", [])],
            case_result=[TestcaseResultDto.parse(result) for result in data["results"]],
        )


@dataclasses.dataclass
class ContestProblemDto:
    problem_key: str
    contest_problem_key: str
    points: int
    color: str | None


@dataclasses.dataclass
class ClarificationDto:
    key: str
    team_key: str
    contest_key: str
    contest_problem_key: str | None

    request_time: float
    response_to: str | None
    from_jury: bool
    body: str

    def serialize(self):
        data = {
            "key": self.key,
            "team": self.team_key,
            "contest": self.contest_key,
            "time": self.request_time,
            "jury": self.from_jury,
            "body": self.body,
        }
        put_if_present(data, "contest_problem", self.contest_problem_key)
        put_if_present(data, "response", self.response_to)
        return data

    @staticmethod
    def parse(data):
        response_to = data.get("response", None)
        if response_to == "None":
            response_to = None
        return ClarificationDto(
            key=data["key"],
            team_key=data["team"],
            contest_key=data["contest"],
            contest_problem_key=data.get("contest_problem", None),
            request_time=data["time"],
            response_to=response_to,
            from_jury=data["jury"],
            body=data["body"],
        )


@dataclasses.dataclass
class ContestDescriptionDto:
    contest_key: str
    start: float | None
    end: float | None

    def serialize(self):
        data: dict[str, str | float] = {"key": self.contest_key}
        put_if_present(data, "start", self.start)
        put_if_present(data, "end", self.end)
        return data

    @staticmethod
    def parse(data):
        start = get_map_if_present(data, "start", float)
        end = get_map_if_present(data, "end", float)
        return ContestDescriptionDto(contest_key=data["key"], start=start, end=end)


@dataclasses.dataclass
class ContestDataDto:
    description: ContestDescriptionDto
    teams: dict[str, TeamDto]
    languages: dict[str, str]
    problems: dict[str, str]
    submissions: list[SubmissionDto]
    clarifications: list[ClarificationDto]

    def serialize(self):
        return {
            "description": self.description.serialize(),
            "teams": [team.serialize() for team in self.teams.values()],
            "languages": self.languages,
            "problems": self.problems,
            "submissions": [submission.serialize() for submission in self.submissions],
            "clarifications": [
                clarification.serialize() for clarification in self.clarifications
            ],
        }

    @staticmethod
    def parse(data) -> "ContestDataDto":
        return ContestDataDto(
            description=ContestDescriptionDto.parse(data["description"]),
            teams={team.key: team for team in map(TeamDto.parse, data["teams"])},
            languages=data["languages"],
            problems=data["problems"],
            submissions=[
                SubmissionDto.parse(submission) for submission in data["submissions"]
            ],
            clarifications=[
                ClarificationDto.parse(clarification)
                for clarification in data["clarifications"]
            ],
        )
