# Getting Started from Zero

This guide takes you from an empty Linux machine to a locally running DOMjudge with an example contest, users and a jury solution uploaded through `pydomjudge`.
It is aimed at students starting a project with DOMtutor.
Expect about an hour, most of it waiting for downloads.

Windows users: use WSL2 (Ubuntu).
macOS works for the Python side, but the judgehost container needs Linux cgroups, so run DOMjudge itself on a Linux machine or VM.

## 1. Install system dependencies

On Debian or Ubuntu:

```shell
# core tools
sudo apt install git curl
# to build problemtools' checktestdata
sudo apt install automake g++ make libboost-dev libgmp-dev
# to verify problems and build problem statements (PDF)
sudo apt install pypy3 ghostscript texlive-latex-extra texlive-luatex texlive-fonts-recommended texlive-plain-generic
```

Install Docker Engine with the Compose plugin as the [Docker documentation](https://docs.docker.com/engine/install/) recommends for your distribution, including the post-installation step that lets you run `docker` without `sudo`.

Optional: `default-jdk` if your problems use Java generators or solutions.

Install [uv](https://docs.astral.sh/uv/) (Python project manager, also provides Python itself):

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Add yourself to the `docker` group (`sudo usermod -aG docker $USER`, then log out and in) so that `docker` works without `sudo`.

## 2. Install pydomjudge

```shell
git clone --recurse-submodules git@github.com:DOMtutor/pyjudge.git
cd pyjudge
(cd libs/problemtools && make)   # compiles checktestdata, used to validate test inputs
uv sync
```

`uv sync` creates `.venv/` with Python, all dependencies and the `pyjudge` command.
Either activate the environment once per shell with `source .venv/bin/activate`, or prefix every command with `uv run`.
The rest of this guide assumes an activated environment.

Check:

```shell
pyjudge --help
```

## 3. Start DOMjudge locally

DOMjudge consists of a web server (`domserver`), a database and one or more `judgehost`s that compile and run submissions.
We run all of them with Docker Compose.

```shell
mkdir ~/domjudge && cd ~/domjudge
cp ~/pyjudge/docs/docker-compose.yml .
cat > .env <<'ENV'
TZ=Europe/Berlin
DOMJUDGE_DB_ROOT_PASSWORD=change-me-root
DOMJUDGE_DB_DOMJUDGE_PASSWORD=change-me-db
DOMJUDGE_JUDGE_PASSWORD=change-me-judge
ENV
docker compose up -d
docker compose logs -f domserver     # wait until it reports the admin password, then Ctrl-C
```

Open <http://localhost:12345> and log in as `admin` with the password from the log.
Then, in the web interface, go to *Users*, edit `judgehost` and set its password to `DOMJUDGE_JUDGE_PASSWORD` from `.env` (after step 4, `pyjudge upload password judgehost` does the same).
The judgehost container reconnects on its own.
Check with `docker compose logs judgehost`; see [deployment.md](deployment.md) if it complains about cgroups.

## 4. Point pydomjudge at the database

`pyjudge upload` and `pyjudge export` talk directly to the DOMjudge database.
They look for a `db.yml` in the current directory (or take `--db <path>`):

```yaml
host: 127.0.0.1
port: 3306
user: domjudge
password: change-me-db      # DOMJUDGE_DB_DOMJUDGE_PASSWORD
database: domjudge
```

The example folder already contains one with the default password `domjudge`, so adjust it:

```shell
cd ~/pyjudge/examples
$EDITOR db.yml
```

## 5. Upload the example

The `examples` folder contains everything a setup needs:

| File | Content |
|------|---------|
| `instance.json` | Judge-wide settings: limits, scoring, team categories, allowed languages |
| `users.json` | Users `user` and `admin`, their teams and an affiliation |
| `contest.json` | Contest `example` with problems A (`helloworld`), B (`pastryperfection`), C (`dfamin`) |
| `repository/` | The problem repository: `config.yaml` plus one folder per problem |
| `script.py` | Generates the three JSON files from Python objects (see step 7) |

Upload in this order.
Every command is idempotent; running it again updates what changed.

```shell
pyjudge upload settings                   # instance.json: settings, categories, languages
pyjudge upload users users.json           # users 'user' (password 'user') and 'admin'
python script.py --pretty -O contest.json contest   # regenerate so the contest starts in an hour from now
pyjudge upload contest contest.json       # verifies the problems, builds PDFs, uploads everything
```

Passwords are only set when a user is created, so the existing `admin` keeps the password from the DOMjudge log; add `--overwrite-passwords` to the `users` upload to set it to `admin` as well.

The first `contest` upload takes a while: the larger test inputs are generated from their seed files, `problemtools` validates the test data and runs the jury solutions, and `problem2pdf` compiles the statements.
Problems that passed are marked with a `.last_verified` file and skipped next time unless something changed.

`pyjudge` finds the database configuration, `instance.json` and the `repository/` folder through `examples/pyjudge.yaml`, from `examples/` or any folder below it; `pyjudge config` shows them.
For your own project, `pyjudge init` creates these files.

## 6. Submit something

Log out of the admin account and log in as `user` (password `user`).
The contest becomes active immediately and starts one hour after you generated `contest.json`.
If you do not want to wait, edit the times in `contest.json` and upload again with `--force` (needed when a contest is running).

Submit `repository/problems/helloworld/submissions/accepted/HelloWorldTobias.py` for problem *A* and watch it get judged.
If it stays pending, the judgehost is not connected: check its password and logs.

In the jury interface (as `admin`), you will also find the uploaded jury solutions as submissions of the "Sample Solution" and "Author" teams.
These are judged too, so you can see immediately whether the expected verdicts (accepted, time limit exceeded, ...) match.

## 7. Make it your own

* **Problems**: `pyjudge problem new myproblem` creates a problem folder that verifies (or copy `repository/problems/helloworld`); adapt `problem.yaml`, statement, test data and solutions.
  The layout is the Kattis problem package format with a few additions, see [usage.md](usage.md#problem-repository).
  Check a problem without uploading with `pyjudge problem check --name myproblem`.
* **Contest**: add the problem to the contest's `problems` list in `script.py` (or `contest.json`) and upload again.
* **Users**: generate `users.json` from your course roster.
  `script.py` shows how to build `User`, `Team` and `Affiliation` objects; passwords are stored as bcrypt hashes, see `User.hash_password`.
* **Export results**: `pyjudge export contest example -d example.json` dumps all submissions, verdicts and clarifications for grading or statistics.
  The argument is the contest's short name.

From here on, [usage.md](usage.md) is the reference.

## Troubleshooting

* `No instance.json found`: run from the folder containing it, or pass `--instance`.
* `Access denied for user 'domjudge'`: `db.yml` password does not match `DOMJUDGE_DB_DOMJUDGE_PASSWORD`.
* Problem verification fails: run `pyjudge problem check --name <problem> --debug` for the full `problemtools` output.
  Missing `pypy3` or `checktestdata` are the usual suspects.
* Statement does not build: `lualatex` or a LaTeX package is missing; the build log is printed with `--debug`.
* Submissions stay pending: `docker compose logs judgehost`; see [deployment.md](deployment.md).
* Starting over: `docker compose down -v` deletes the database, then redo steps 3 to 5.
