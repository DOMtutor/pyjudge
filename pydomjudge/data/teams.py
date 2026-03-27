from pydantic import BaseModel, Field


class UserDto(BaseModel):
    login_name: str = Field(alias="login")
    display_name: str = Field(alias="name")
    email: str | None = Field(exclude_if=lambda x: x is None, default=None)

    def __str__(self):
        return self.display_name

    def __hash__(self):
        return hash(self.login_name)

    def __eq__(self, other):
        return isinstance(other, UserDto) and self.login_name == other.login_name


class TeamDto(BaseModel):
    key: str
    display_name: str = Field(alias="name")
    category_name: str | None = Field(alias="category")
    members: list[UserDto]

    def __str__(self):
        return f"{self.key}"

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return isinstance(other, UserDto) and self.key == other.key
