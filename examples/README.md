# Example Setup

A complete, ready-to-upload setup: judge settings, two users, and one contest with three problems.
The [getting started guide](../docs/getting-started.md) walks through it step by step.

| File | Content |
|------|---------|
| `db.yml` | Database connection (default password `domjudge`, adjust to your DOMjudge) |
| `instance.json` | Judge-wide settings: limits, scoring, team categories, allowed languages |
| `users.json` | Users `user` and `admin` (password equal to the login name), their teams and an affiliation |
| `contest.json` | Contest `example` with problems A (`helloworld`), B (`pastryperfection`), C (`dfamin`) |
| `repository/` | The problem repository: `config.yaml` plus one folder per problem |
| `script.py` | Generates the three JSON files from Python objects |

With DOMjudge running and `db.yml` adjusted, from this folder:

```shell
dt_judge_upload settings                             # instance.json
dt_judge_upload users users.json
python script.py --pretty -O contest.json contest    # contest starting one hour from now
dt_judge_upload contest contest.json
```

`python script.py --pretty -O <file> <settings|users|contest>` regenerates any of the JSON files; the committed `contest.json` has fixed times, so regenerate it before uploading.
`dfamin` creates its larger test inputs from seed files, which in turn come from the Jinja templates in `data/secret/` (`dt_generate_seed`).
Generated files (`build/`, `.last_verified`, generated `.in` files) are ignored via `.gitignore`.
