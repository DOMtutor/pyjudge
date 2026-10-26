"""Plagiarism candidates from the grading layout, a review file per problem
with a verdict per pair and side, and what the course needs from the verdicts.

Needs the ``plagiarism`` extra (copydetect, rapidfuzz, pygments).

1. ``find_plagiarism`` turns the submissions of the layout into units (one per
   submission, near-identical ones of a team collapsed), runs the detectors
   per problem (copydetect on the code, then the comments) and writes a report
   directory: copydetect's report per problem, the pairs, and an index page
   with the cases (connected components of flagged team pairs, for
   navigation) and the team pairs flagged on several problems.
2. It updates the review file of each problem: one row per flagged team pair,
   with a verdict for each side. Rows survive re-runs; ``review`` says what
   the reviewer has to look at (``new``, ``re-review`` when the evidence
   changed, ``dropped`` when the pair is no longer flagged).
3. ``read_reviews`` refuses incomplete files; ``findings`` (one per team and
   problem, the most severe reported kind) and ``hearings`` (per team, only
   the pairs where its own side is reported) are what feedback and forms use.
"""

import csv
import dataclasses
import hashlib
import html
import io
import itertools
import json
import logging
import pathlib
import re
import shutil
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from typing import Protocol

import rapidfuzz
import rapidfuzz.utils
from copydetect import CodeFingerprint, CopyDetector, compare_files
from pygments import token
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound
from rapidfuzz.distance import Levenshtein

from pydomjudge_course.layout import Evaluation, SubmissionRecord

log = logging.getLogger(__name__)

TeamPairKey = tuple[str, str]


# Verdict kinds


# Name -> severity. 0 is not reported; a reported side gets a finding and a
# hearing, and the most severe of a team's sides wins. A course passes its own
# mapping to read_reviews, hearings and findings.
DEFAULT_KINDS: Mapping[str, int] = {
    "none": 0,
    # the similarity is acknowledged
    "cited": 0,
    # others copied from this side
    "source": 0,
    "uncited": 1,
    "copied": 2,
}


# Units


@dataclasses.dataclass(frozen=True)
class Unit:
    """One submission of a team to a problem, standing for its near-identical
    submissions (``submissions``, the first one is the one shown)."""

    problem: str
    team: str
    submissions: tuple[str, ...]
    folders: tuple[str, ...]
    """Of the submissions, relative to the layout directory."""
    files: tuple[str, ...]
    language: str
    time: float
    sources: tuple[tuple[str, str], ...] = dataclasses.field(repr=False, compare=False)
    """(file name, text) of the first submission, in name order."""

    @property
    def text(self) -> str:
        return "\n".join(text for _, text in self.sources)

    @property
    def name(self) -> str:
        """A file name for the corpus, with the suffix of the first file."""
        suffix = pathlib.PurePosixPath(self.files[0]).suffix if self.files else ""
        return f"{int(self.time):d}_{self.submissions[0]}{suffix}"

    def ref(self) -> dict:
        return {
            "team": self.team,
            "submissions": list(self.submissions),
            "folders": list(self.folders),
        }


def all_sources(submission: SubmissionRecord) -> bool:
    """Every submission with text files, also those after the cutoff."""
    return submission.source and bool(submission.files)


def _read_sources(directory: pathlib.Path, record: SubmissionRecord):
    return tuple(
        (
            name,
            (directory / record.folder / name)
            .read_bytes()
            .decode("utf-8", errors="replace"),
        )
        for name in sorted(record.files)
    )


