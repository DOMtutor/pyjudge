# Example Setup

A complete, ready-to-upload setup: judge settings, two users, and one contest with three problems.
The [getting started guide](../docs/getting-started.md) walks through it step by step.

| File | Content |
|------|---------|
| `db.yml` | Database connection (default password `domjudge`, adjust to your DOMjudge) |
| `instance.json` | Judge-wide settings: limits, scoring, team categories, allowed languages |
| `users.json` | Users `user` (password `user`) and `admin`, their teams and an affiliation |
| `contest.json` | Contest `example` with problems A (`helloworld`), B (`pastryperfection`), C (`dfamin`) |
| `repository/` | The problem repository: `config.yaml` plus one folder per problem |
| `script.py` | Generates the three JSON files from Python objects |

With DOMjudge running and `db.yml` adjusted, from this folder:

```shell
pyjudge upload settings                              # instance.json
pyjudge upload users users.json
python script.py --pretty -O contest.json contest    # contest starting one hour from now
pyjudge upload contest contest.json
```

`python script.py --pretty -O <file> <settings|users|contest>` regenerates any of the JSON files; the committed `contest.json` has fixed times, so regenerate it before uploading.
All three problems generate their larger test inputs from seed files; those of `dfamin` were created from the Jinja templates in its `data/secret/` with `pyjudge problem seed`.
`pastryperfection/attachments/` holds a solution skeleton for students.
Generated files (`build/`, `.last_verified`, generated `.in` files) are ignored via `.gitignore`.
