from flask import Flask, request
import subprocess
import os

app = Flask(__name__)

SECRET = os.getenv("WEBHOOK_SECRET", "")


@app.route("/")
def home():
    return "Watchlist bot alive"


@app.route("/run")
def run_bot():
    if SECRET:
        if request.args.get("key") != SECRET:
            return "unauthorized", 401

    subprocess.run(["python", "main.py"])
    return "ok", 200
