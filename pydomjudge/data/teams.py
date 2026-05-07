from pydantic import BaseModel, Field


class UserDto(BaseModel):
    key: str = Field(serialization_alias="key")
    login_name: str = Field(serialization_alias="login")
    display_name: str = Field(serialization_alias="name")
    email: str | None = Field(exclude_if=lambda x: x is None, default=None)

    def __str__(self):
        return self.display_name

    def __hash__(self):
        return hash(self.login_name)

    def __eq__(self, other):
        return isinstance(other, UserDto) and self.key == other.key


class TeamDto(BaseModel):
    key: str = Field(serialization_alias="key")
    display_name: str = Field(serialization_alias="name")
    category_name: str | None = Field(serialization_alias="category")
    affiliation_name: str | None = Field(serialization_alias="affiliation")
    members: list[UserDto]

    def __str__(self):
        return f"{self.key}"

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return isinstance(other, TeamDto) and self.key == other.key
