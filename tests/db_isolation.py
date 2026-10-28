"""Point tests at a throwaway sqlite file.

Flask-SQLAlchemy builds the engine once. Changing SQLALCHEMY_DATABASE_URI
afterwards does not move it, so drop_all() would erase the live app.db.
init_app() can run only before the first request; later tests swap the engine.
"""
from __future__ import annotations

from sqlalchemy import create_engine


def use_temp_db(server, path) -> None:
    uri = f"sqlite:///{path}"
    server.app.config["SQLALCHEMY_DATABASE_URI"] = uri
    server.app.config["TESTING"] = True
    server.db.session.remove()
    app = server.app
    db = server.db
    if "sqlalchemy" not in app.extensions:
        db.init_app(app)
    else:
        engines = db._app_engines.setdefault(app, {})
        for eng in list(engines.values()):
            eng.dispose()
        engines.clear()
        engines[None] = create_engine(uri)
    url = str(db.engine.url).replace("\\", "/").rstrip("/")
    if url.endswith("/app.db"):
        raise RuntimeError("refusing to touch the live database")
