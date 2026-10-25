"""The watcher daemon (tools/watcher, a workspace member)."""

import pytest

watcher = pytest.importorskip("domjudge_watcher", reason="needs uv sync --all-packages")


def test_truncate_keeps_lines_and_drops_quotes():
    text = "first line\n> quoted reply\nsecond line\n\nthird"
    assert watcher.truncate_text(text) == "first line\nsecond line\nthird"


def test_truncate_limits_lines_and_length():
    lines = "\n".join(f"line {i}" for i in range(10))
    assert watcher.truncate_text(lines, line_count=2) == "line 0\nline 1..."
    assert watcher.truncate_text("x" * 300, total_length=10) == "x" * 10 + "..."


def test_event_type_by_name():
    assert (
        watcher.EventType.get_by_name("Clarification")
        is watcher.EventType.Clarification
    )
    assert watcher.EventType.get_by_name("nothing") is None
