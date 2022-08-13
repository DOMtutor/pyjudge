import abc
import dataclasses
import enum
import io
import pathlib
import typing
from typing import Dict, Tuple, Collection, Optional


class ExecutableType(enum.Enum):
    Compile = "compile"
    Runscript = "run"
    Compare = "compare"

    def __str__(self):
        return self.value


@dataclasses.dataclass
class Executable(abc.ABC):
    @staticmethod
    def get_directory_contents(directory: pathlib.Path) -> Dict[str, pathlib.Path]:
        return {str(path.relative_to(directory)): path
                for path in directory.rglob("*") if path.is_file()
                and not path.name.endswith(".class")}  # Exclude java compilation artifacts

    key: str
    description: str
    executable_type: ExecutableType
    contents: Dict[str, typing.Any]

    def __str__(self):
        return f"{self.key}({self.executable_type})"


@dataclasses.dataclass
class Language(object):
    key: str
    name: str
    time_factor: float
    extensions: Collection[str]
    entry_point_description: Optional[str]
    entry_point_required: bool
    compile_script: Executable

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return isinstance(other, Language) and self.key == other.key

    def __str__(self):
        return f"{self.name}"
