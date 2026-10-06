"""Login-code email: HTTPS (Resend) preferred, SMTP fallback (Yandex etc.)."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_ASSETS = Path(__file__).resolve().parent / "mail-assets"
_INLINE_CACHE: Optional[list[tuple[str, str, bytes]]] = None


def smtp_configured() -> bool:
    """True if any outbound mail transport is configured."""
    if (os.getenv("RESEND_API_KEY") or "").strip():
        return True
    return bool((os.getenv("SMTP_HOST") or "").strip()) and bool(
        (os.getenv("SMTP_PASS") or os.getenv("MAIL_PASS") or "").strip()
    )


def _cfg() -> dict[str, str | int | bool]:
    host = (os.getenv("SMTP_HOST") or "").strip()
    port = int(os.getenv("SMTP_PORT") or "465")
    user = (os.getenv("SMTP_USER") or os.getenv("MAIL_FROM") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or user).strip()
    password = (os.getenv("SMTP_PASS") or os.getenv("MAIL_PASS") or "").strip()
    from_name = (os.getenv("MAIL_FROM_NAME") or "{AI}-шница").strip()
    secure_raw = (os.getenv("SMTP_SECURE") or "").strip().lower()
    if secure_raw in ("0", "false", "no"):
        secure = False
    elif secure_raw in ("1", "true", "yes"):
        secure = True
    else:
        secure = port == 465
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from": mail_from,
        "from_name": from_name,
        "secure": secure,
    }


def _brand() -> str:
    return (os.getenv("MAIL_FROM_NAME") or "{AI}-шница").strip()


def _site_url() -> str:
    return (os.getenv("BASE_URL") or os.getenv("DOMAIN") or "").strip().rstrip("/")


def _inline_images() -> list[tuple[str, str, bytes]]:
    global _INLINE_CACHE
    if _INLINE_CACHE is not None:
        return _INLINE_CACHE
    out: list[tuple[str, str, bytes]] = []
    for cid, name in (("sunny@aishnitsa", "sunny.png"), ("logo@aishnitsa", "logo.png")):
        path = _ASSETS / name
        try:
            out.append((cid, name, path.read_bytes()))
        except OSError:
            pass
    if not out:
        log.warning("[mail] mail-assets/ missing — sending without inline images")
    _INLINE_CACHE = out
    return out


def login_code_mail(to: str, code: str) -> tuple[str, str, str, list[tuple[str, str, bytes]]]:
    brand = _brand()
    site_url = _site_url()
    subject = f"{code} — ваш код для входа"
    text = (
        f"Здравствуйте!\n\nВаш код для входа: {code}\n\n"
        "Код действует 10 минут. Никому его не сообщайте — наша команда никогда не спрашивает коды.\n"
        "Если вы не запрашивали вход, просто проигнорируйте это письмо.\n\n"
        f"— {brand}, маркетплейс генеративных моделей"
    )
    if site_url:
        text += f"\n{site_url}"

    inline = _inline_images()
    img = len(inline) > 0
    digits = "".join(
        f'<td style="padding:0 3px"><div style="width:44px;height:56px;line-height:56px;border-radius:14px;'
        f'background:#ffffff;border:1.5px solid #E6DDFB;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;'
        f'font-size:30px;font-weight:800;color:#3B1FB0;text-align:center;'
        f'box-shadow:0 6px 14px -8px rgba(91,53,224,.35)">{d}</div></td>'
        for d in code
    )
    logo_cell = (
        f'<img src="cid:logo@aishnitsa" width="158" height="32" alt="{brand}" '
        f'style="display:block;border:0;width:158px;height:32px">'
        if img
        else f'<span style="font:800 22px Arial,sans-serif;color:#FF7B2C">{brand}</span>'
    )
    sunny_block = (
        '<img src="cid:sunny@aishnitsa" width="150" height="150" alt="Яишенка" '
        'style="display:block;border:0;width:150px;height:150px;margin:2px auto 0">'
        if img
        else ""
    )
    site_footer = ""
    if site_url:
        display = site_url.replace("https://", "").replace("http://", "")
        site_footer = (
            f'<br><a href="{site_url}" style="color:#5B35E0;text-decoration:none;font-weight:700">{display}</a>'
        )
    brand_footer = brand.replace("-", "&#8209;")

    html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{subject}</title></head>
<body style="margin:0;padding:0;background:#F4EEFF">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">Код для входа: {code}. Действует 10 минут.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#F4EEFF" style="background:#F4EEFF;background-image:linear-gradient(160deg,#FFF1E6 0%,#F7EEFF 45%,#EEF0FF 100%)">
<tr><td align="center" style="padding:28px 14px 36px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px">
    <tr><td align="center" style="padding:0 0 18px">{logo_cell}</td></tr>
  </table>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="max-width:480px;background:#ffffff;border-radius:28px;box-shadow:0 30px 60px -40px rgba(60,30,120,.45);overflow:hidden">
    <tr><td align="center" style="padding:26px 24px 0;background:#FFF4EC;background-image:linear-gradient(180deg,#FFE9DA 0%,#FFF3F8 70%,#ffffff 100%)">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td align="center" style="background:#ffffff;border-radius:18px;padding:11px 18px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:16px;font-weight:700;color:#1E1238;box-shadow:0 10px 24px -14px rgba(232,105,28,.5)">Здравствуйте! Ваш код уже здесь&nbsp;✨</td></tr>
      <tr><td align="center" style="font-size:0;line-height:0"><div style="width:0;height:0;border-left:9px solid transparent;border-right:9px solid transparent;border-top:9px solid #ffffff;margin:0 auto"></div></td></tr></table>
      {sunny_block}
    </td></tr>
    <tr><td align="center" style="padding:6px 28px 0;font-family:'Segoe UI',Arial,Helvetica,sans-serif">
      <div style="font-size:24px;line-height:1.25;font-weight:800;color:#1E1238">Код для входа</div>
      <div style="padding-top:6px;font-size:15px;line-height:1.5;color:#6B5E8C">Введите его на странице входа</div>
    </td></tr>
    <tr><td align="center" style="padding:22px 16px 6px">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="background:#F6F1FF;border-radius:20px"><tr><td style="padding:14px 11px"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{digits}</tr></table></td></tr></table>
    </td></tr>
    <tr><td align="center" style="padding:10px 28px 0;font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:13px;color:#9A90B5">
      Чтобы скопировать: <span style="font-family:Menlo,Consolas,monospace;font-size:15px;font-weight:700;color:#5B35E0;letter-spacing:2px">{code}</span>
    </td></tr>
    <tr><td align="center" style="padding:18px 28px 0">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td style="background:#FFF1E4;border-radius:999px;padding:8px 14px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:13px;font-weight:700;color:#C2560F">⏱ Действует 10 минут</td></tr></table>
    </td></tr>
    <tr><td style="padding:24px 28px 26px">
      <div style="height:1px;background:#EEE7FB;line-height:1px;font-size:0">&nbsp;</div>
      <div style="padding-top:18px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:13px;line-height:1.55;color:#7A6F98">
        Никому не сообщайте этот код — наша команда никогда его не спрашивает.<br>
        Если вы не запрашивали вход, просто проигнорируйте письмо.
      </div>
    </td></tr>
  </table>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px">
    <tr><td align="center" style="padding:20px 20px 0;font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6;color:#9A90B5">
      {brand_footer} — маркетплейс генеративных моделей<br>
      Видео, картинки и музыка — лучшая модель по лучшей цене{site_footer}
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""
    return subject, text, html, inline


def _send_via_resend(to: str, subject: str, text: str, html: str) -> None:
    import requests

    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    cfg = _cfg()
    from_addr = str(cfg["from"]) or (os.getenv("RESEND_FROM") or "").strip()
    from_name = str(cfg["from_name"])
    if not from_addr:
        raise RuntimeError("MAIL_FROM / RESEND_FROM not configured")
    sender = f"{from_name} <{from_addr}>" if from_name else from_addr
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"from": sender, "to": [to], "subject": subject, "html": html, "text": text},
        timeout=15,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Resend HTTP {r.status_code}: {r.text[:300]}")
    log.info("[mail] login code sent via Resend to %s", to)


def _send_via_smtp(to: str, subject: str, text: str, html: str, inline: list[tuple[str, str, bytes]]) -> None:
    cfg = _cfg()
    if not cfg["host"]:
        raise RuntimeError("SMTP_HOST not configured")
    if not cfg["from"] or not cfg["password"]:
        raise RuntimeError("MAIL_FROM / SMTP_PASS not configured")

    from_addr = str(cfg["from"])
    from_name = str(cfg["from_name"])

    if inline:
        root = MIMEMultipart("related")
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text, "plain", "utf-8"))
        alt.attach(MIMEText(html, "html", "utf-8"))
        root.attach(alt)
        for cid, filename, data in inline:
            img = MIMEImage(data, _subtype=filename.rsplit(".", 1)[-1])
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=filename)
            root.attach(img)
        msg = root
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1] or "localhost")

    host = str(cfg["host"])
    port = int(cfg["port"])
    user = str(cfg["user"])
    password = str(cfg["password"])
    timeout = int(os.getenv("SMTP_TIMEOUT") or "8")

    if cfg["secure"]:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=timeout) as smtp:
            if user:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            if user:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to], msg.as_string())

    log.info("[mail] login code sent via SMTP to %s", to)


def send_login_code(to: str, code: str) -> None:
    subject, text, html, inline = login_code_mail(to, code)
    # Prefer HTTPS: many home networks block outbound SMTP (465/587).
    if (os.getenv("RESEND_API_KEY") or "").strip():
        _send_via_resend(to, subject, text, html)
        return
    _send_via_smtp(to, subject, text, html, inline)
