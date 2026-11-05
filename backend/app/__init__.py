import os

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException, default_exceptions

from .config import Config
from .db import JSONProvider, ensure_indexes


class PaymentRequired(HTTPException):
    """402 — plan limit reached or subscription overdue (werkzeug has no built-in class)."""
    code = 402
    description = "Upgrade required"


default_exceptions[402] = PaymentRequired


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.json_provider_class = JSONProvider
    app.json = JSONProvider(app)
    CORS(app)
    os.makedirs(Config.UPLOAD_DIR, exist_ok=True)
    ensure_indexes()

    # each feature module is a blueprint; later modules are added to this tuple without touching the others
    from .routes import auth, users, access, superadmin, contacts, projects, admin, leads, followups, notifications
    for module in (auth, users, access, superadmin, contacts, projects, admin, leads, followups, notifications):
        app.register_blueprint(module.bp, url_prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.errorhandler(HTTPException)
    def http_error(e):
        return jsonify({"error": e.description, "status": e.code}), e.code

    @app.errorhandler(Exception)
    def server_error(e):
        app.logger.exception(e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500

    return app
