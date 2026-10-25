# Code Review and Modernization Notes

Collected while reading the whole code base in October 2026. Items are grouped by kind and ordered by impact within each group.
"Confirmed" means reproduced with a script or demonstrated by reading the DOMjudge 9.0.1 sources in the sibling checkout; "likely" means the reasoning is clear but not executed.
Line numbers refer to the tree after the mechanical fixes listed first.

## Applied in this pass

Mechanical changes that need no discussion; everything else below is proposal only.
The import fixes are commit 390f5b9, the ruff pass is commit 3ae9424.

* `ruff check --fix` with the rule set now in `pyproject.toml` (`E`, `F`, `W`, `I`, `UP`, `B`): sorted imports, `typing.List/Dict/Optional` → builtins and `X | None`, `class X(object)` → `class X`, `universal_newlines=True` → `text=True`, `IOError` → `OSError`, `typing.Collection/Mapping/...` → `collections.abc`, `stdout=PIPE, stderr=PIPE` → `capture_output=True`, unused loop variables prefixed.
* `evaluate/_render.py` imported the non-existent module `pydomjudge.evaluate.statistics`; importing `pydomjudge.evaluate` failed.
  Now `._statistics`.
* `repository/kattis.py` imported `importlib.abc.Traversable`, which is deprecated and removed in Python 3.14, the version used by the `Dockerfile`.
  Now `importlib.resources.abc.Traversable`.
* Examples: `allowed_language_keys: []` disables submission in every language (only `null` means "all"); `set("python-bot")` built a set of characters; `import dateutil` does not import `dateutil.parser`.
  All three fixed.
* `docs/docker-compose.yml`: `depends_on: mariadb` referenced a non-existent service (compose refused to start) and the domserver used the hard-coded root password `root` instead of `DOMJUDGE_DB_ROOT_PASSWORD`.
* `Dockerfile`: `cd /build/libs/problemtools` after copying problemtools to `/build` itself; the second stage now installs the `web` extra so the tools in the image have their dependencies.
* Packaging: `dateutils` (a CLI package that only transitively provided `python-dateutil` and `pytz`) replaced by `python-dateutil`; `jinja2` declared; `matplotlib`/`numpy`/`pytz` moved to the extra `evaluate`, Flask and friends to the extra `web`; `dt_selfservice` entry point added; metadata, dev dependency group (pytest, ruff, ty) and tool configuration added.

## A. Bugs, confirmed

1. **Exporting a contest with a time-limit verdict crashes.**
   `database/_query.py:160` parses `judging.result` with `SubmissionVerdict.from_string`, whose strings are `str(verdict)` = `"time-limit"`, but DOMjudge stores `timelimit` (`etc/db-config.yaml`, `webapp/src/Entity/Judging.php`).
   `from_string("timelimit")` raises `KeyError`.
   `update_settings` (`_update.py:753`) carries its own `verdict_names` table with the correct spelling, so two spellings coexist.
   Suggest one canonical DOMjudge spelling in the enum (and a migration note for `instance.json`, whose `result_priority` keys currently use `time-limit`).
   Also check `TestcaseVerdict.PRESENTATION_ERROR = "presentation_error"` (`model/_verdict.py:49`): DOMjudge 9 no longer has that verdict at all.
2. **Exported contest data cannot be read back.**
   `ContestDataExport` serialises users and teams with `serialization_alias` (`login`, `name`, `category`, ...) and `_resolve_users_and_teams` (`_data.py:200`) re-validates them with `by_alias=True`, but no validation alias exists, so `ContestDataExport.model_validate_json(export.model_dump_json())` fails with "login_name: Field required".
   `anonymize.py` and anything consuming exports in Python are affected.
   Fix: `alias=` with `ConfigDict(validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)` (pydantic ≥ 2.11), then the custom validators and serializers mostly disappear.
3. **Anonymization is broken three ways** (`scripts/anonymize.py`): `dataclasses.replace` on a pydantic model raises `TypeError` (line 82, use `model_copy(update=...)`); the anonymized `users` list is built (line 52) but never written, so the real users are emitted; `random.Random(hash(key))` (line 22) is not reproducible across processes because `str.__hash__` is randomized.
   The script also has no entry point in `pyproject.toml`.
4. **Swapped SQL parameters.**
   `_update.py:576`: `UPDATE testcase SET description = %s WHERE testcaseid = %s` receives `(case_id, description)`.
   Updates silently affect no row (or the wrong one if a description is numeric).
