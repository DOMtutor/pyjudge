import pytest

from pydomjudge.database._db import field_in_list, field_not_in_list, list_param
from pydomjudge.database._update import DbTestCase, test_case_compare_key as compare_key


def test_list_param():
    assert list_param([1, 2, 3]) == "(%s,%s,%s)"


def test_field_in_list_empty_never_matches():
    assert field_in_list("x", []) == "1 = 2"
    assert field_in_list("x", [1]) == "x IN (%s)"


def test_field_not_in_list_empty_always_matches():
    assert field_not_in_list("x", []) == "1 = 1"


def _case(name: str) -> DbTestCase:
    return DbTestCase(
        case_id=0, name=name, description=None, rank=0, input_md5="", output_md5=""
    )


@pytest.mark.parametrize(
    "names",
    [
        ["sample/1", "secret/small_1", "secret/medium_1", "secret/large_1"],
        ["sample/2", "secret/tiny_1", "secret/special_1", "secret/zzz"],
    ],
)
def test_test_case_sort_order(names: list[str]):
    cases = [_case(name) for name in reversed(names)]
    assert [c.name for c in sorted(cases, key=compare_key)] == names
