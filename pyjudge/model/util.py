def get_md5(o) -> str:
    import hashlib

    md5 = hashlib.md5()
    with open(o, mode="rb") as f:
        while block := f.read(4096):
            md5.update(block)
    return md5.hexdigest()
