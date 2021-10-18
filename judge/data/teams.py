import dataclasses
from typing import List, Optional


@dataclasses.dataclass
class UserDto(object):
    login_name: str
    display_name: str
    email: str

    def __str__(self):
        return self.display_name


@dataclasses.dataclass
class TeamDto(object):
    key: str
    display_name: str
    category_name: Optional[str]
    members: List[UserDto]

    def __str__(self):
        return f"{self.key}"
