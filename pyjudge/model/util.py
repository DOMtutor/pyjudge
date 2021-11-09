from os import PathLike
from typing import Union


def get_md5(o: Union[bytes, PathLike, str]) -> str:
    import hashlib

    md5 = hashlib.md5()

    if isinstance(o, PathLike) or isinstance(o, str):
        with open(o, mode="rb") as f:
            while block := f.read(4096):
                md5.update(block)
    else:
        md5.update(o)

    return md5.hexdigest()
