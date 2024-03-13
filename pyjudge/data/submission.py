import dataclasses
import base64
from typing import Optional, List, Dict

from pyjudge import util
from pyjudge.data.teams import TeamDto
from pyjudge.model import Verdict
from pyjudge.model.submission import TestcaseVerdict


@dataclasses.dataclass
class SubmissionFileDto:
    filename: str
    content: bytes

    @property
    def byte_size(self) -> int:
        return len(self.content)

    @property
    def line_count(self) -> Optional[int]:
        try:
            return self.content.decode("utf-8").count("\n") + 1
        except UnicodeDecodeError:
            return None

    def content_safe(self, default=None) -> str:
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return default

    @property
    def is_text_file(self):
        try:
            self.content.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False

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
    language_key: str
    submission_time: float

    verdict: Optional[Verdict]
    case_result: List[TestcaseResultDto]
    too_late: bool

    files: List[SubmissionFileDto]

    @property
    def line_count(self):
        return sum(
            file.line_count for file in self.files if file.line_count is not None
        )

    @property
    def maximum_runtime(self) -> Optional[float]:
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

    def serialize(self):
        data = {
            "team": self.team_key,
            "contest": self.contest_key,
            "problem": self.contest_problem_key,
            "language": self.language_key,
            "time": self.submission_time,
            "too_late": self.too_late,
            "results": [c.serialize() for c in self.case_result],
        }
        if self.maximum_runtime is not None:
            data["runtime"] = self.maximum_runtime
        if self.verdict is not None:
            data["verdict"] = self.verdict.serialize()
        if self.files:
            data["files"] = [file.serialize() for file in self.files]
        return data

    @staticmethod
    def parse(data):
        return SubmissionDto(
            team_key=data["team"],
            contest_key=data["contest"],
            contest_problem_key=data["problem"],
            language_key=data["language"],
            submission_time=data["time"],
            verdict=Verdict.parse(data["verdict"])
            if data.get("verdict", None) is not None
            else None,
            too_late=data["too_late"],
            files=[SubmissionFileDto.parse(file) for file in data.get("files", [])],
            case_result=[TestcaseResultDto.parse(result) for result in data["results"]],
        )


@dataclasses.dataclass
class ContestProblemDto:
    problem_key: str
    contest_problem_key: str
    points: int
    color: Optional[str]


@dataclasses.dataclass
class ClarificationDto:
    key: str
    team_key: str
    contest_key: str
    contest_problem_key: Optional[str]

    request_time: float
    response_to: Optional[str]
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
        if self.contest_problem_key is not None:
            data["contest_problem"] = self.contest_problem_key
        if self.response_to is not None:
            data["response"] = self.response_to
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
    start: Optional[float]
    end: Optional[float]

    def serialize(self):
        data = {"key": self.contest_key}
        if self.start is not None:
            data["start"] = float(self.start)
        if self.end is not None:
            data["end"] = float(self.end)
        return data

    @staticmethod
    def parse(data):
        start = data.get("start", None)
        if start is not None:
            start = float(start)
        end = data.get("end", None)
        if end is not None:
            end = float(end)
        return ContestDescriptionDto(contest_key=data["key"], start=start, end=end)


@dataclasses.dataclass
class ContestDataDto:
    description: ContestDescriptionDto
    teams: Dict[str, TeamDto]
    languages: Dict[str, str]
    problems: Dict[str, str]
    submissions: List[SubmissionDto]
    clarifications: List[ClarificationDto]

    def serialize(self):
        data = {
            "description": self.description.serialize(),
            "teams": [team.serialize() for team in self.teams.values()],
            "languages": self.languages,
            "problems": self.problems,
            "submissions": [submission.serialize() for submission in self.submissions],
            "clarifications": [
                clarification.serialize() for clarification in self.clarifications
            ],
        }
        return data

    @staticmethod
    def parse(data):
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
