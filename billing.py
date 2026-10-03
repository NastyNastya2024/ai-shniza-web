"""Money in kopecks: hold / capture / release / topup with ledger."""
from __future__ import annotations

import json
from typing import Any, Optional


class InsufficientFunds(Exception):
    def __init__(self, need_kop: int, have_kop: int):
        self.need_kop = need_kop
        self.have_kop = have_kop
        super().__init__("insufficient_funds")


def get_or_create_balance(db, Balance, user_id: int):
    row = Balance.query.filter_by(user_id=user_id).first()
    if not row:
        row = Balance(user_id=user_id, balance_kop=0, held_kop=0)
        db.session.add(row)
        db.session.commit()
    return row


def available_kop(bal) -> int:
    return int(bal.balance_kop or 0) - int(bal.held_kop or 0)


def hold(
    db,
    Balance,
    Ledger,
    *,
    user_id: int,
    amount_kop: int,
    job_id: str,
    model_key: str,
    snapshot: Optional[dict] = None,
):
    if amount_kop < 0:
        raise ValueError("bad_amount")
    if amount_kop == 0:
        return get_or_create_balance(db, Balance, user_id)
    idem = f"hold:{job_id}"
    if Ledger.query.filter_by(idempotency_key=idem).first():
        return get_or_create_balance(db, Balance, user_id)
    bal = get_or_create_balance(db, Balance, user_id)
    if available_kop(bal) < amount_kop:
        raise InsufficientFunds(amount_kop, available_kop(bal))
    bal.held_kop = int(bal.held_kop or 0) + amount_kop
    db.session.add(
        Ledger(
            user_id=user_id,
            kind="hold",
            amount_kop=-amount_kop,
            model_key=model_key,
            job_id=job_id,
            price_snapshot=json.dumps(snapshot or {}, ensure_ascii=False),
            idempotency_key=idem,
        )
    )
    db.session.commit()
    return bal


def capture(db, Balance, Ledger, *, user_id: int, amount_kop: int, job_id: str, model_key: str = ""):
    idem = f"capture:{job_id}"
    if Ledger.query.filter_by(idempotency_key=idem).first():
        return get_or_create_balance(db, Balance, user_id)
    bal = get_or_create_balance(db, Balance, user_id)
    amount_kop = min(amount_kop, int(bal.held_kop or 0))
    bal.held_kop = int(bal.held_kop or 0) - amount_kop
    bal.balance_kop = int(bal.balance_kop or 0) - amount_kop
    db.session.add(
        Ledger(
            user_id=user_id,
            kind="capture",
            amount_kop=-amount_kop,
            model_key=model_key,
            job_id=job_id,
            idempotency_key=idem,
        )
    )
    db.session.commit()
    return bal


def release(db, Balance, Ledger, *, user_id: int, amount_kop: int, job_id: str, model_key: str = ""):
    idem = f"release:{job_id}"
    if Ledger.query.filter_by(idempotency_key=idem).first():
        return get_or_create_balance(db, Balance, user_id)
    bal = get_or_create_balance(db, Balance, user_id)
    amount_kop = min(amount_kop, int(bal.held_kop or 0))
    bal.held_kop = int(bal.held_kop or 0) - amount_kop
    db.session.add(
        Ledger(
            user_id=user_id,
            kind="release",
            amount_kop=amount_kop,
            model_key=model_key,
            job_id=job_id,
            idempotency_key=idem,
        )
    )
    db.session.commit()
    return bal


def topup(db, Balance, Ledger, *, user_id: int, amount_kop: int, idempotency_key: str, meta: Optional[dict] = None):
    if amount_kop <= 0:
        raise ValueError("bad_amount")
    if Ledger.query.filter_by(idempotency_key=idempotency_key).first():
        return get_or_create_balance(db, Balance, user_id)
    bal = get_or_create_balance(db, Balance, user_id)
    bal.balance_kop = int(bal.balance_kop or 0) + amount_kop
    db.session.add(
        Ledger(
            user_id=user_id,
            kind="topup",
            amount_kop=amount_kop,
            price_snapshot=json.dumps(meta or {}, ensure_ascii=False),
            idempotency_key=idempotency_key,
        )
    )
    db.session.commit()
    return bal


def ledger_sum(db, Ledger, user_id: int) -> int:
    """Net balance implied by ledger (topup/release positive, hold/capture negative — hold shouldn't double-count).

    Practical check: balance_kop should equal sum(topup+refund+adjust+release_capture_net).
    We store hold as separate held_kop; ledger hold is informational.
    """
    rows = Ledger.query.filter_by(user_id=user_id).all()
    total = 0
    for r in rows:
        if r.kind in {"topup", "refund", "adjust"}:
            total += int(r.amount_kop)
        elif r.kind == "capture":
            total += int(r.amount_kop)  # already negative
    return total