5. **Users removed from a team are never detached.**
   `_update.py:248`: `unassigned = set(team.members) - assigned_users` is always empty because `assigned_users` is the union of all members.
   Intended query: `UPDATE user SET teamid = NULL WHERE teamid = %s AND userid NOT IN (<current members>)`.
6. **`response_to` becomes the string `"None"`.**
   `_query.py:362` `str(response_id)` for unanswered clarifications.
   `evaluate/_statistics.py:359` then does `clarifications_by_key[clarification.response_to]` for every clarification whose `response_to is not None` → `KeyError: 'None'`.
7. **Multi-file submissions lose files on export.**
   `_query.py:172` groups the `submission_file` query by `submitid` while selecting `filename`/`sourcecode`; MariaDB returns one arbitrary file per submission (and rejects the query under `ONLY_FULL_GROUP_BY`).
   Drop the `GROUP BY`.
8. **Repository compiler override uploads the wrong directory.**
   `kattis.py:982` passes `base_directory` (the whole `compiler/`) instead of `language_directory` to `get_directory_contents`, so a repository with `compiler/python/` uploads every language's scripts into the Python executable.
9. **Settings built in Python cannot be uploaded.**
   `_update.py:805` requires `clarification.answers` to be a `list`, but `ClarificationSettings.answers` defaults to a tuple (`Sequence[str]`).
   `update_settings(JudgeSettings())` raises a bare `ValueError`; only settings that went through JSON work.
   `tests/test_scripts.py::test_default_instance_roundtrip` had to compare JSON for the same reason.
   Make the field `list[str]` and drop the check.
10. **`.tar` destination of `dt_kattis_get` crashes.**
    `scripts/get.py:75` calls `tar.open(name, mode="w")`; `TarFile` has no such method (the `ty: ignore` comment marks it).
    Use `TarInfo` + `addfile(BytesIO)`.
11. **Fuzzer container cannot start.**
    `tools/fuzzer/_server.py:211` parses `sys.argv` inside `create_app()`, so under gunicorn argparse sees gunicorn's arguments and exits; additionally `docker_entrypoint.sh` invokes `run_app()`, which starts Flask's development server inside gunicorn.
    Take the repository path from an environment variable/config and point gunicorn at `create_app()`.
12. **Fuzzer handles only the first source file.**
    `_fuzzer.py:471`: the compile/run/return block sits inside `for name, source_code in request.sources.items()`, so the function returns after the first file.
    Write all files, then compile once.
13. **Logging calls with missing arguments** print `--- Logging error ---` instead of the message: `_update.py:1140` (three `%s`, two args), `_fuzzer.py:425` and `:545` (`%s` with only `exc_info`).
14. **Self-service duplicate check never matches.**
    `_selfservice.py:91` checks for a team *named* `t_<username>`, but the team it creates has `name=username` and `key=t_<username>`.
    The DB unique constraint catches the duplicate, but as a generic 500 instead of the friendly message.
    The `password_env`/`secret_key_env` options documented in `example_config.yaml` are not implemented (`Database(**db_data)` fails with `KeyError: 'password'`).
15. **Seed generation is not reproducible.**
    `scripts/generate_seed.py:16` seeds with `hash(name)` (randomized per process).
    Use `random.Random(name)` (deterministic for `str`) or `hashlib`.
16. **Naive datetimes give `TypeError`, not a validation error.**
    `model/_contest.py` compares `start_time < activation_time` before checking `tzinfo`; pydantic only wraps `ValueError`, so the user sees a stack trace.
    Check `tzinfo` first (or use a `field_validator`).
    The freeze-time message at line 74 says "Start has no timezone".
17. **`chardet` fallback can call `decode(None)`.**
    `_data.py:71`: `result["encoding"]` is always present and may be `None`; `should_rename_legacy` is deprecated (`prefer_superset`).

## B. Likely bugs and surprising behaviour

