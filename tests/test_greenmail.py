"""Wait against a real IMAP server.

These tests need GreenMail. Start it with ``docker compose up -d``.
They skip when nothing is listening, so ``pytest`` still passes without Docker.
"""

import imaplib
import smtplib
import socket
import threading
import time
from email.message import EmailMessage

import pytest

from mailfinder import EmailTimeout, Inbox

from mail import button

pytestmark = pytest.mark.integration

IMAP_HOST = "127.0.0.1"
IMAP_PORT = 3143
SMTP_PORT = 3025
ACCOUNT = "qa@example.com"


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection((IMAP_HOST, port), timeout=0.3):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def greenmail():
    if not _port_open(IMAP_PORT) or not _port_open(SMTP_PORT):
        pytest.skip("GreenMail is not running. Start it with: docker compose up -d")


def make_inbox() -> Inbox:
    return Inbox(
        IMAP_HOST,
        ACCOUNT,
        "qa",
        address=ACCOUNT,
        port=IMAP_PORT,
        ssl=False,
        poll_interval=0.2,
    )


def deliver(to_header: str, subject: str, html: str) -> None:
    """Put a message in the qa mailbox, keeping the plus-address on To.

    GreenMail does not fold plus-addresses the way Gmail does. The envelope
    recipient is the real account. The header still says qa+<tag>@example.com,
    which is what the library matches.
    """

    message = EmailMessage()
    message["From"] = "App <app@example.com>"
    message["To"] = to_header
    message["Subject"] = subject
    message.set_content("Open the HTML part.")
    message.add_alternative(html, subtype="html")
    # GreenMail stalls on EHLO when the client name is a .local hostname
    # it cannot resolve. "localhost" keeps the test server moving.
    with smtplib.SMTP(IMAP_HOST, SMTP_PORT, timeout=10, local_hostname="localhost") as smtp:
        smtp.send_message(
            message,
            from_addr="app@example.com",
            to_addrs=[ACCOUNT],
        )


def test_mail_already_in_the_box_is_returned(greenmail):
    client = make_inbox()
    address = client.unique_address()
    deliver(address, "Activate your account", button("Activate account", "https://example.com/a"))
    message = client.wait_for(address, timeout=10)
    assert message.link("Activate account") == "https://example.com/a"


def test_mail_that_arrives_during_the_wait_is_returned(greenmail):
    client = make_inbox()
    address = client.unique_address()

    def send_soon():
        time.sleep(0.5)
        deliver(address, "Activate your account", button("Activate account", "https://example.com/late"))

    thread = threading.Thread(target=send_soon)
    thread.start()
    try:
        message = client.wait_for(address, timeout=10)
    finally:
        thread.join()
    assert message.link("Activate account") == "https://example.com/late"


def test_parallel_waits_keep_their_own_mail(greenmail):
    client = make_inbox()
    first = client.unique_address()
    second = client.unique_address()
    deliver(first, "Activate", button("Activate account", "https://example.com/first"))
    deliver(second, "Invitation", button("Accept invitation", "https://example.com/second"))
    found = {}

    def wait(address, label):
        found[address] = client.wait_for(address, timeout=10).link(label)

    threads = [
        threading.Thread(target=wait, args=(first, "Activate account")),
        threading.Thread(target=wait, args=(second, "Accept invitation")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert found[first] == "https://example.com/first"
    assert found[second] == "https://example.com/second"


def test_newer_than_ignores_mail_that_was_already_there(greenmail):
    client = make_inbox()
    address = client.unique_address()
    deliver(address, "Reset your password", button("Reset password", "https://example.com/old"))
    mark = client.mark()
    deliver(address, "Reset your password", button("Reset password", "https://example.com/new"))
    message = client.wait_for(address, timeout=10, newer_than=mark)
    assert message.link("Reset password") == "https://example.com/new"


def test_timeout_when_nothing_arrives(greenmail):
    client = make_inbox()
    with pytest.raises(EmailTimeout):
        client.wait_for(client.unique_address(), timeout=0.6)


def test_reading_does_not_mark_the_message_seen(greenmail):
    client = make_inbox()
    address = client.unique_address()
    deliver(address, "Activate your account", button("Activate account", "https://example.com/a"))
    client.wait_for(address, timeout=10)
    with imaplib.IMAP4(IMAP_HOST, IMAP_PORT, timeout=10) as imap:
        imap.login(ACCOUNT, "qa")
        imap.select("INBOX", readonly=True)
        _typ, data = imap.uid("SEARCH", "TO", f'"{address}"')
        uid = data[0].split()[-1]
        _typ, fetched = imap.uid("FETCH", uid, "(FLAGS)")
    assert b"\\Seen" not in fetched[0]