def units_from_layout(
    evaluation: Evaluation,
    directory: pathlib.Path,
    *,
    include: Callable[[SubmissionRecord], bool] = all_sources,
    collapse: float = 0.95,
) -> dict[str, list[Unit]]:
    """Units by problem. A team's submission whose text is at least
    ``collapse`` similar (normalized Levenshtein) to an earlier unit of the
    team joins that unit."""
    units: dict[str, list[Unit]] = defaultdict(list)
    for team, record in sorted(evaluation.teams.items()):
        for problem, entry in sorted(record.problems.items()):
            groups: list[tuple[SubmissionRecord, tuple, list[SubmissionRecord]]] = []
            for submission in sorted(entry.submissions, key=lambda s: s.time):
                if not include(submission):
                    continue
                sources = _read_sources(directory, submission)
                text = "\n".join(t for _, t in sources)
                for _first, first_sources, members in groups:
                    first_text = "\n".join(t for _, t in first_sources)
                    if Levenshtein.normalized_similarity(first_text, text) >= collapse:
                        members.append(submission)
                        break
                else:
                    groups.append((submission, sources, [submission]))
            for first, sources, members in groups:
                units[problem].append(
                    Unit(
                        problem=problem,
                        team=team,
                        submissions=tuple(m.id for m in members),
                        folders=tuple(m.folder for m in members),
                        files=tuple(sorted(first.files)),
                        language=first.language,
                        time=first.time,
                        sources=sources,
                    )
                )
    return dict(units)


# Detectors


@dataclasses.dataclass(frozen=True)
class PairScore:
    detector: str
    a: Unit
    b: Unit
    """Of different teams."""
    score: float
    """In [0, 1]."""
    tokens: int
    flagged: bool

    @property
    def teams(self) -> TeamPairKey:
        first, second = sorted((self.a.team, self.b.team))
        return first, second

    def to_json(self) -> dict:
        return {
            "detector": self.detector,
            "score": self.score,
            "tokens": self.tokens,
            "flagged": self.flagged,
            "a": self.a.ref(),
            "b": self.b.ref(),
        }


class Detector(Protocol):
    @property
    def name(self) -> str: ...

    def detect(
        self,
        units: Sequence[Unit],
        boilerplate: Sequence[pathlib.Path],
        reference: Sequence[Unit] = (),
        *,
        skip: Collection[TeamPairKey] = (),
        workspace: pathlib.Path,
    ) -> list[PairScore]:
        """Scores of unit pairs of different teams of one problem, flagged or
        worth listing; team pairs in skip need no score. The workspace is a
        fresh folder of this detector and problem, for files and reports."""
        ...


def _no_reference(reference: Sequence[Unit]) -> None:
    if reference:
        raise NotImplementedError("A reference corpus is not supported yet")


@dataclasses.dataclass(frozen=True)
class CodeDetector:
    """copydetect on the problem's units, one folder per team (ignore_leaf
    keeps a team's units apart), with copydetect's report as report.html.
    A pair is flagged above ``threshold`` (of the more copied side) and
    listed above ``list_threshold``."""

    name: str = "code"
    noise: int = 30
    guarantee: int = 40
    threshold: float = 0.6
    list_threshold: float = 0.4

    def detect(
        self,
        units: Sequence[Unit],
        boilerplate: Sequence[pathlib.Path],
        reference: Sequence[Unit] = (),
        *,
        skip: Collection[TeamPairKey] = (),
        workspace: pathlib.Path,
    ) -> list[PairScore]:
        _no_reference(reference)
        if len({unit.team for unit in units}) < 2:
            return []
        by_path: dict[str, Unit] = {}
        team_directories = []
        for team, team_units in itertools.groupby(
            sorted(units, key=lambda u: u.team), key=lambda u: u.team
        ):
            team_directory = workspace / "corpus" / team
            team_directory.mkdir(parents=True)
            team_directories.append(str(team_directory))
            for unit in team_units:
                path = team_directory / unit.name
                path.write_text(unit.text, encoding="utf-8")
                by_path[str(path)] = unit
        detector = CopyDetector(
            test_dirs=team_directories,
            noise_t=self.noise,
            guarantee_t=self.guarantee,
            display_t=self.list_threshold,
            ignore_leaf=True,
            autoopen=False,
            silent=True,
            out_file=str(workspace / "report.html"),
        )
        for path in boilerplate:
            detector.add_file(str(path), type="boilerplate")
        detector.run()
        scores = []
        for (
            test_sim,
            ref_sim,
            test_f,
            ref_f,
            _,
            _,
            overlap,
        ) in detector.get_copied_code_list():
            a, b = by_path[test_f], by_path[ref_f]
            score = float(max(test_sim, ref_sim))
            scores.append(
                PairScore(
                    detector=self.name,
                    a=a,
                    b=b,
                    score=score,
                    tokens=int(overlap),
                    flagged=score > self.threshold,
                )
            )
        detector.generate_html_report()
        return scores


