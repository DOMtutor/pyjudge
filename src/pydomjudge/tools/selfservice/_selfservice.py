"""Self-service web app for DOMjudge users.

Services (each can be enabled in the configuration):

* register: pick a username and password; creates a participant with a
  one-person team. Existing users and teams are never changed.
* change_password: users whose only role is "team" change their password.

Run it with ``pyjudge serve selfservice`` (development server) or with gunicorn
as ``pydomjudge.tools.selfservice:create_app()`` and a single worker, since
the throttling of password attempts is kept in memory.
"""

import argparse
import collections
import functools
import logging
import os
import pathlib
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

import bcrypt
import pydantic
import yaml
from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_wtf import FlaskForm
from wtforms import Field, PasswordField, StringField, ValidationError, validators

from pydomjudge.database import (
    Database,
    category_exists,
    create_or_update_teams,
    create_or_update_users,
    find_login,
    find_team_id,
    find_user_id,
    update_user_password,
)
from pydomjudge.exc import (
    ConfigurationError,
    InvalidFileFormatError,
    validation_problems,
)
from pydomjudge.model import Team, TeamCategory, User, UserRole
from pydomjudge.scripts._config import DatabaseConfig

logger = logging.getLogger(__name__)

EXTENSION_KEY = "pydomjudge"

# DOMjudge's constraint on user names (webapp/src/Entity/User.php)
USERNAME_PATTERN = r"^[a-zA-Z0-9@._-]+$"
USERNAME_MAX_LENGTH = 64

# One answer for every refused password change, so that the form tells nobody
# whether a username exists or what role it has
REFUSED = (
    "The username or the current password is wrong, or the password of this "
    "account cannot be changed here."
)
THROTTLED = "Too many failed attempts, please try again later."


# Configuration


class RegisterService(pydantic.BaseModel, extra="forbid"):
    # Key (externalid) of the team category of the new teams
    category: str = "participants"
    # An additional regular expression the username must match, e.g. "^ge[0-9]+$"
    username_pattern: str | None = None


class ChangePasswordService(pydantic.BaseModel, extra="forbid"):
    # Failed attempts per username and address, and per address, in the window
    attempts: int = 5
    address_attempts: int = 30
    window_seconds: int = 900


class Services(pydantic.BaseModel, extra="forbid"):
    # "register" would shadow ABCMeta.register of pydantic models
    registration: RegisterService | None = pydantic.Field(None, alias="register")
    change_password: ChangePasswordService | None = None

    @pydantic.model_validator(mode="before")
    @classmethod
    def _enabled_by_name(cls, data: Any) -> Any:
        # "register:" (no value) or "register: true" enables a service with its
        # defaults, "register: false" disables it
        if not isinstance(data, dict):
            return data
        result = {}
        for name, value in data.items():
            if value is False:
                continue
            result[name] = {} if value is None or value is True else value
        return result

    @pydantic.model_validator(mode="after")
    def _at_least_one(self) -> "Services":
        if not self.enabled:
            raise ValueError("enable at least one service (register, change_password)")
        return self

    @property
    def enabled(self) -> list[str]:
        """Configuration names of the enabled services."""
        return [
            info.alias or name
            for name, info in type(self).model_fields.items()
            if getattr(self, name) is not None
        ]

    def get(self, name: str) -> pydantic.BaseModel | None:
        for field_name, info in type(self).model_fields.items():
            if (info.alias or field_name) == name:
                return getattr(self, field_name)
        raise KeyError(name)


class ServerConfig(pydantic.BaseModel, extra="forbid"):
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False
    trust_proxy: int = 0


class ConfigFile(pydantic.BaseModel, extra="forbid"):
    secret_key: str | None = None
    secret_key_env: str | None = None
    min_password_length: int = 8
    server: ServerConfig = pydantic.Field(default_factory=ServerConfig)
    database: DatabaseConfig
    services: Services


@dataclass(frozen=True)
class AppConfig:
    database: Database
    secret_key: str
    minimum_password_length: int
    services: Services
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False
    trust_proxy: int = 0

    @classmethod
    def load(cls, path: pathlib.Path) -> "AppConfig":
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise InvalidFileFormatError(path, f"invalid YAML: {e}") from e
        try:
            config = ConfigFile.model_validate(data)
        except pydantic.ValidationError as e:
            raise InvalidFileFormatError(
                path, *validation_problems(e), what="self-service configuration"
            ) from e

        secret_key = config.secret_key
        if config.secret_key_env:
            secret_key = os.environ.get(config.secret_key_env)
            if not secret_key:
                raise InvalidFileFormatError(
                    path,
                    f"environment variable {config.secret_key_env} is not set or "
                    "empty; generate a key with: "
                    "python -c 'import secrets; print(secrets.token_urlsafe(32))'",
                )
        if not secret_key:
            raise InvalidFileFormatError(
                path,
                "set secret_key or secret_key_env; generate one with: "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'",
            )
        return cls(
            database=Database(**config.database.connection(path)),
            secret_key=secret_key,
            minimum_password_length=config.min_password_length,
            host=config.server.host,
            port=config.server.port,
            debug=config.server.debug,
            trust_proxy=config.server.trust_proxy,
            services=config.services,
        )


