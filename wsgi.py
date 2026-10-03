"""WSGI entry for gunicorn: gunicorn -c deploy/gunicorn.conf.py wsgi:app"""
from server import app, db  # noqa: F401

with app.app_context():
    db.create_all()
