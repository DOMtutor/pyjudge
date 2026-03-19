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


def without_id(obj, key_name):
    return {k: v for k, v in vars(obj).items() if k != key_name}


def to_id_map(objects):
    return {obj.json_key(): without_id(obj, obj.json_key_name()) for obj in objects}


def from_id_map(objects, cls):
    return [{**values, cls.json_key_name(): key} for key, values in objects.items()]
