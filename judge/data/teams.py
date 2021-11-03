import dataclasses
from typing import List, Optional


@dataclasses.dataclass
class UserDto(object):
    login_name: str
    display_name: str
    email: str

    def __str__(self):
        return self.display_name

    def serialize(self):
        return {
            "login": self.login_name,
            "name": self.display_name,
            "email": self.email
        }

    @staticmethod
    def parse(data):
        return UserDto(login_name=data["login"], display_name=data["name"], email=data["email"])


@dataclasses.dataclass
class TeamDto(object):
    key: str
    display_name: str
    category_name: Optional[str]
    members: List[UserDto]

    def __str__(self):
        return f"{self.key}"

    def serialize(self):
        data = {
            "key": self.key,
            "display_name": self.display_name,
            "members": [user.serialize() for user in self.members]
        }
        if self.category_name is not None:
            data["category"] = self.category_name
        return data

    @staticmethod
    def parse(data):
        return TeamDto(
            key=data["key"],
            display_name=data["display_name"],
            category_name=data.get("category", None),
            members=list(map(UserDto.parse, data["members"]))
        )
