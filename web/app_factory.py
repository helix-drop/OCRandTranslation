"""Flask app factory。"""

from __future__ import annotations

import os

from flask import Flask

from logging_config import setup_logging
from web.csrf import register_csrf
from web.dev_routes import register_dev_routes
from web.document_routes import register_document_routes
from web.export_routes import register_export_routes
from web.page_editor_routes import register_page_editor_routes
from web.reading_routes import register_reading_routes
from web.services import build_app_services
from web.settings_routes import register_settings_routes
from web.toc_routes import register_toc_routes
from web.translation_routes import register_translation_routes


def create_app() -> Flask:
    setup_logging()
    web_dir = os.path.dirname(__file__)
    project_root = os.path.dirname(web_dir)
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, "templates"),
        static_folder=os.path.join(project_root, "static"),
    )
    app.secret_key = os.urandom(24)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    register_csrf(app)

    services = build_app_services()
    register_document_routes(app, services.document)
    register_reading_routes(app, services.reading)
    register_translation_routes(app, services.translation)
    register_page_editor_routes(app, services.page_editor)
    register_settings_routes(app, services.settings)
    register_export_routes(app, services.export)
    register_toc_routes(app, services.toc)
    register_dev_routes(app)
    return app
