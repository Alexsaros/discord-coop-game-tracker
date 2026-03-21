import hashlib
import hmac
import os
import subprocess
import threading
import time

import flask
from discord.ext.commands import Bot
from dotenv import load_dotenv

from shared.logger import log

load_dotenv()
GITHUB_WEBHOOK_SECRET_TOKEN = os.getenv("GITHUB_WEBHOOK_SECRET_TOKEN")


class BotUpdater:

    def __init__(self, bot: Bot):
        self.bot = bot
        self.flask_app = flask.Flask(__name__)
        self._setup_flask_routes()

    def _setup_flask_routes(self):
        @self.flask_app.route("/update-discord-bot-cooper", methods=["POST"])
        def update_bot():
            # Check if the request has the correct signature/secret
            signature = flask.request.headers.get("X-Hub-Signature-256")
            if not signature:
                log("Incoming request does not have a `X-Hub-Signature-256` header.")
                flask.abort(403)
            sha_name, signature = signature.split("=")
            if sha_name != "sha256":
                log(f"Incoming request's X-Hub-Signature-256 does not use sha256, but `{sha_name}`.")
                flask.abort(403)
            # Using the secret, check if we compute the same HMAC for this request as the received HMAC
            computed_hmac = hmac.new(GITHUB_WEBHOOK_SECRET_TOKEN.encode(), msg=flask.request.data,
                                     digestmod=hashlib.sha256)
            if not hmac.compare_digest(computed_hmac.hexdigest(), signature):
                log("Incoming request does not have a matching HMAC/secret.")
                flask.abort(403)

            data = flask.request.json
            if data and data.get("ref") == "refs/heads/main":
                os.chdir("/home/alexsaro/discord-coop-game-tracker")
                output = subprocess.run(["git", "pull"], capture_output=True, text=True)

                log(output)
                log("Pulled new git commits. Shutting down the bot so it can restart...")
                threading.Thread(target=self.shutdown).start()
            return "", 200

    def shutdown(self):
        time.sleep(1)       # Wait a second to give a chance for any clean-up
        self.bot.loop.stop()
        os._exit(0)


def start_listening_to_updates(bot: Bot):
    # Start a thread that will restart the bot whenever a Git commit has been pushed to the repo
    bot_updater = BotUpdater(bot)
    updater_thread = threading.Thread(target=bot_updater.flask_app.run, kwargs={"host": "127.0.0.1", "port": 5500})
    updater_thread.start()
