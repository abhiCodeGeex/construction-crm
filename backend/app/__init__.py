import os

from flask import Flask, abort, jsonify, request
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
    from .routes import auth, users, access, superadmin, contacts, projects, admin, leads, followups, notifications, lead_steps, lead_brief, lead_money, lead_tools, proposals, project_work, project_plan, project_meetings, finance, invoices, change_orders, finance_reports, documents, selections, site_reports
    for module in (auth, users, access, superadmin, contacts, projects, admin, leads, followups, notifications, lead_steps, lead_brief, lead_money, lead_tools, proposals, project_work, project_plan, project_meetings, finance, invoices, change_orders, finance_reports, documents, selections, site_reports):
        app.register_blueprint(module.bp, url_prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.before_request
    def json_object_only():
        """Every API write takes a JSON object. A list, a bare number or broken JSON is refused here with a clear
        message, so no route can trip over a body of the wrong shape (found by the regression sweep)."""
        if not request.path.startswith("/api/") or request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        if (request.mimetype or "").startswith(("multipart/", "application/x-www-form-urlencoded")):
            return None  # file uploads: never read the raw body here, the form parser needs it
        if not request.data:
            return None
        body = request.get_json(force=True, silent=True)
        if body is None and request.data.strip() not in (b"null", b""):
            abort(400, "The request body is not valid JSON")
        if body is not None and not isinstance(body, dict):
            abort(400, "Send the data as a JSON object ({ … })")
        return None

    @app.errorhandler(HTTPException)
    def http_error(e):
        return jsonify({"error": e.description, "status": e.code}), e.code

    @app.errorhandler(TypeError)
    @app.errorhandler(AttributeError)
    @app.errorhandler(ValueError)
    def bad_value(e):
        """A field of the wrong type or format (a number where text is expected, 'abc' as a limit or a date…).
        The caller gets a clear 400; the details stay in the server log so a real bug is still visible."""
        app.logger.warning("Bad value in %s: %r", request.path, e)
        return jsonify({"error": "A value sent has the wrong type or format. Check the fields and try again.",
                        "status": 400}), 400

    @app.errorhandler(Exception)
    def server_error(e):
        app.logger.exception(e)  # the details go to the log, never to the browser
        return jsonify({"error": "Something went wrong on the server. It has been logged.", "status": 500}), 500

    return app
