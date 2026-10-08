import os
import smtplib
from email.mime.text import MIMEText


def send_verification_email(email: str, code: str, ttl_minutes: int = 15) -> tuple[bool, str]:
    """Send a one-time verification code to `email` via SMTP.

    Credentials come from SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS in the
    environment (.env). If they aren't configured, verification can't
    happen, so registration is refused rather than silently skipping it.
    """
    host = os.environ.get("SMTP_HOST")
    port = os.environ.get("SMTP_PORT")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")

    if not all([host, port, user, password]):
        return False, "Email verification is not configured on this server. Contact your administrator."

    msg = MIMEText(
        f"Your SNOW ARC verification code is: {code}\n\n"
        f"This code expires in {ttl_minutes} minutes. If you didn't request this, you can ignore this email."
    )
    msg["Subject"] = "Your SNOW ARC verification code"
    msg["From"] = user
    msg["To"] = email

    try:
        with smtplib.SMTP(host, int(port), timeout=10) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [email], msg.as_string())
        return True, "Verification code sent."
    except Exception as e:
        return False, f"Failed to send verification email: {e}"
