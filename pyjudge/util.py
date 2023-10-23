from typing import Any, Dict, Set, Optional, Iterable


def list_if_not_none(iterable: Optional[Iterable[Any]]):
    if iterable is None:
        return None
    return list(iterable)


def filter_none(data: Dict[str, Any], except_keys: Optional[Set[str]] = None):
    if except_keys is None:
        except_keys = {}
    return {
        key: value
        for key, value in data.items()
        if value is not None or key in except_keys
    }
