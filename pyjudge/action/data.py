import dataclasses
import logging
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
    order = ["sample", "secret/tiny", "secret/small", "secret/medium", "secret/large", "secret/huge",
             "secret/xlarge", "secret/special", "secret/sparse"]
    for i, prefix in enumerate(order):
        if case.name.startswith(prefix):
            return i, case.name[len(prefix):]
    if case.description is None:
        logging.debug("Case %s name does not start with regular key", case)
    return len(order), case.name
