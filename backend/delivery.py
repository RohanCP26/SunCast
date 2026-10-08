"""Send a password-reset code by email or text.

Email uses SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and SMTP_FROM.
Texts use TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER.
Neither channel is attempted when its settings are missing.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import requests


def smtp_ready() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def sms_ready() -> bool:
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID")
        and os.getenv("TWILIO_AUTH_TOKEN")
        and os.getenv("TWILIO_FROM_NUMBER")
    )


def deliver_reset_code(email: str, phone: str, code: str) -> bool:
    """Send the code to the account email, or by text when there is no email."""
    body = (
        f"Your SunCast code is {code}. It expires in 15 minutes. "
        "If you did not ask to reset your password, you can ignore this message."
    )
    if email and smtp_ready():
        _send_email(email, "Your SunCast password code", body)
        return True
    if phone and sms_ready():
        _send_sms(phone, body)
        return True
    if email or phone:
        print("Password reset could not be delivered. Set SMTP or Twilio environment variables.")
    return False


def deliver_report(subject: str, body: str) -> None:
    """Email a new report to REPORT_EMAIL when SMTP is configured."""
    target = os.getenv("REPORT_EMAIL", "paranjape.ro@northeastern.edu")
    if not target or not smtp_ready():
        return
    _send_email(target, subject, body)


def _send_email(to_addr: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = os.getenv("SMTP_FROM")
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(body)
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password or "")
        smtp.send_message(message)


def _send_sms(phone: str, body: str) -> None:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    response = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data={"To": f"+{digits}", "From": os.getenv("TWILIO_FROM_NUMBER"), "Body": body},
        auth=(sid, token),
        timeout=20,
    )
    response.raise_for_status()