# Database access


class UserAlreadyExistsError(Exception):
    pass


class PasswordChangeRefused(Exception):
    pass


class Backend(Protocol):
    def category_exists(self, key: str) -> bool: ...

    def create_user(self, username: str, password: str, category: str) -> None: ...

    def change_password(self, username: str, current: str, new: str) -> None: ...


@functools.cache
def _dummy_hash() -> str:
    # Compared against when the user does not exist, so that the answer takes
    # about the same time either way; same cost as DOMjudge's and our hashes
    return User.hash_password("not a password")


def _password_matches(password: str, stored: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), stored.encode())
    except ValueError:
        # Not a bcrypt hash (empty, or of another algorithm): no match, after
        # as much work as a comparison
        bcrypt.checkpw(password.encode(), _dummy_hash().encode())
        return False


class UserBackend:
    def __init__(self, db: Database):
        self.db = db

    def category_exists(self, key: str) -> bool:
        with self.db as db, db.transaction_cursor(readonly=True) as cursor:
            return category_exists(cursor, key)

    def create_user(self, username: str, password: str, category: str) -> None:
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
            # The writer looks categories up by key only
            category=TeamCategory(
                key=category,
                name=category,
                color="",
                visible=True,
                order=0,
                self_registration=True,
            ),
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

    def change_password(self, username: str, current: str, new: str) -> None:
        with self.db as db, db.transaction_cursor() as cursor:
            login = find_login(cursor, username)
            stored = (login.password_hash if login else None) or _dummy_hash()
            matches = _password_matches(current, stored)
            if (
                login is None
                or not matches
                or not login.enabled
                or login.roles != {"team"}
                or login.key is None
            ):
                raise PasswordChangeRefused
            update_user_password(cursor, login.key, User.hash_password(new))


class Throttle:
    """Failed attempts per (username, address) and per address, in memory."""

    def __init__(self, service: ChangePasswordService):
        self.service = service
        self.lock = threading.Lock()
        self.failures: dict[Any, collections.deque[float]] = collections.defaultdict(
            collections.deque
        )

    def _recent(self, key: Any, now: float) -> int:
        failures = self.failures[key]
        while failures and failures[0] < now - self.service.window_seconds:
            failures.popleft()
        return len(failures)

    def allowed(self, username: str, address: str) -> bool:
        now = time.monotonic()
        with self.lock:
            return (
                self._recent((username, address), now) < self.service.attempts
                and self._recent(address, now) < self.service.address_attempts
            )

    def failed(self, username: str, address: str) -> None:
        now = time.monotonic()
        with self.lock:
            self.failures[(username, address)].append(now)
            self.failures[address].append(now)


@dataclass
class SelfServiceState:
    """What the request handlers need, stored in app.extensions."""

    config: AppConfig
    backend: Backend
    throttle: Throttle | None


def state() -> SelfServiceState:
    return current_app.extensions[EXTENSION_KEY]


# Forms


