import abc
import dataclasses
from typing import Optional, Tuple, Collection, TypeVar, Generic

from .submission import JuryProblemSubmission
from .language import Executable
from .util import get_md5


class ProblemTestCase(abc.ABC):
    @property
    @abc.abstractmethod
    def input(self):
        pass

    @property
    def input_md5(self) -> str:
        return get_md5(self.input)

    @property
    @abc.abstractmethod
    def output(self):
        pass

    @property
    def output_md5(self) -> str:
        return get_md5(self.output)

    @abc.abstractmethod
    def is_sample(self):
        pass

    @property
    @abc.abstractmethod
    def unique_name(self) -> str:
        pass

    @property
    def image_extension(self) -> Optional[str]:
        return None

    @property
    def description(self) -> Optional[str]:
        return None

    @property
    def image(self) -> Optional[Tuple[bytes, bytes]]:
        image = self._load_image()
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

    @abc.abstractmethod
    def _load_image(self) -> Optional[bytes]:
        pass

    def __str__(self):
        return f"TC({self.unique_name})"


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
    @abc.abstractmethod
    def checker(self) -> Optional[Executable]:
        pass

    @property
    def checker_flags(self) -> Optional[str]:
        return None

    @property
    @abc.abstractmethod
    def problem_text(self) -> Tuple[bytes, str]:
        pass

    @property
    @abc.abstractmethod
    def testcases(self) -> Collection[ProblemTestCase]:
        pass

    @property
    @abc.abstractmethod
    def submissions(self) -> Collection[JuryProblemSubmission]:
        pass

    def __str__(self):
        return f"{self.name}"


P = TypeVar('P', bound=Problem)


class ProblemLoader(abc.ABC, Generic[P]):
    @abc.abstractmethod
    def load_problem(self, key) -> P:
        pass

    def __getitem__(self, item):
        return self.load_problem(item)

    @abc.abstractmethod
    def serialize_problem(self, problem: P):
        pass
