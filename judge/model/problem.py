import abc
import dataclasses
from typing import Optional, Tuple, Collection

from .submission import JuryProblemSubmission
from .language import Executable
from .util import get_md5


class ProblemTestCase(abc.ABC):
    @abc.abstractmethod
    def input(self):
        pass

    def load_input(self) -> bytes:
        with open(self.input(), mode="rb") as f:
            return f.read()

    @property
    def input_md5(self) -> str:
        return get_md5(self.input())

    @abc.abstractmethod
    def output(self):
        pass

    def load_output(self) -> bytes:
        with open(self.output(), mode="rb") as f:
            return f.read()

    @property
    def output_md5(self) -> str:
        return get_md5(self.output())

    @abc.abstractmethod
    def is_sample(self):
        pass

    @abc.abstractmethod
    def get_unique_name(self) -> str:
        pass

    @abc.abstractmethod
    def load_image(self) -> Optional[bytes]:
        pass

    @property
    @abc.abstractmethod
    def image_extension(self) -> str:
        pass

    @property
    def description(self) -> Optional[str]:
        return None

    def load_image_with_thumbnail(self) -> Optional[Tuple[bytes, bytes]]:
        image = self.load_image()
        if image is None:
            return None

        import io
        from PIL import Image

        thumbnail = io.BytesIO()
        with Image.open(io.BytesIO(image)) as im:
            im: Image.Image
            im.thumbnail((128, 128))
            im.save(thumbnail, format=self.image_extension)
        return image, thumbnail.getvalue()

    def __str__(self):
        return f"TC({self.get_unique_name()})"


@dataclasses.dataclass
class ProblemLimits(object):
    time_s: float
    memory_kib: Optional[int]
    output_kib: Optional[int]


@abc.abstractmethod
class Problem(object):
    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass

    def check(self) -> None:
        pass

    @property
    @abc.abstractmethod
    def key(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def limits(self) -> ProblemLimits:
        pass

    @property
    def checker_flags(self) -> Optional[str]:
        return None

    @abc.abstractmethod
    def get_checker(self) -> Optional[Executable]:
        pass

    @abc.abstractmethod
    def load_problem_text(self) -> Tuple[bytes, str]:
        pass

    @abc.abstractmethod
    def load_testcases(self) -> Collection[ProblemTestCase]:
        pass

    @abc.abstractmethod
    def load_submissions(self) -> Collection[JuryProblemSubmission]:
        pass

    def __str__(self):
        return f"{self.name}"


class ProblemLoader(abc.ABC):
    @abc.abstractmethod
    def load_problem(self, key):
        pass

    @abc.abstractmethod
    def serialize_problem(self, problem: Problem):
        pass