def _comments(name: str, text: str) -> str:
    try:
        lexer = get_lexer_for_filename(name)
    except ClassNotFound:
        return ""
    return "\n".join(
        value
        for kind, value in lexer.get_tokens(text)
        if (kind in token.Comment or kind in token.String.Doc)
        and kind not in token.Comment.Preproc
    )


@dataclasses.dataclass(frozen=True)
class CommentDetector:
    """Similar comments (and docstrings): the units' comments, normalized,
    if longer than ``min_chars``. A pair with at least ``min_tokens``
    overlapping tokens is flagged with more than max(``token_threshold``,
    half of the shorter comments) tokens or a partial ratio above
    ``ratio_threshold``. Once a team pair is flagged, its other units are not
    compared."""

    name: str = "comments"
    min_chars: int = 60
    k: int = 30
    min_tokens: int = 30
    token_threshold: int = 80
    ratio_threshold: float = 80

    def detect(
        self,
        units: Sequence[Unit],
        boilerplate: Sequence[pathlib.Path],
        reference: Sequence[Unit] = (),
        *,
        skip: Collection[TeamPairKey] = (),
        workspace: pathlib.Path,
    ) -> list[PairScore]:
        _no_reference(reference)
        comments: dict[Unit, str] = {}
        for unit in sorted(units, key=lambda u: (u.team, u.submissions)):
            content = " ".join(
                rapidfuzz.utils.default_process(_comments(name, text))
                for name, text in unit.sources
            )
            content = re.sub(r"\s+", " ", content).strip()
            if len(content) > self.min_chars:
                comments[unit] = content
        fingerprints = {
            unit: CodeFingerprint(
                file=unit.name,
                k=self.k,
                win_size=1,
                fp=io.StringIO(content),
                language="output",
            )
            for unit, content in comments.items()
        }
        done = set(skip)
        scores = []
        for a, b in itertools.combinations(comments, 2):
            pair = PairScore(self.name, a, b, 0, 0, False).teams
            if a.team == b.team or pair in done:
                continue
            tokens, _, _ = compare_files(fingerprints[a], fingerprints[b])
            if tokens < self.min_tokens:
                continue
            ratio = rapidfuzz.fuzz.partial_ratio(comments[a], comments[b])
            flagged = (
                tokens
                > max(
                    self.token_threshold, min(len(comments[a]), len(comments[b])) // 2
                )
                or ratio > self.ratio_threshold
            )
            if flagged:
                done.add(pair)
                scores.append(
                    PairScore(self.name, a, b, ratio / 100, int(tokens), True)
                )
        return scores


DEFAULT_DETECTORS: tuple[Detector, ...] = (CodeDetector(), CommentDetector())


# Team pairs and cases


