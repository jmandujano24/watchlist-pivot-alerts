from flask import Flask
import subprocess

app = Flask(__name__)

@app.route("/")
def home():
    return "Watchlist bot alive"

@app.route("/run")
def run_bot():
    subprocess.run(["python", "main.py"])
    return "ok", 200