* `upload.py:103` `raise ValueError("Contest %s is running")`: placeholder never filled.
* `upload.py:407` `problem --skip-testcases` is parsed but `upload_problems` always updates test cases.
* `upload.py:361` the `password` subcommand is advertised but raises `NotImplementedError`; `_update.update_user_password` exists and is unused.
* `_update.py:1507` the contest `UPDATE` sets `shortname = contest.key` while the `INSERT` uses `contest.short_name`.
* `_update.py:1444` (TODO in code): problems removed from `contest.json` stay in the contest.
* `_update.py:1598` category error says "Non-existing teams specified".
* `_update.py:537` dead duplicate check (second `if file_name in testcases_by_name` is unreachable).
* `_update.py:885` `LENGTH(sourcecode) = ''` compares to a string; works only through MariaDB coercion.
* `_query.py:209/221` the testcase query filters `NOT t.deleted`, but the lookup afterwards assumes every referenced testcase exists → `KeyError` for judgings that ran on since-deleted test cases.
* `_db.py:112` `get_only` returns `result[0]` (first column) although annotated as a tuple; `readonly` (line 79) is accepted and ignored.
* `kattis.py:588` generators run with the executable `python`, which does not exist on Debian/Ubuntu without `python-is-python3`; use `sys.executable`.
* `kattis.py:106` `name[:-3]` to strip `.in`; `pathlib.Path.stem` is clearer and safe.
* `kattis.py:558` `rasterize = False` is hard-coded, so `util.rasterize_pdf` (and the undocumented `gs` dependency) is dead.
* `kattis.py` `Repository.__init__` computes `repository_runscript_directory` and `problemset_class` but nothing uses them; `ExecutableType.Runscript`, the packaged `repository/runscript/` and `repository/compare/default/compare.py` are never uploaded.
  Either wire them into `settings` (upload a repository `run`/`compare` executable like compile scripts) or remove them.
