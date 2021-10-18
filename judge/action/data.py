import dataclasses
from typing import Optional


@dataclasses.dataclass
class DbTestCase(object):
    case_id: int
    name: str
    description: Optional[str]
    rank: int
    input_md5: str
    output_md5: str

    def __str__(self):
        return f"TC({self.name})"

    def __hash__(self):
        return hash(self.case_id)

    def __eq__(self, other):
        return isinstance(other, DbTestCase) and self.case_id == other.case_id


def test_case_compare_key(case: DbTestCase):
    order = ["sample", "tiny", "small", "medium", "large", "huge", "special"]
    for i, prefix in enumerate(order):
        if case.name.startswith(prefix):
            return i, case.name[len(prefix):]
    return len(order), case.name
