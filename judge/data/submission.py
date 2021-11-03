import dataclasses
from typing import Optional, List, Dict, Collection

from judge.data.teams import TeamDto
from judge.model import Verdict


@dataclasses.dataclass
class SubmissionFileDto(object):
    filename: str
    content: str


@dataclasses.dataclass
class ParticipantSubmissionDto(object):
    team_key: str
    contest_key: str
    contest_problem_key: str
    language_key: str
    submission_time: float

    def serialize(self):
        return {
            "team": self.team_key,
            "contest": self.contest_key,
            "problem": self.contest_problem_key,
            "language": self.language_key,
            "time": self.submission_time
        }

    @staticmethod
    def parse(data):
        return ParticipantSubmissionDto(
            team_key=data["team"],
            contest_key=data["contest"],
            contest_problem_key=data["problem"],
            language_key=data["language"],
            submission_time=data["time"]
        )


@dataclasses.dataclass
class SubmissionSize(object):
    file_count: int
    line_count: int
    byte_size: int

    def serialize(self):
        return {"files": self.file_count, "lines": self.line_count, "size": self.byte_size}

    @staticmethod
    def parse(data):
        return SubmissionSize(file_count=data["files"], line_count=data["lines"], byte_size=data["size"])


@dataclasses.dataclass
class SubmissionWithVerdictDto(ParticipantSubmissionDto):
    size: SubmissionSize
    maximum_runtime: Optional[float]
    verdict: Optional[Verdict]
    too_late: bool

    def serialize(self):
        data = super(SubmissionWithVerdictDto, self).serialize()
        data.update({
            "size": self.size.serialize(),
            "too_late": self.too_late
        })
        if self.maximum_runtime is not None:
            data["runtime"] = self.maximum_runtime
        if self.verdict is not None:
            data["verdict"] = self.verdict.name
        return data

    @staticmethod
    def parse(data):
        return SubmissionWithVerdictDto(
            size=SubmissionSize.parse(data["size"]),
            maximum_runtime=data.get("runtime", None),
            verdict=Verdict.get(data["verdict"]) if data.get("verdict", None) is not None else None,
            too_late=data["too_late"],
            **ParticipantSubmissionDto.parse(data).__dict__
        )


@dataclasses.dataclass
class SubmissionWithFilesDto(ParticipantSubmissionDto):
    files: List[SubmissionFileDto]


@dataclasses.dataclass
class ContestProblemDto(object):
    problem_key: str
    contest_problem_key: str
    points: int
    color: Optional[str]


@dataclasses.dataclass
class ClarificationDto(object):
    key: str
    team_key: str
    contest_key: str
    contest_problem_key: Optional[str]

    request_time: float
    response_key: Optional[str]
    from_jury: bool
    body: str

    def serialize(self):
        data = {
            "key": self.key,
            "team": self.team_key,
            "contest": self.contest_key,
            "time": self.request_time,
            "jury": self.from_jury,
            "body": self.body
        }
        if self.contest_problem_key is not None:
            data["contest_problem"] = self.contest_problem_key
        if self.response_key is not None:
            data["response"] = self.response_key
        return data

    @staticmethod
    def parse(data):
        return ClarificationDto(
            key=data["key"],
            team_key=data["team"],
            contest_key=data["contest"],
            contest_problem_key=data.get("contest_problem", None),
            request_time=data["time"],
            response_key=data.get("response", None),
            from_jury=data["jury"],
            body=data["body"]
        )


@dataclasses.dataclass
class ContestDataDto(object):
    teams: Dict[str, TeamDto]
    languages: Dict[str, str]
    problems: Dict[str, str]
    submissions: List[SubmissionWithVerdictDto]
    clarifications: List[ClarificationDto]

    def serialize(self):
        return {
            "teams": [team.serialize() for team in self.teams.values()],
            "languages": self.languages,
            "problems": self.problems,
            "submissions": [submission.serialize() for submission in self.submissions],
            "clarifications": [clarification.serialize() for clarification in self.clarifications]
        }

    @staticmethod
    def parse(data):
        return ContestDataDto(
            teams={team.key: team for team in map(TeamDto.parse, data["teams"])},
            languages=data["languages"],
            problems=data["problems"],
            submissions=[SubmissionWithVerdictDto.parse(submission) for submission in data["submissions"]],
            clarifications=[ClarificationDto.parse(clarification) for clarification in data["clarifications"]]
        )
