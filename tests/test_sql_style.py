"""The SQL style of pydomjudge.database (see its docstring), on the source."""

import ast
import io
import pathlib
import re
import tokenize

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "src" / "pydomjudge").glob("database/*.py"))

KEYWORDS = re.compile(
    r"\b(select|from|where|and|or|not|in|is|null|as|on|join|left|outer|inner|"
    r"insert|into|values|update|set|delete|replace|group|order|by|having|limit|"
    r"distinct|exists|like|between|case|when|then|else|end|desc|asc|union|"
    r"duplicate|true|false|count|max|min|sum|md5|length|locate)\b"
)
CLAUSES = re.compile(
    r"\b(FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|"
    r"(?:LEFT (?:OUTER )?)?JOIN|ON DUPLICATE KEY UPDATE)\b"
)
STATEMENT = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE|SHOW)\b", re.I)


def _statements(path: pathlib.Path):
    """The SQL statements of a file: lists of (line, literal text) pieces."""
    tokens = tokenize.generate_tokens(io.StringIO(path.read_text()).readline)
    group: list[tuple[int, str]] = []
    depth = 0
    for token in tokens:
        if token.type == tokenize.FSTRING_START:
            depth += 1
        if depth or token.type == tokenize.STRING:
            if token.type == tokenize.FSTRING_MIDDLE:
                group.append((token.start[0], token.string))
            elif token.type == tokenize.FSTRING_END:
                depth -= 1
            elif token.type == tokenize.STRING and not token.string.endswith('"""'):
                group.append(
                    (token.start[0], re.sub(r"^\w*[\"']|[\"']$", "", token.string))
                )
            elif depth and token.string == "{":
                group.append((token.start[0], "{}"))
            continue
        if token.type in (tokenize.NL, tokenize.COMMENT):
            continue
        if group and STATEMENT.match(group[0][1]):
            yield group
        group = []


def _outside_literals(text: str) -> str:
    return re.sub(r"'(?:[^'\\]|\\.)*'", "''", text)


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_sql_style(path: pathlib.Path):
    problems = []
    for statement in _statements(path):
        lines: dict[int, str] = {}
        for line, text in statement:
            lines[line] = lines.get(line, "") + _outside_literals(text)
        sql = " ".join(lines.values())
        if match := KEYWORDS.search(sql):
            problems.append(f"{path.name}:{statement[0][0]}: lower case {match[1]!r}")
        if re.search(r"\b(FROM|JOIN|UPDATE|INTO)\s+user\b", sql):
            problems.append(f"{path.name}:{statement[0][0]}: user without backticks")
        if len(lines) > 1:
            for line, text in lines.items():
                # one clause per piece; parenthesized subqueries do not count
                outer = text
                while (inner := re.sub(r"\([^()]*\)", "", outer)) != outer:
                    outer = inner
                # a subquery that opens or closes on another line
                outer = re.sub(r"^[^(]*\)|\(.*$", "", outer)
                if len(CLAUSES.findall(outer)) > 1:
                    problems.append(
                        f"{path.name}:{line}: several clauses: {text.strip()}"
                    )
    assert not problems, "\n".join(problems)


def test_sql_only_in_the_database_package():
    database = ROOT / "src" / "pydomjudge" / "database"
    outside = [
        f"{path.relative_to(ROOT)}:{node.lineno}"
        for path in [*ROOT.glob("src/**/*.py"), *ROOT.glob("course/src/**/*.py")]
        if database not in path.parents
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute) and node.attr in ("execute", "executemany")
    ]
    assert not outside, "SQL outside pydomjudge.database: " + ", ".join(outside)
