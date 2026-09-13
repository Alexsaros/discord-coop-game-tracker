import os
import time
from pathlib import Path

from discord.ext.commands import Bot
from dotenv import load_dotenv

from discord_coop_core.deployment import DeploymentTarget, WebhookUpdater
from shared.logger import log

load_dotenv()


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return value


def shutdown(bot: Bot) -> None:
    time.sleep(1)       # Wait a second to give a chance for any clean-up
    bot.loop.stop()
    os._exit(0)


def start_listening_to_updates(bot: Bot) -> WebhookUpdater:
    personal_bot_path = Path(get_required_env("PERSONAL_BOT_PATH"))
    shared_code_path = Path(get_required_env("SHARED_CODE_PATH"))
    updater = WebhookUpdater(
        targets=(
            # Defines what to do when the personal bot gets updated
            DeploymentTarget(
                route=os.getenv("PERSONAL_BOT_WEBHOOK_PATH", "/update-discord-bot-cooper"),
                repository=get_required_env("PERSONAL_BOT_REPOSITORY"),
                ref="refs/heads/main",
                checkout_path=personal_bot_path,
                secret=get_required_env("PERSONAL_BOT_WEBHOOK_SECRET"),
                post_pull_command=("pipenv", "sync", "--deploy"),
            ),
            # Defines what to do when the shared code gets updated
            DeploymentTarget(
                route=os.getenv("SHARED_CODE_WEBHOOK_PATH", "/update-shared-development"),
                repository=get_required_env("SHARED_CODE_REPOSITORY"),
                ref="refs/heads/development",
                checkout_path=shared_code_path,
                secret=get_required_env("SHARED_CODE_WEBHOOK_SECRET"),
                post_pull_command=("pipenv", "run", "python", "-m", "pip", "install", "--editable", str(shared_code_path)),
                post_pull_cwd=personal_bot_path,
            ),
        ),
        log=log,
        restart=lambda: shutdown(bot),
    )
    updater.start(port=int(os.getenv("PERSONAL_BOT_UPDATER_PORT", "5500")))
    return updater
