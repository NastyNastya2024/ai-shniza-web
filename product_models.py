"""SQLAlchemy models for balances, works, profiles, FX rate cache."""
from __future__ import annotations

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy


def init_product_models(db: SQLAlchemy):
    class Balance(db.Model):
        __tablename__ = "balances"
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
        balance_kop = db.Column(db.Integer, nullable=False, default=0)
        held_kop = db.Column(db.Integer, nullable=False, default=0)
        updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    class Ledger(db.Model):
        __tablename__ = "ledger"
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
        kind = db.Column(db.String(20), nullable=False)  # topup|hold|capture|release|refund|adjust
        amount_kop = db.Column(db.Integer, nullable=False)  # signed: + credit, - debit for capture/hold
        model_key = db.Column(db.String(200), nullable=True)
        job_id = db.Column(db.String(64), nullable=True, index=True)
        price_snapshot = db.Column(db.Text, nullable=True)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
        idempotency_key = db.Column(db.String(120), unique=True, nullable=True)

    class CreatorProfile(db.Model):
        __tablename__ = "creator_profiles"
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
        handle = db.Column(db.String(32), unique=True, nullable=True, index=True)
        display_name = db.Column(db.String(120), nullable=True)
        bio = db.Column(db.String(160), nullable=True)
        avatar_url = db.Column(db.String(500), nullable=True)
        email_verified = db.Column(db.Boolean, default=False)
        telegram = db.Column(db.String(120), nullable=True)
        vk = db.Column(db.String(120), nullable=True)
        website = db.Column(db.String(250), nullable=True)
        show_telegram = db.Column(db.Boolean, default=True)
        show_vk = db.Column(db.Boolean, default=False)
        show_website = db.Column(db.Boolean, default=True)
        show_email = db.Column(db.Boolean, default=False)
        referral_code = db.Column(db.String(32), unique=True, nullable=True, index=True)
        referred_by = db.Column(db.Integer, nullable=True)
        consent_152 = db.Column(db.Boolean, default=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)

    class Work(db.Model):
        __tablename__ = "works"
        id = db.Column(db.Integer, primary_key=True)
        owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
        kind = db.Column(db.String(20), nullable=False)  # video|image|audio|text
        model_key = db.Column(db.String(200), nullable=False)
        prompt = db.Column(db.Text, nullable=False, default="")
        params = db.Column(db.Text, nullable=True)
        original_url = db.Column(db.String(700), nullable=True)
        watermarked_url = db.Column(db.String(700), nullable=True)
        thumb_url = db.Column(db.String(700), nullable=True)
        status = db.Column(db.String(20), nullable=False, default="draft", index=True)
        title = db.Column(db.String(200), nullable=True)
        tags = db.Column(db.String(300), nullable=True)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
        published_at = db.Column(db.DateTime, nullable=True)
        downloads = db.Column(db.Integer, default=0)
        likes = db.Column(db.Integer, default=0)
        job_id = db.Column(db.String(64), nullable=True, index=True)

    class FreeQuota(db.Model):
        __tablename__ = "free_quotas"
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
        day_key = db.Column(db.String(10), primary_key=True)  # YYYY-MM-DD MSK
        used = db.Column(db.Integer, default=0)
        bonus = db.Column(db.Integer, default=0)
        publish_bonus_used = db.Column(db.Boolean, default=False)
        lifetime_success = db.Column(db.Integer, default=0)

    class FxRate(db.Model):
        __tablename__ = "fx_rates"
        id = db.Column(db.Integer, primary_key=True)
        code = db.Column(db.String(8), unique=True, nullable=False, default="USD")
        rate = db.Column(db.Float, nullable=False)
        fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    class LoginCode(db.Model):
        __tablename__ = "login_codes"
        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(255), index=True, nullable=False)
        code_hash = db.Column(db.String(128), nullable=False)
        attempts = db.Column(db.Integer, default=0)
        expires_at = db.Column(db.DateTime, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)

    class Complaint(db.Model):
        __tablename__ = "complaints"
        id = db.Column(db.Integer, primary_key=True)
        work_id = db.Column(db.Integer, db.ForeignKey("works.id"), index=True)
        reporter_id = db.Column(db.Integer, nullable=True)
        reason = db.Column(db.Text, nullable=False)
        status = db.Column(db.String(20), default="open")
        created_at = db.Column(db.DateTime, default=datetime.utcnow)

    class WorkLike(db.Model):
        __tablename__ = "work_likes"
        id = db.Column(db.Integer, primary_key=True)
        work_id = db.Column(db.Integer, db.ForeignKey("works.id"), index=True, nullable=False)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)
        __table_args__ = (db.UniqueConstraint("work_id", "user_id", name="uq_work_like_user"),)

    class AssistantMetric(db.Model):
        __tablename__ = "assistant_metrics"
        id = db.Column(db.Integer, primary_key=True)
        day_key = db.Column(db.String(10), index=True)
        total = db.Column(db.Integer, default=0)
        without_llm = db.Column(db.Integer, default=0)

    return {
        "Balance": Balance,
        "Ledger": Ledger,
        "CreatorProfile": CreatorProfile,
        "Work": Work,
        "FreeQuota": FreeQuota,
        "FxRate": FxRate,
        "LoginCode": LoginCode,
        "Complaint": Complaint,
        "WorkLike": WorkLike,
        "AssistantMetric": AssistantMetric,
    }