* `_fuzzer.py:257` `math.log(abs(seed), 2)` fails for seed `0`; `:249` time limit uses the bare `time_factor` instead of `base_time × factor` (TODO in code).
* `_server.py:23` the language enum is hard-coded and misses `c`; derive it from the repository.
* `_statistics.py:395/401` `statistics.mean([])` raises for contests without answered clarifications; `:101` `min(..., key=maximum_runtime)` fails when a runtime is `None` (compile errors).
* `_render.py` never closes figures (`plt.close(fig)`) and uses `pyplot` global state; rendering many problems leaks memory and can mix axes.
* `scripts/export.py:43-53` leftover debug `log.info` calls dump every team and submission at INFO.
* `scripts/util.apply_logging`: `upload.py` calls `logging.basicConfig(INFO)` beforehand, the other tools do not, so default verbosity differs per tool (see TODO "Consistent CLI model").
* `docker_entrypoint.sh:3` `IFS="\n"` sets IFS to the two characters `\` and `n`.
* `tools/watcher/domjudge_watcher.py:40` `"".join(lines)` concatenates lines without separator; `:130` `print(e)` instead of logging.
* `model/_problem.py:79` `@abc.abstractmethod` decorates the class `Problem` (harmless, meaningless).
* `model/_language.py` `Executable` and `Language` are `frozen` dataclasses with `list`/`set` fields and therefore unhashable; fine today because nothing hashes them, but the `frozen=True` promises it.
* `_update.py:1311` jury submission `externalid` is `"<teamid> <name> <reversed mtime>"` truncated to 64 characters; collisions are possible for long file names.
  A hash would be shorter and stable.

## C. Design and consistency

* **Verdict strings** (A.1) deserve a single source of truth: one enum whose `.value` is the DOMjudge string, with the JSON representation derived from it.
* **`_update.py` is 1700 lines.**
  Splitting by entity (`_users.py`, `_problems.py`, `_submissions.py`, `_contest.py`, `_settings.py`) behind the existing `database/__init__.py` façade costs nothing and makes the SQL reviewable.
  `create_problem_submissions` alone is 500 lines and re-queries global configuration per inserted submission.
* **Pydantic usage** is mixed: hand-written `model_validator(mode="before")` and `field_serializer` emulate aliases (`_data.py`, `upload.py:203` with `vars(team)`); `SubmissionFileDto` caches via `hasattr(self, "_str_content")` instead of `PrivateAttr`/`cached_property`; `JudgeSettings` uses mutable model instances as defaults (works because pydantic copies, but `Field(default_factory=...)` is the documented form).
* **problemtools coupling** goes through private attributes (`p.output_validators._validators`, `submissions._submissions`) and `argparse.Namespace` stand-ins (`kattis.py:318`, `:466`, `_fuzzer.py:266`).
  Every problemtools update can break these silently; a thin adapter module would localize the damage.
  (Long-term TODO already says "migrate away from problemtools".)
* **Keys vs. names.**
  Teams are matched by `externalid` (key) in `_update.py` but by `name` in `_query.find_teams_by_name` and in the self-service; exports identify teams by `name`.
  Decide on one.
* **Flask tools** store state as ad-hoc attributes on the app (`app.context`, `app.app_config`, `app.backend`), which is what most `ty` diagnostics are about; `app.extensions[...]` or a module-level dataclass in `g`/`current_app.config` is the idiomatic way.
* **`flask-inputs`** (last release 2024, pins `jsonschema==4.*`) is used for one request schema.
  A pydantic model for the request body removes two dependencies.
* **Shell scripts in `repository/compiler/*`** are copied from DOMjudge; document their origin and version so they can be refreshed when DOMjudge changes them.

## D. Modernization (idioms), not auto-fixable

* `dict()`/`list()` → literals; `defaultdict(lambda: 0)` → `defaultdict(int)` (`_statistics.py`).
* `global _wordlist_cache` (`util.py:19`) → `@functools.cache`.
* Enum lookups by loop (`SubmissionVerdict.from_string`, `TestcaseVerdict.from_string`, `RunVerdict.get`, `EventType.get_by_name`) → `Enum(value)` / `Enum[name]` with a `KeyError` wrapper.
* `@staticmethod def of(...)` factories → `@classmethod`.
* `pytz` → `zoneinfo` (`_statistics.py` takes a `pytz.BaseTzInfo`; `datetime.fromtimestamp(ts, tz)` works with any `tzinfo`).
* `logging.warning(...)` on the root logger (`_query.py`, `kattis.py:587`, `util.py`) → module loggers.
* `raise ... from err` in the `except` blocks flagged by `B904` (currently ignored in `pyproject.toml`), mostly in `repository/compare/default/compare.py` and `kattis.py:230`.
* Type hints: `clear_invalid_submissions(cursor)` and most `command_*` functions are untyped; `JurySubmission.author` overrides a property with a narrower type (`ty` complains).
* `argparse` boilerplate is duplicated across seven `main()` functions; a shared `make_parser()` with the common `--db/--repository/--instance/--log` options, or a single `dt` entry point with subcommands, would also address the "Consistent CLI model" TODO.
* `tools/watcher` could become a uv workspace member instead of a separate project with its own lock.

## E. Dead code

Unused and safe to delete (verified with grep over `src`, `tools`, `examples`): `util.compile_latex`, `util.check_output_defined_or_pipe`, `util.check_input_defined_or_pipe`, `util.filter_none`, `util.list_if_not_none`, `_db.get_unique`, `_update.update_problem_statement`, `_update.update_user_password` (or wire it to the `password` command), `model/_util.without_id`, `to_id_map`, `from_id_map`, `RepositoryProblem.json_ref`, `Repository.repository_runscript_directory`, `Repository.problemset_class`, `ExecutableType.Runscript`, `repository/runscript/*`, `repository/compare/default/compare.py`, `util.rasterize_pdf` (unless rasterization is revived).

## F. Dependencies and packaging

* Stale `build/` directories leak into wheels: before this pass, `uv build` produced a wheel containing `pydomjudge/fuzzer/static/*` from the pre-`src/` layout because setuptools reuses `./build`.
  CI builds from a clean checkout; locally run `rm -rf build` before `uv build`.
* `Dockerfile` uses `python:3.14-slim` while the lock file and venv use 3.13 and CI tests 3.12/3.13.
  Pick one (3.13 is the safe choice until problemtools declares 3.14 support).
* `problemtools` is installed with `SETUPTOOLS_SCM_PRETEND_VERSION=0.1` in Docker because the submodule has no git metadata there; fine, but note it in the Dockerfile.
* `uv.lock` pins Python ≥ 3.12 and 49 packages; `dependabot.yml` now proposes monthly updates for uv and GitHub Actions.
* The `.idea/`, `.junie/`, `.ruff_cache/` directories are local; `.gitignore` covers them.

## G. Type checking

`uv run ty check` reports 27 diagnostics, all in these groups: ad-hoc Flask app attributes (C above), `anonymize.py` `dataclasses.replace` (A.3), `chardet` `decode(None)` (A.17), `list.sort` on `Optional` start times in `_statistics.py:251`, the `JurySubmission.author` override, and the `validators` tuple reassignment in `_selfservice.py:135`.
CI runs `ty` as an informational step; make it blocking once these are fixed.

## H. Suggested order

1. A.1 and A.2 (verdict strings, export round trip), with tests on an exported fixture.
2. A.4, A.5, A.7, A.8 (SQL layer), ideally with an integration test against a throwaway MariaDB container in CI.
   DOMjudge 9 has no SQL schema file; the schema comes from its Doctrine migrations (`webapp/migrations`), so such a test would start from a DOMjudge-initialised database dump.
3. A.3, A.10, A.15, A.16, B items in `upload.py`.
4. Fuzzer and self-service (A.11-A.14), then replace `flask-inputs`.
5. Split `_update.py`, unify CLI parsing, delete dead code (C, D, E).
