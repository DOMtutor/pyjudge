import argparse
import pathlib
import random
import sys

import jinja2


def render_content(
    file_number: int, filename_template: str, content_template: jinja2.Template
):
    name = filename_template.format(n=file_number)
    # Seeding with a str is deterministic (hash() is randomized per process)
    rnd = random.Random(name)
    seed = rnd.randint(0, 2**63 - 1)
    return name, content_template.render(n=file_number, seed=seed, random=rnd)


def run(args: argparse.Namespace) -> None:
    """Render seed files from a template; asks before writing."""
    if args.count <= 0:
        sys.exit("Need a positive count")

    env = jinja2.Environment()

    filename_template = args.filename
    template_content = None
    if len(args.content) == 1:
        path = pathlib.Path(args.content[0])
        if path.exists():
            template_content = path.read_text()
            if filename_template is None:
                filename_template = path.stem + "_{n:02d}.seed"
    if filename_template is None:
        sys.exit("Need a filename template (could not infer from other arguments)")
    if template_content is None:
        template_content = "\n".join(args.content)

    template = env.from_string(template_content)

    files = {}
    for i in range(args.count):
        filename, content = render_content(i + 1, filename_template, template)
        file = pathlib.Path(filename).resolve().absolute()
        if file in files:
            sys.exit("Duplicate filenames!")
        files[file] = content

    file_list = sorted(files.items(), key=lambda x: x[0])

    print(
        f"Would write the following files: {', '.join(file.name for file, _ in file_list)}"
    )
    print(f"Sample content:\n{file_list[0][1]}")
    print()

    existing = set(file for file, _ in file_list if file.exists())
    if existing:
        print(
            f"Note: Would overwrite the files {', '.join(sorted(file.name for file in existing))}"
        )

    answer = input("Write? (yes/no) ").lower()
    while answer not in {"yes", "no", "y", "n"}:
        answer = input('Please choose "yes" or "no": ').lower()

    if answer in {"yes", "y"}:
        for file, content in file_list:
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open(mode="wt") as f:
                f.write(content)
