import abc
import dataclasses
import enum
import pathlib
from typing import Dict, Tuple, Collection, Optional


class ExecutableType(enum.Enum):
    Compile = "compile"
    Runscript = "run"
    Compare = "compare"


@dataclasses.dataclass
class Executable(abc.ABC):
    @staticmethod
    def get_directory_contents(directory: pathlib.Path) -> Dict[str, pathlib.Path]:
        return {path.relative_to(directory): path
                for path in directory.rglob("*") if path.is_file()
                and not path.name.endswith(".class")}  # Exclude java compilation artifacts

    key: str
    description: str
    executable_type: ExecutableType
    contents: Dict[str, pathlib.Path]  # Currently need path :(

    def make_zip(self) -> Tuple[bytes, str]:
        import io
        import zipfile
        import shutil
        import hashlib

        zip_file = io.BytesIO()
        with zipfile.ZipFile(zip_file, mode="w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=False) as z:
            for name, path in sorted(self.contents.items()):
                if path.is_file():
                    info = zipfile.ZipInfo.from_file(path, str(name))
                    if str(name) in {"build", "run"}:
                        info.external_attr |= (0o100 << 16)

                    with path.open(mode="rb") as f:
                        with z.open(info, mode="w") as d:
                            shutil.copyfileobj(f, d)

        byte_value = zip_file.getvalue()
        return byte_value, hashlib.md5(byte_value).hexdigest()

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
