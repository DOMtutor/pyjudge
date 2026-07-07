import abc
import enum
import pathlib
from dataclasses import dataclass
from typing import Collection


class ExecutableType(enum.StrEnum):
    Compile = "compile"
    Runscript = "run"
    Compare = "compare"


class FileData(abc.ABC):
    @abc.abstractmethod
    def open(self):
        pass

    @property
    @abc.abstractmethod
    def relative_path(self) -> list[str]:
        pass

    def __lt__(self, other):
        return self.relative_path < other.relative_path


@dataclass(frozen=True)
class PathFile(FileData):
    content: pathlib.Path
    path_components: list[str]

    def __post_init__(self):
        assert self.path_components and all(
            component for component in self.path_components
        )

    @staticmethod
    def from_path(file: pathlib.Path, base_directory: pathlib.Path) -> "PathFile":
        return PathFile(file, list(map(str, file.relative_to(base_directory).parts)))

    def open(self):
        return self.content.open(mode="rb")

    @property
    def relative_path(self) -> list[str]:
        return self.path_components


@dataclass(frozen=True)
class Executable:
    @staticmethod
    def get_directory_contents(directory: pathlib.Path) -> Collection[PathFile]:
        return [
            PathFile.from_path(path, directory)
            for path in directory.glob("**/*")
            if path.is_file() and not path.name.endswith(".class")
        ]  # Exclude java compilation artifacts

    key: str
    description: str
    executable_type: ExecutableType
    contents: Collection[FileData]

    def __str__(self):
        return f"{self.key}({self.executable_type})"


@dataclass(frozen=True)
class Language:
    key: str
    name: str
    time_factor: float
    extensions: Collection[str]
    entry_point_description: str | None
    entry_point_required: bool
    compile_script: Executable

    def __str__(self):
        return f"{self.name}"
