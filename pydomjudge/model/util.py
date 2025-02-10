from os import PathLike
from typing import Union


def get_md5(o: Union[bytes, PathLike]) -> str:
    import hashlib

    md5 = hashlib.md5()

    if isinstance(o, PathLike):
        with open(o, mode="rb") as f:
            while block := f.read(4096):
                md5.update(block)
    elif isinstance(o, bytes):
        md5.update(o)
    else:
        raise TypeError(type(o))

    return md5.hexdigest()
