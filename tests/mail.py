"""Build raw messages for tests."""

from email.message import EmailMessage


def raw_message(
    *,
    to: str,
    subject: str = "Hello",
    html: str | None = None,
    plain: str | None = None,
    delivered_to: str | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = "App <app@example.com>"
    message["To"] = to
    message["Subject"] = subject
    if delivered_to is not None:
        message["Delivered-To"] = delivered_to
    if html is not None and plain is not None:
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
    elif html is not None:
        message.set_content(html, subtype="html")
    else:
        message.set_content(plain or "")
    return message.as_bytes()


def button(label: str, url: str) -> str:
    return f'<a href="{url}">{label}</a>'
