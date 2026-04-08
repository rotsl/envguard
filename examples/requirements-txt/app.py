"""Simple Flask application for envguard testing."""
import os

from flask import Flask, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["APP_NAME"] = os.getenv("APP_NAME", "requirements-txt-demo")
app.config["DEBUG"] = os.getenv("DEBUG", "false").lower() == "true"


@app.route("/")
def index():
    """Return application status."""
    return jsonify({
        "app": app.config["APP_NAME"],
        "status": "running",
        "message": "Hello from requirements-txt-demo!",
    })


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"})


@app.route("/env")
def env_info():
    """Display environment information."""
    import sys
    return jsonify({
        "python_version": sys.version,
        "debug": app.config["DEBUG"],
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=app.config["DEBUG"])