@dataclasses.dataclass(frozen=True)
class TeamPair:
    problem: str
    a: str
    b: str
    """a < b."""
    scores: tuple[PairScore, ...]
    """The strongest score per detector."""

    @property
    def flagged(self) -> bool:
        return any(score.flagged for score in self.scores)

    @property
    def score(self) -> float:
        flagged = [s.score for s in self.scores if s.flagged]
        return max(flagged or [s.score for s in self.scores])

    @property
    def detectors(self) -> list[str]:
        return [s.detector for s in self.scores if s.flagged]

    @property
    def evidence(self) -> str:
        """What a reviewer looked at: the flagged detectors, their units and a
        score bucket of 0.1. A change asks for a re-review."""
        parts = sorted(
            f"{s.detector}:{','.join(s.a.submissions)}:{','.join(s.b.submissions)}"
            if s.a.team == self.a
            else f"{s.detector}:{','.join(s.b.submissions)}:{','.join(s.a.submissions)}"
            for s in self.scores
            if s.flagged
        )
        parts.append(f"bucket:{int(self.score * 10)}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]

    def to_json(self) -> dict:
        return {
            "a": self.a,
            "b": self.b,
            "flagged": self.flagged,
            "scores": [score.to_json() for score in self.scores],
        }


def find_pairs(
    problem: str,
    units: Sequence[Unit],
    workspace: pathlib.Path,
    *,
    detectors: Sequence[Detector] = DEFAULT_DETECTORS,
    boilerplate: Sequence[pathlib.Path] = (),
) -> list[TeamPair]:
    """The team pairs of a problem with a listed or flagged score, by teams.
    Each detector skips the team pairs flagged by the ones before."""
    strongest: dict[TeamPairKey, dict[str, PairScore]] = defaultdict(dict)
    flagged: set[TeamPairKey] = set()
    for detector in detectors:
        target = workspace / detector.name
        target.mkdir(parents=True)
        for score in detector.detect(
            units, boilerplate, skip=frozenset(flagged), workspace=target
        ):
            if score.a.team == score.b.team:
                continue
            current = strongest[score.teams].get(detector.name)
            if current is None or (score.flagged, score.score) > (
                current.flagged,
                current.score,
            ):
                strongest[score.teams][detector.name] = score
        flagged |= {
            pair
            for pair, by_detector in strongest.items()
            if any(s.flagged for s in by_detector.values())
        }
    order = [detector.name for detector in detectors]
    return [
        TeamPair(
            problem,
            a,
            b,
            tuple(sorted(by_detector.values(), key=lambda s: order.index(s.detector))),
        )
        for (a, b), by_detector in sorted(strongest.items())
    ]


@dataclasses.dataclass(frozen=True)
class Case:
    """Teams connected by flagged pairs of one problem; for navigation."""

    problem: str
    id: str
    teams: tuple[str, ...]
    pairs: tuple[TeamPair, ...]


def find_cases(pairs: Iterable[TeamPair]) -> list[Case]:
    flagged = [pair for pair in pairs if pair.flagged]
    parent: dict[str, str] = {}

    def find(team: str) -> str:
        while parent.setdefault(team, team) != team:
            parent[team] = parent[parent[team]]
            team = parent[team]
        return team

    for pair in flagged:
        parent[find(pair.a)] = find(pair.b)
    components: dict[str, list[TeamPair]] = defaultdict(list)
    for pair in flagged:
        components[find(pair.a)].append(pair)
    groups = sorted(
        (
            tuple(sorted({team for pair in group for team in (pair.a, pair.b)})),
            tuple(group),
        )
        for group in components.values()
    )
    return [
        Case(problem=group[0].problem, id=f"C{number:02d}", teams=teams, pairs=group)
        for number, (teams, group) in enumerate(groups, start=1)
    ]


# Review files

REVIEW_COLUMNS = [
    "case",
    "a",
    "b",
    "score",
    "detectors",
    "evidence",
    "verdict_a",
    "verdict_b",
    "note",
    "review",
]


def update_review(path: pathlib.Path, pairs: Sequence[TeamPair]) -> None:
    """Rows of the flagged pairs; verdicts and notes of earlier runs stay.
    review: new (a new pair), re-review (its evidence changed), dropped (no
    longer flagged, kept while it has a verdict or note). The reviewer clears
    review when done."""
    existing: dict[TeamPairKey, dict[str, str]] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["a"], row["b"]] = row
    case_of = {
        (pair.a, pair.b): case.id for case in find_cases(pairs) for pair in case.pairs
    }
    rows = []
    for pair in pairs:
        if not pair.flagged:
            continue
        old = existing.pop((pair.a, pair.b), None)
        row = {column: "" for column in REVIEW_COLUMNS} if old is None else dict(old)
        if old is None:
            row["review"] = "new"
        elif old.get("evidence") != pair.evidence and old.get("review") != "new":
            row["review"] = "re-review"
        elif old.get("review") == "dropped":
            row["review"] = "re-review"
        row.update(
            case=case_of[pair.a, pair.b],
            a=pair.a,
            b=pair.b,
            score=f"{pair.score:.2f}",
            detectors="+".join(pair.detectors),
            evidence=pair.evidence,
        )
        rows.append(row)
    for row in existing.values():
        if row.get("verdict_a") or row.get("verdict_b") or row.get("note"):
            rows.append({**row, "case": "", "review": "dropped"})
    rows.sort(key=lambda r: (r["case"] == "", r["case"], r["a"], r["b"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class ReviewError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class PairVerdict:
    problem: str
    a: str
    b: str
    verdict_a: str
    verdict_b: str
    note: str


def read_reviews(
    review_files: Mapping[str, pathlib.Path], kinds: Mapping[str, int] = DEFAULT_KINDS
) -> list[PairVerdict]:
    """The verdicts of the review files (problem -> file). Every row needs a
    known verdict for both sides and no open review marker."""
    if any(severity < 0 for severity in kinds.values()):
        raise ValueError(f"Verdict severities must not be negative: {dict(kinds)}")
    verdicts = []
    problems = []
    for problem, path in sorted(review_files.items()):
        with path.open(newline="", encoding="utf-8") as f:
            for number, row in enumerate(csv.DictReader(f), start=2):
                where = f"{path.name}:{number}"
                if row.get("review"):
                    problems.append(f"{where}: review is {row['review']!r}")
                for side in ("verdict_a", "verdict_b"):
                    if row.get(side) not in kinds:
                        problems.append(
                            f"{where}: {side} must be one of {', '.join(kinds)}"
                        )
                verdicts.append(
                    PairVerdict(
                        problem,
                        row["a"],
                        row["b"],
                        row.get("verdict_a") or "",
                        row.get("verdict_b") or "",
                        row.get("note") or "",
                    )
                )
    if problems:
        raise ReviewError("Incomplete plagiarism review:\n" + "\n".join(problems))
    return verdicts


@dataclasses.dataclass(frozen=True)
class Hearing:
    """A pair in which the team's own side has a reported kind."""

    team: str
    problem: str
    partner: str
    verdict: str
    partner_verdict: str
    note: str


def hearings(
    verdicts: Iterable[PairVerdict], kinds: Mapping[str, int] = DEFAULT_KINDS
) -> dict[str, list[Hearing]]:
    """By team; only the pairs where its own side is reported."""
    result: dict[str, list[Hearing]] = defaultdict(list)
    for v in verdicts:
        for team, partner, own, other in (
            (v.a, v.b, v.verdict_a, v.verdict_b),
            (v.b, v.a, v.verdict_b, v.verdict_a),
        ):
            if kinds[own] > 0:
                result[team].append(
                    Hearing(team, v.problem, partner, own, other, v.note)
                )
    return {
        team: sorted(items, key=lambda h: (h.problem, h.partner))
        for team, items in sorted(result.items())
    }


@dataclasses.dataclass(frozen=True)
class Finding:
    """A team's result for a problem: the most severe reported kind of its
    sides, and the partners of those pairs."""

    team: str
    problem: str
    verdict: str
    partners: tuple[str, ...]


def findings(
    verdicts: Iterable[PairVerdict], kinds: Mapping[str, int] = DEFAULT_KINDS
) -> list[Finding]:
    grouped: dict[tuple[str, str], list[Hearing]] = defaultdict(list)
    for items in hearings(verdicts, kinds).values():
        for hearing in items:
            grouped[hearing.team, hearing.problem].append(hearing)
    return [
        Finding(
            team,
            problem,
            max((h.verdict for h in items), key=kinds.__getitem__),
            tuple(sorted({h.partner for h in items})),
        )
        for (team, problem), items in sorted(grouped.items())
    ]


def write_findings(items: Iterable[Finding], path: pathlib.Path) -> None:
    """plagiarism.csv: team, problem, verdict, partners (separated by ;)."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["team", "problem", "verdict", "partners"])
        for item in items:
            writer.writerow(
                [item.team, item.problem, item.verdict, ";".join(item.partners)]
            )


def write_evidence(
    team_hearings: Mapping[str, Sequence[Hearing]],
    report_directory: pathlib.Path,
    layout_directory: pathlib.Path,
    target: pathlib.Path,
    evaluation: Evaluation,
) -> None:
    """Per team, the submissions of its hearings only:
    target/<team>/<problem>/<partner>/{own,partner}/<submission folder>, as
    links into the layout. Replaces target.

    A pair that this run did not flag (a dropped row whose verdict was kept)
    gets all submissions of both teams to the problem, with a warning."""
    if target.exists():
        shutil.rmtree(target)
    for team, items in team_hearings.items():
        for hearing in items:
            pair = _stored_pair(
                report_directory, hearing.problem, team, hearing.partner
            )
            sides = {
                owner: _flagged_folders(pair, owner) if pair else set()
                for owner in (team, hearing.partner)
            }
            if not all(sides.values()):
                log.warning(
                    "%s: the pair %s / %s is not flagged in this run; its evidence "
                    "is every submission of both teams",
                    hearing.problem,
                    *sorted((team, hearing.partner)),
                )
                sides = {
                    owner: _all_folders(evaluation, owner, hearing.problem)
                    for owner in sides
                }
            folder = target / team / hearing.problem / hearing.partner
            for side, owner in (("own", team), ("partner", hearing.partner)):
                for relative in sorted(sides[owner]):
                    link = folder / side / pathlib.PurePosixPath(relative).name
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to((layout_directory / relative).resolve())


def _flagged_folders(pair: dict, owner: str) -> set[str]:
    return {
        folder
        for score in pair["scores"]
        if score["flagged"]
        for unit in (score["a"], score["b"])
        if unit["team"] == owner
        for folder in unit["folders"]
    }


def _all_folders(evaluation: Evaluation, team: str, problem: str) -> set[str]:
    record = evaluation.teams.get(team)
    entry = record.problems.get(problem) if record else None
    return {s.folder for s in entry.submissions} if entry else set()


def _stored_pair(
    report_directory: pathlib.Path, problem: str, x: str, y: str
) -> dict | None:
    a, b = sorted((x, y))
    path = report_directory / problem / "pairs.json"
    if not path.exists():
        return None
    for pair in json.loads(path.read_text()):
        if pair["a"] == a and pair["b"] == b:
            return pair
    return None


# Running it


@dataclasses.dataclass(frozen=True)
class RepeatedPair:
    """A team pair listed on several problems."""

    a: str
    b: str
    flagged: tuple[str, ...]
    listed: tuple[str, ...]
    """Problems with a listed but not flagged score."""
    total: float


def repeated_pairs(
    pairs: Mapping[str, Sequence[TeamPair]], *, min_problems: int = 3
) -> list[RepeatedPair]:
    """Team pairs flagged on two or more problems, or listed (flagged or with a
    weaker score) on at least min_problems; most problems first."""
    by_teams: dict[TeamPairKey, list[TeamPair]] = defaultdict(list)
    for items in pairs.values():
        for pair in items:
            by_teams[pair.a, pair.b].append(pair)
    result = []
    for (a, b), items in by_teams.items():
        flagged = tuple(sorted(p.problem for p in items if p.flagged))
        listed = tuple(sorted(p.problem for p in items if not p.flagged))
        if len(flagged) >= 2 or len(items) >= min_problems:
            result.append(
                RepeatedPair(a, b, flagged, listed, sum(p.score for p in items))
            )
    return sorted(
        result, key=lambda r: (-len(r.flagged) - len(r.listed), -r.total, r.a, r.b)
    )


def find_plagiarism(
    evaluation: Evaluation,
    layout_directory: pathlib.Path,
    *,
    report_directory: pathlib.Path,
    review_directory: pathlib.Path,
    include: Callable[[SubmissionRecord], bool] = all_sources,
    collapse: float = 0.95,
    detectors: Sequence[Detector] = DEFAULT_DETECTORS,
    boilerplate: Mapping[str, Sequence[pathlib.Path]] | None = None,
    min_problems: int = 3,
) -> dict[str, list[TeamPair]]:
    """Runs the detectors per problem, rebuilds report_directory (copydetect's
    report and pairs.json per problem, index.html) and updates
    review_directory/<problem>.csv. Returns the team pairs by problem."""
    units = units_from_layout(
        evaluation, layout_directory, include=include, collapse=collapse
    )
    if report_directory.exists():
        shutil.rmtree(report_directory)
    report_directory.mkdir(parents=True)
    pairs: dict[str, list[TeamPair]] = {}
    for problem, problem_units in sorted(units.items()):
        log.info("Plagiarism check of %s: %d units", problem, len(problem_units))
        workspace = report_directory / problem
        pairs[problem] = find_pairs(
            problem,
            problem_units,
            workspace,
            detectors=detectors,
            boilerplate=(boilerplate or {}).get(problem, ()),
        )
        (workspace / "pairs.json").write_text(
            json.dumps([pair.to_json() for pair in pairs[problem]], indent=1)
        )
        update_review(review_directory / f"{problem}.csv", pairs[problem])
    # Problems without units this time: their rows are dropped
    for path in sorted(review_directory.glob("*.csv")):
        if path.stem not in units:
            update_review(path, [])
    write_index(
        report_directory / "index.html",
        pairs,
        repeated_pairs(pairs, min_problems=min_problems),
        detectors=[detector.name for detector in detectors],
    )
    return pairs


def write_index(
    path: pathlib.Path,
    pairs: Mapping[str, Sequence[TeamPair]],
    repeated: Sequence[RepeatedPair],
    *,
    detectors: Sequence[str],
) -> None:
    e = html.escape
    parts = [
        "<!doctype html><meta charset='utf-8'><title>Plagiarism</title>",
        "<style>body{font-family:sans-serif}table{border-collapse:collapse}"
        "td,th{border:1px solid #ccc;padding:2px 6px}</style>",
        "<h1>Plagiarism</h1>",
    ]
    for problem, items in sorted(pairs.items()):
        parts.append(f"<h2>{e(problem)}</h2><p>")
        for detector in detectors:
            report = path.parent / problem / detector / "report.html"
            if report.exists():
                href = e(f"{problem}/{detector}/report.html", quote=True)
                parts.append(f"<a href='{href}'>{e(detector)} report</a> ")
        parts.append("</p>")
        cases = find_cases(items)
        if not cases:
            parts.append("<p>No flagged pairs.</p>")
        for case in cases:
            parts.append(
                f"<h3>{e(case.id)}: {e(', '.join(case.teams))}</h3>"
                "<table><tr><th>a</th><th>b</th><th>score</th>"
                "<th>detectors</th><th>submissions (a / b)</th></tr>"
            )
            for pair in case.pairs:
                units = "; ".join(
                    f"{s.detector}: {','.join(s.a.submissions)} / "
                    f"{','.join(s.b.submissions)}"
                    for s in pair.scores
                    if s.flagged
                )
                parts.append(
                    f"<tr><td>{e(pair.a)}</td><td>{e(pair.b)}</td>"
                    f"<td>{pair.score:.2f}</td><td>{e('+'.join(pair.detectors))}</td>"
                    f"<td>{e(units)}</td></tr>"
                )
            parts.append("</table>")
    parts.append("<h2>Team pairs on several problems</h2>")
    if repeated:
        parts.append(
            "<table><tr><th>a</th><th>b</th><th>flagged</th><th>listed</th>"
            "<th>total score</th></tr>"
        )
        for item in repeated:
            parts.append(
                f"<tr><td>{e(item.a)}</td><td>{e(item.b)}</td>"
                f"<td>{e(', '.join(item.flagged))}</td>"
                f"<td>{e(', '.join(item.listed))}</td><td>{item.total:.2f}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p>None.</p>")
    path.write_text("\n".join(parts), encoding="utf-8")