def _username_field() -> StringField:
    return StringField(
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


class _PasswordLength:
    """Checks the configured minimum length (forms are created per request)."""

    def __init__(self, minimum: int):
        self.minimum = minimum

    def __call__(self, form, field: Field) -> None:
        if len(field.data or "") < self.minimum:
            raise ValidationError(
                f"Password must be at least {self.minimum} characters long"
            )


class RegisterForm(FlaskForm):
    username = _username_field()
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

    def __init__(self, config: AppConfig, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.minimum_password_length = config.minimum_password_length
        register = config.services.registration
        self.username_pattern = register.username_pattern if register else None

    def validate_password(self, field: Field):
        _PasswordLength(self.minimum_password_length)(self, field)

    def validate_username(self, field: Field):
        if self.username_pattern and not re.search(
            self.username_pattern, field.data or ""
        ):
            raise ValidationError("This username is not allowed here.")


class ChangePasswordForm(FlaskForm):
    username = _username_field()
    current_password = PasswordField(
        "Current Password", [validators.DataRequired("Please enter your password.")]
    )
    password = PasswordField(
        "New Password", [validators.DataRequired("Please enter a new password.")]
    )
    password_confirm = PasswordField(
        "Repeat New Password",
        [
            validators.DataRequired("Please confirm your new password."),
            validators.EqualTo("password", message="Passwords must match"),
        ],
    )

    def __init__(self, config: AppConfig, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.minimum_password_length = config.minimum_password_length

    def validate_password(self, field: Field):
        _PasswordLength(self.minimum_password_length)(self, field)


def _add_error(field: Field, message: str) -> None:
    # A list after validation; the wtforms stubs only know the initial ()
    cast(list[str], field.errors).append(message)


# Routes

blueprint = Blueprint("selfservice", __name__)

SERVICE_PAGES = {
    "register": ("selfservice.register", "Create an account"),
    "change_password": ("selfservice.change_password", "Change your password"),
}


def _require(service: str) -> None:
    if state().config.services.get(service) is None:
        abort(404)


@blueprint.get("/")
def index():
    enabled = state().config.services.enabled
    if len(enabled) == 1:
        return redirect(url_for(SERVICE_PAGES[enabled[0]][0]))
    pages = [SERVICE_PAGES[name] for name in enabled]
    return render_template("index.html", pages=pages)


@blueprint.route("/register", methods=["GET", "POST"])
def register():
    _require("register")
    config = state().config
    form = RegisterForm(config)
    if request.method == "GET":
        return render_template("register.html", form=form)
    if form.validate_on_submit():
        username = form.username.data.strip()
        register_service = config.services.registration
        assert register_service is not None
        try:
            state().backend.create_user(
                username, form.password.data, register_service.category
            )
            flash(
                f"Account '{username}' created successfully. You may now log in.",
                "success",
            )
            return redirect(url_for(".register"))
        except UserAlreadyExistsError:
            _add_error(form.username, f"The username '{username}' is already taken.")
        except Exception as e:
            current_app.logger.exception(
                "Creating user %s failed", username, exc_info=e
            )
            flash("A server error occurred; please try again later.", "danger")
    return render_template("register.html", form=form), 400


@blueprint.route("/password", methods=["GET", "POST"])
def change_password():
    _require("change_password")
    current = state()
    form = ChangePasswordForm(current.config)
    if request.method == "GET":
        return render_template("password.html", form=form)
    if form.validate_on_submit():
        username = form.username.data.strip()
        address = request.remote_addr or "?"
        throttle = current.throttle
        assert throttle is not None
        if not throttle.allowed(username, address):
            flash(THROTTLED, "danger")
            return render_template("password.html", form=form), 429
        try:
            current.backend.change_password(
                username, form.current_password.data, form.password.data
            )
            flash("Your password has been changed.", "success")
            return redirect(url_for(".change_password"))
        except PasswordChangeRefused:
            throttle.failed(username, address)
            flash(REFUSED, "danger")
        except Exception as e:
            current_app.logger.exception(
                "Changing the password of %s failed", username, exc_info=e
            )
            flash("A server error occurred; please try again later.", "danger")
    return render_template("password.html", form=form), 400


def create_app(
    config: AppConfig | None = None, backend: Backend | None = None
) -> Flask:
    """The app; without config, it is read from APP_CONFIG_PATH (default
    config.yaml). The backend is only replaced in tests."""
    if config is None:
        config_path = pathlib.Path(os.environ.get("APP_CONFIG_PATH", "config.yaml"))
        if not config_path.is_file():
            raise ConfigurationError(
                f"No configuration found at {config_path}, create one or set "
                f"APP_CONFIG_PATH environment variable"
            )
        config = AppConfig.load(config_path)

    if backend is None:
        backend = UserBackend(config.database)
    # Fail at startup if the database is unreachable or the category is missing
    register_service = config.services.registration
    category = register_service.category if register_service else "participants"
    if not backend.category_exists(category) and register_service is not None:
        raise ConfigurationError(
            f"Team category {category!r} (externalid) does not exist; "
            "upload the settings first or set services.register.category"
        )

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
    change_password_service = config.services.change_password
    app.extensions[EXTENSION_KEY] = SelfServiceState(
        config=config,
        backend=backend,
        throttle=Throttle(change_password_service) if change_password_service else None,
    )
    app.register_blueprint(blueprint)
    return app


def run(args: argparse.Namespace) -> None:
    """pyjudge serve selfservice: the Flask development server."""
    config = AppConfig.load(args.config)
    app = create_app(config)
    app.run(host=config.host, port=config.port, debug=config.debug)
