from typing import Set

from pyjudge.db import Database


class JudgeInstance(object):
    def __init__(self, base_time: float, database: Database):
        self.base_time: float = base_time
        self.user_whitelist: Set[str] = {"python_bot"}  # TODO Not hardcoded?
        self.database = database
