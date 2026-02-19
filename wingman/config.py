"""Configuration loading from config.toml + .env."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class GitHubConfig:
    token: str
    owner: str
    repos: list[str]
    check_interval_minutes: int = 60


@dataclass(frozen=True)
class ForgeMod:
    name: str
    id: int
    slug: str


@dataclass(frozen=True)
class ForgeConfig:
    email: str
    password: str
    mods: list[ForgeMod]
    check_interval_minutes: int = 60


@dataclass(frozen=True)
class RedditConfig:
    client_id: str
    client_secret: str
    username: str
    password: str
    user_agent: str
    subreddit: str
    enabled: bool = False
    check_interval_minutes: int = 30


@dataclass(frozen=True)
class NotificationConfig:
    smtp_server: str
    smtp_port: int
    smtp_email: str
    smtp_password: str
    recipient_email: str
    sms_gateway: str


@dataclass(frozen=True)
class TriageConfig:
    api_key: str
    model: str = "claude-sonnet-4-20250514"


@dataclass(frozen=True)
class WingmanConfig:
    github: GitHubConfig
    forge: ForgeConfig
    reddit: RedditConfig
    notifications: NotificationConfig
    triage: TriageConfig
    database_path: str = "wingman.db"
    log_level: str = "INFO"
    first_run_notify: bool = False


def _env(key: str, default: str = "") -> str:
    """Get an environment variable, returning default if not set."""
    return os.environ.get(key, default)


def load_config(config_path: str | Path | None = None) -> WingmanConfig:
    """Load configuration from config.toml and .env files.

    Args:
        config_path: Path to config.toml. Defaults to config.toml in the
                     project root (next to the wingman package).
    """
    project_root = Path(__file__).resolve().parent.parent

    # Load .env from project root
    env_path = project_root / ".env"
    load_dotenv(env_path)

    # Load TOML config
    if config_path is None:
        config_path = project_root / "config.toml"
    else:
        config_path = Path(config_path)

    with open(config_path, "rb") as f:
        toml = tomllib.load(f)

    general = toml.get("general", {})
    gh = toml.get("github", {})
    forge = toml.get("forge", {})
    reddit = toml.get("reddit", {})
    notif = toml.get("notifications", {})
    triage = toml.get("triage", {})

    return WingmanConfig(
        database_path=general.get("database_path", "wingman.db"),
        log_level=general.get("log_level", "INFO"),
        first_run_notify=general.get("first_run_notify", False),
        github=GitHubConfig(
            token=_env("GITHUB_TOKEN"),
            owner=gh.get("owner", ""),
            repos=gh.get("repos", []),
            check_interval_minutes=gh.get("check_interval_minutes", 60),
        ),
        forge=ForgeConfig(
            email=_env("FORGE_EMAIL"),
            password=_env("FORGE_PASSWORD"),
            mods=[
                ForgeMod(name=name, id=info["id"], slug=info["slug"])
                for name, info in forge.get("mods", {}).items()
            ],
            check_interval_minutes=forge.get("check_interval_minutes", 60),
        ),
        reddit=RedditConfig(
            client_id=_env("REDDIT_CLIENT_ID"),
            client_secret=_env("REDDIT_CLIENT_SECRET"),
            username=_env("REDDIT_USERNAME"),
            password=_env("REDDIT_PASSWORD"),
            user_agent=reddit.get("user_agent", "Wingman/1.0"),
            subreddit=reddit.get("subreddit", ""),
            enabled=reddit.get("enabled", False),
            check_interval_minutes=reddit.get("check_interval_minutes", 30),
        ),
        notifications=NotificationConfig(
            smtp_server=notif.get("smtp_server", "smtp.gmail.com"),
            smtp_port=notif.get("smtp_port", 587),
            smtp_email=_env("SMTP_EMAIL"),
            smtp_password=_env("SMTP_APP_PASSWORD"),
            recipient_email=_env("NOTIFICATION_RECIPIENT"),
            sms_gateway=_env("SMS_GATEWAY"),
        ),
        triage=TriageConfig(
            api_key=_env("ANTHROPIC_API_KEY"),
            model=triage.get("model", "claude-sonnet-4-20250514"),
        ),
    )
