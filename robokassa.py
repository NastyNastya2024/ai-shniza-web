"""Robokassa payment provider (interface + ResultURL verification)."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode


@dataclass
class PaymentStart:
    inv_id: str
    amount_rub: float
    pay_url: str


class PaymentProvider:
    def start_topup(self, *, user_id: int, amount_kop: int, inv_id: str, description: str) -> PaymentStart:
        raise NotImplementedError

    def verify_result(self, form: dict) -> dict:
        raise NotImplementedError


class RobokassaProvider(PaymentProvider):
    def __init__(self):
        self.login = (os.getenv("ROBOKASSA_MERCHANT_LOGIN") or "").strip()
        self.pass1 = (os.getenv("ROBOKASSA_PASSWORD1") or "").strip()
        self.pass2 = (os.getenv("ROBOKASSA_PASSWORD2") or "").strip()
        self.is_test = (os.getenv("ROBOKASSA_TEST") or "1").strip() in {"1", "true", "yes"}

    def configured(self) -> bool:
        return bool(self.login and self.pass1 and self.pass2)

    def start_topup(self, *, user_id: int, amount_kop: int, inv_id: str, description: str) -> PaymentStart:
        if amount_kop < 10000:
            raise ValueError("min_topup_100_rub")
        out_sum = f"{amount_kop / 100:.2f}"
        sign_str = f"{self.login}:{out_sum}:{inv_id}:{self.pass1}"
        signature = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
        params = {
            "MerchantLogin": self.login,
            "OutSum": out_sum,
            "InvId": inv_id,
            "Description": description[:100],
            "SignatureValue": signature,
            "Culture": "ru",
        }
        if self.is_test:
            params["IsTest"] = "1"
        base = "https://auth.robokassa.ru/Merchant/Index.aspx"
        return PaymentStart(inv_id=inv_id, amount_rub=amount_kop / 100, pay_url=f"{base}?{urlencode(params)}")

    def verify_result(self, form: dict) -> dict:
        out_sum = str(form.get("OutSum") or "")
        inv_id = str(form.get("InvId") or "")
        signature = str(form.get("SignatureValue") or "").lower()
        expected = hashlib.md5(f"{out_sum}:{inv_id}:{self.pass2}".encode("utf-8")).hexdigest().lower()
        if not inv_id or signature != expected:
            raise ValueError("bad_signature")
        amount_kop = int(round(float(out_sum.replace(",", ".")) * 100))
        return {"inv_id": inv_id, "amount_kop": amount_kop}


def get_payment_provider() -> RobokassaProvider:
    return RobokassaProvider()
