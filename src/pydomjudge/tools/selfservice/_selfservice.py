"""Self-service registration web app for DOMjudge.

A tiny Flask application that lets a user pick a username and password. It
creates a participant and a one-person team; existing users are never changed.
"""

import argparse
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Protocol, cast

import yaml
from flask import (
    Blueprint,
    Flask,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_wtf import FlaskForm
from wtforms import Field, PasswordField, StringField, ValidationError, validators

from pydomjudge.database import (
    Database,
    create_or_update_teams,
    create_or_update_users,
    find_team_id,
    find_user_id,
)
from pydomjudge.exc import ConfigurationError
from pydomjudge.model import DefaultCategory, Team, User, UserRole

logger = logging.getLogger(__name__)

EXTENSION_KEY = "pydomjudge"

# DOMjudge's constraint on user names (webapp/src/Entity/User.php)
USERNAME_PATTERN = r"^[a-zA-Z0-9@._-]+$"
USERNAME_MAX_LENGTH = 64


def _from_env(data: dict[str, Any], key: str, what: str) -> Any:
    """data[key], or the environment variable named by data[key + "_env"]."""
    env_key = f"{key}_env"
    if data.get(env_key):
        variable = str(data[env_key])
        if variable not in os.environ:
            raise ValueError(f"Environment variable {variable} for the {what} is unset")
        return os.environ[variable]
    return data.get(key)


@dataclass(frozen=True)
class AppConfig:
    database: Database
    secret_key: str
    minimum_password_length: int
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False
    trust_proxy: int = 0

    @classmethod
    def load(cls, path: pathlib.Path) -> "AppConfig":
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Config file {path} does not contain a mapping.")

        db_data = data.get("database")
        if not isinstance(db_data, dict):
            raise ValueError("Config file is missing a 'database' mapping.")
        db_data = dict(db_data)
        db_data["password"] = _from_env(db_data, "password", "database password")
        db_data.pop("password_env", None)
        if db_data["password"] is None:
            raise ValueError("Set 'password' or 'password_env' for the database.")

        secret_key = _from_env(data, "secret_key", "secret key")
        if not secret_key or not isinstance(secret_key, str):
            raise ValueError(
                "Missing 'secret_key' (or 'secret_key_env') in configuration. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )

        server = data.get("server", {}) or {}
        return cls(
            database=Database(**db_data),
            secret_key=secret_key,
            host=str(server.get("host", "127.0.0.1")),
            port=int(server.get("port", 5000)),
            trust_proxy=int(server.get("trust_proxy", 0)),
            debug=bool(server.get("debug", False)),
            minimum_password_length=int(data.get("min_password_length", 8)),
        )


class UserAlreadyExistsError(Exception):
    pass


class Backend(Protocol):
    def create_user(self, username: str, password: str) -> None: ...


class UserBackend:
    def __init__(self, db: Database):
        self.db = db

    def create_user(self, username: str, password: str) -> None:
        user = User(
            key=username,
            login_name=username,
            display_name=username,
            email=None,
            role=UserRole.Participant,
            password_hash=User.hash_password(password),
        )
        team = Team(
            key=f"t_{username}",
            name=username,
            display_name=username,
            members=[user],
            category=DefaultCategory.Participants,
            affiliation=None,
        )
        with self.db as db, db.transaction_cursor() as cursor:
            # The writer matches by externalid (key) and would update an existing
            # user or team with that key, so check names and keys of both
            if (
                find_user_id(cursor, key=user.key, login_name=user.login_name)
                is not None
                or find_team_id(cursor, key=team.key, name=team.name) is not None
            ):
                raise UserAlreadyExistsError
            user_ids = create_or_update_users(cursor, [user])
            create_or_update_teams(cursor, [team], user_ids=user_ids)


@dataclass(frozen=True)
class SelfServiceState:
    """What the request handlers need, stored in app.extensions."""

    config: AppConfig
    backend: Backend


def state() -> SelfServiceState:
    return current_app.extensions[EXTENSION_KEY]


class RegisterForm(FlaskForm):
    username = StringField(
        "Username",
        [
            validators.DataRequired(message="Please enter a username."),
            validators.Length(max=USERNAME_MAX_LENGTH),
            validators.Regexp(
                USERNAME_PATTERN,
                message="Only letters, digits and the characters _-@. are allowed.",
            ),
        ],
    )
    password = PasswordField(
        "New Password", [validators.DataRequired("Please enter a password.")]
    )
    password_confirm = PasswordField(
        "Repeat Password",
        [
            validators.DataRequired("Please confirm your password."),
            validators.EqualTo("password", message="Passwords must match"),
        ],
    )

    def __init__(self, minimum_password_length: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.minimum_password_length = minimum_password_length

    # WTForms runs validate_<field> methods in addition to the field validators
    def validate_password(self, field: Field):
        if len(field.data or "") < self.minimum_password_length:
            raise ValidationError(
                f"Password must be at least {self.minimum_password_length} "
                "characters long"
            )


register_bp = Blueprint("register", __name__)


@register_bp.get("/")
def register_form():
    return render_template(
        "register.html", form=RegisterForm(state().config.minimum_password_length)
    )


@register_bp.post("/")
def register_submit():
    form = RegisterForm(state().config.minimum_password_length)

    if form.validate_on_submit():
        username = form.username.data.strip()
        try:
            state().backend.create_user(username, form.password.data)
            flash(
                f"Account '{username}' created successfully. You may now log in.",
                "success",
            )
            return redirect(url_for(".register_form"))
        except UserAlreadyExistsError:
            # A list after validation; the wtforms stubs only know the initial ()
            cast(list[str], form.username.errors).append(
                f"The username '{username}' is already taken."
            )
        except Exception as e:
            current_app.logger.exception(
                "Creating user %s failed", username, exc_info=e
            )
            flash("A server error occurred; please try again later.", "danger")
    return render_template("register.html", form=form), 400


def create_app(
    config: AppConfig | None = None, backend: Backend | None = None
) -> Flask:
    """The app; without config, it is read from APP_CONFIG_PATH (default
    config.yaml). The backend is only replaced in tests."""
    if config is None:
        config_path = pathlib.Path(os.environ.get("APP_CONFIG_PATH", "config.yaml"))
        if not config_path.is_file():
            raise ValueError(
                f"No configuration found at {config_path}, create one or set "
                f"APP_CONFIG_PATH environment variable"
            )
        config = AppConfig.load(config_path)

    if backend is None:
        # Fail early if the database is not reachable
        with config.database as db, db.transaction_cursor(readonly=True):
            pass
        backend = UserBackend(config.database)

    app = Flask(__name__)
    if config.trust_proxy:
        from werkzeug.middleware.proxy_fix import ProxyFix

        # Flask's documented way to wrap the WSGI app
        app.wsgi_app = ProxyFix(  # ty: ignore[invalid-assignment]
            app.wsgi_app,
            x_for=config.trust_proxy,
            x_proto=config.trust_proxy,
            x_host=config.trust_proxy,
            x_port=config.trust_proxy,
            x_prefix=config.trust_proxy,
        )

    app.config["SECRET_KEY"] = config.secret_key
    app.extensions[EXTENSION_KEY] = SelfServiceState(config=config, backend=backend)
    app.register_blueprint(register_bp)
    return app


def run(args: argparse.Namespace) -> None:
    """pyjudge serve selfservice: the Flask development server."""
    try:
        config = AppConfig.load(args.config)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise ConfigurationError(f"{args.config}: {exc}") from exc
    app = create_app(config)
    app.run(host=config.host, port=config.port, debug=config.debug)
