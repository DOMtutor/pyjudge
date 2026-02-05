import abc
import dataclasses
import enum
import hashlib
import pathlib
from typing import Tuple, Collection, Optional


class ExecutableType(enum.Enum):
    Compile = "compile"
    Runscript = "run"
    Compare = "compare"

    def __str__(self):
        return self.value


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


@dataclasses.dataclass
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


@dataclasses.dataclass
class Executable(abc.ABC):
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

    def file_info(self) -> list[dict]:
        file_info = []
        for file_data in self.contents:
            with file_data.open() as f:
                file_content = f.read()

            filename = file_data.relative_path[-1]
            file_hash = hashlib.md5(file_content).hexdigest()
            is_executable = 1 if filename in ('build', 'run') else 0

            file_info.append({
                'filename': filename,
                'content': file_content,
                'hash': file_hash,
                'is_executable': is_executable,
            })

        file_info.sort(key=lambda x: x['filename'])
        return file_info

    # def make_zip(self) -> Tuple[bytes, str]:
    #     import io
    #     import zipfile
    #     import shutil
    #     import hashlib
    #
    #     zip_file = io.BytesIO()
    #     with zipfile.ZipFile(
    #         zip_file, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False
    #     ) as z:
    #         for file in sorted(self.contents):
    #             info = zipfile.ZipInfo(filename="/".join(file.relative_path))
    #             info.external_attr = 0o100444 << 16
    #             if file.relative_path[-1] in {"build", "run"}:
    #                 info.external_attr |= 0o111 << 16
    #
    #             with file.open() as f:
    #                 with z.open(info, mode="w") as d:
    #                     shutil.copyfileobj(f, d)
    #
    #     byte_value = zip_file.getvalue()
    #     return byte_value, hashlib.md5(byte_value).hexdigest()

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
