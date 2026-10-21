""" Email LabRats staff when a website form is submitted (the old WordPress forms did this).

Configured with environment variables (see __init__.py). When LABRATS_NOTIFY_TO or SMTP_HOST is
unset, notification is skipped and the inquiry is only stored; a failed send never loses data
because the inquiry is saved before this runs.
"""
import smtplib
from email.message import EmailMessage

FORM_TITLES = {
    "contact": "Contact form",
    "scholarship": "Scholarship application",
    "partnership": "Corporate partnership request",
    "video_topic": "Video topic request",
    "newsletter": "Newsletter signup",
}


def build_notification(inquiry, sender, recipients):
    """Return the EmailMessage for one stored inquiry (a LabRatsInquiry.read() dict)."""
    message = EmailMessage()
    title = FORM_TITLES.get(inquiry["form"], inquiry["form"])
    message["Subject"] = f"[sdlabrats.org] {title} from {inquiry['first_name']} {inquiry['last_name']}"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Reply-To"] = inquiry["email"]

    lines = [
        f"{title} received {inquiry['created_at']} (inquiry #{inquiry['id']})",
        "",
        f"Name: {inquiry['first_name']} {inquiry['last_name']}",
        f"Email: {inquiry['email']}",
    ]
    if inquiry.get("phone"):
        lines.append(f"Phone: {inquiry['phone']}")
    for key, value in inquiry["details"].items():
        shown = ", ".join(value) if isinstance(value, list) else value
        lines.append(f"{key.replace('_', ' ').capitalize()}: {shown}")
    lines += ["", "Reply to this email to answer them. All submissions: /labrats/inquiries/"]
    message.set_content("\n".join(lines))
    return message


def notify_staff(inquiry, config, logger):
    """Send the notification. Returns True when sent, False when skipped or failed."""
    recipients = [address.strip() for address in (config.get("LABRATS_NOTIFY_TO") or "").split(",") if address.strip()]
    host = config.get("SMTP_HOST")
    if not recipients or not host:
        logger.info("LabRats inquiry %s stored; email notification not configured", inquiry["id"])
        return False

    sender = config.get("SMTP_FROM") or config.get("SMTP_USER") or recipients[0]
    message = build_notification(inquiry, sender, recipients)
    try:
        with smtplib.SMTP(host, int(config.get("SMTP_PORT") or 587), timeout=10) as server:
            server.starttls()
            if config.get("SMTP_USER"):
                server.login(config["SMTP_USER"], config.get("SMTP_PASSWORD") or "")
            server.send_message(message)
        return True
    except (smtplib.SMTPException, OSError) as error:
        logger.error("LabRats inquiry %s stored but email notification failed: %s", inquiry["id"], error)
        return False
