"""Self-service registration web app for DOMjudge.

A tiny Flask application that lets a user pick a username and password.
"""

import argparse
import logging
import pathlib
from dataclasses import dataclass

import yaml
from flask import (
    Flask,
    current_app,
    flash,
    render_template,
    redirect,
    url_for,
    Blueprint,
)
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, validators

from pydomjudge.database import (
    Database,
    create_or_update_users,
    find_users_by_login,
    find_teams_by_name,
    create_or_update_teams,
)
from pydomjudge.model import User, Team
from pydomjudge.model import UserRole, DefaultCategory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppConfig:
    database: Database
    secret_key: str
    minimum_password_length: int
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False

    @classmethod
    def load(cls, path: pathlib.Path) -> "AppConfig":
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Config file {path} does not contain a mapping.")

        db_data = data.get("database")
        if not isinstance(db_data, dict):
            raise ValueError("Config file is missing a 'database' mapping.")

        secret_key = data.get("secret_key")
        if not secret_key or not isinstance(secret_key, str):
            raise ValueError(
                "Missing 'secret_key' in configuration. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )

        server = data.get("server", {}) or {}
        database = Database(**db_data)

        return cls(
            database=database,
            secret_key=secret_key,
            host=str(server.get("host", "127.0.0.1")),
            port=int(server.get("port", 5000)),
            debug=bool(server.get("debug", False)),
            minimum_password_length=int(data.get("min_password_length", 8)),
        )


class UserAlreadyExistsError(Exception):
    pass


class UserBackend:
    def __init__(self, db: Database):
        self.db = db

    def create_user(self, username: str, password: str) -> None:
        with self.db as db:
            if find_users_by_login(db, {username}):
                raise UserAlreadyExistsError
            if find_teams_by_name(db, {f"t_{username}"}):
                raise UserAlreadyExistsError
            with db.transaction_cursor() as cursor:
                user = User(
                    key=username,
                    login_name=username,
                    display_name=username,
                    email=None,
                    role=UserRole.Participant,
                    password_hash=User.hash_password(password),
                )
                create_or_update_users(cursor, [user])
                team = Team(
                    key=f"t_{username}",
                    name=username,
                    display_name=username,
                    members=[user],
                    category=DefaultCategory.Participants,
                    affiliation=None,
                )
                create_or_update_teams(cursor, [team])


class RegisterForm(FlaskForm):
    username = StringField(
        "Username", [validators.DataRequired(message="Please enter a username.")]
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
        length_validator = validators.Length(
            min=minimum_password_length,
            message=f"Password must be at least {minimum_password_length} characters long",
        )
        self.password.validators = tuple(
            list(self.password.validators) + [length_validator]
        )


register_bp = Blueprint("register", __name__)


@register_bp.get("/")
def register_form():
    config: AppConfig = current_app.app_config
    return render_template(
        "register.html", form=RegisterForm(config.minimum_password_length)
    )


@register_bp.post("/")
def register_submit():
    config: AppConfig = current_app.app_config
    form = RegisterForm(config.minimum_password_length)

    if form.validate_on_submit():
        backend: UserBackend = current_app.backend
        username = form.username.data.strip()
        password = form.password.data

        try:
            backend.create_user(username, password)
            flash(
                f"Account '{username}' created successfully. You may now log in.",
                "success",
            )
            return redirect(url_for(".register_form"))
        except UserAlreadyExistsError:
            form.username.errors.append(f"The username '{username}' is already taken.")
        except Exception as e:
            current_app.logger.exception(
                "Creating user %s failed", username, exc_info=e
            )
            flash("A server error occurred; please try again later.", "danger")
    return render_template("register.html", form=form), 400


def create_app(config: AppConfig) -> Flask:
    # Check connection
    with config.database as db:
        with db.transaction_cursor() as _:
            pass

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.app_config = config
    app.backend = UserBackend(config.database)
    app.register_blueprint(register_bp)
    return app


def start() -> None:
    parser = argparse.ArgumentParser(description="DOMjudge self-service registration")
    parser.add_argument(
        "-c",
        "--config",
        type=pathlib.Path,
        default=pathlib.Path(__file__).parent / "config.yaml",
        help="Path to the configuration file (default: config.yaml next to this module).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        config = AppConfig.load(args.config)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.critical("Failed to load config file %s: %s", args.config, exc)
        raise SystemExit(1) from exc

    app = create_app(config)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    start()
