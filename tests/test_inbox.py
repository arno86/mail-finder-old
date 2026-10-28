import logging

import pytest

from mailfinder import EmailTimeout, Inbox, parse

from mail import button, raw_message


class MemoryMailbox:
    """A mailbox that speaks the same four operations as an IMAP session."""

    def __init__(self, *, search_works: bool = True):
        self.messages: list[bytes] = []
        self.validity = 1
        self.search_works = search_works

    def connect(self):
        return _Session(self)


class _Session:
    def __init__(self, box: MemoryMailbox):
        self.box = box

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def status(self):
        return self.box.validity, len(self.box.messages) + 1

    def search_to(self, recipient):
        if not self.box.search_works:
            return set()
        return {
            uid
            for uid, raw in enumerate(self.box.messages, start=1)
            if parse(raw).addressed_to(recipient)
        }

    def uids_from(self, start):
        return set(range(max(start, 1), len(self.box.messages) + 1))

    def fetch(self, uid):
        return self.box.messages[uid - 1]


def inbox(box: MemoryMailbox | None = None) -> tuple[Inbox, MemoryMailbox]:
    mailbox = box or MemoryMailbox()
    client = Inbox(
        "localhost",
        "qa@example.com",
        "secret",
        address="qa@example.com",
        ssl=False,
        poll_interval=0.01,
        connect=mailbox.connect,
    )
    return client, mailbox


def test_unique_address_is_a_fresh_plus_tag():
    client, _box = inbox()
    first = client.unique_address()
    second = client.unique_address()
    assert first.startswith("qa+")
    assert first.endswith("@example.com")
    assert first != second
    tagged = Inbox(
        "localhost",
        "qa",
        "secret",
        address="qa+already@example.com",
        ssl=False,
        connect=MemoryMailbox().connect,
    )
    assert tagged.unique_address().startswith("qa+")
    assert "+already" not in tagged.unique_address()


def test_mail_already_in_the_box_is_returned(caplog):
    client, box = inbox()
    address = client.unique_address()
    box.messages.append(
        raw_message(to=address, html=button("Activate account", "https://example.com/secret-link"))
    )
    with caplog.at_level(logging.INFO, logger="mailfinder"):
        message = client.wait_for(address, timeout=1)
    assert message.link("Activate account") == "https://example.com/secret-link"
    assert f"found message for {address}" in caplog.text
    assert "secret-link" not in caplog.text


def test_mail_that_arrives_during_the_wait_is_returned():
    client, box = inbox()
    address = client.unique_address()
    looks = {"count": 0}
    real_connect = box.connect

    def connect():
        looks["count"] += 1
        if looks["count"] == 2:
            box.messages.append(
                raw_message(to=address, html=button("Activate account", "https://example.com/late"))
            )
        return real_connect()

    client._connect = connect
    message = client.wait_for(address, timeout=2)
    assert message.link("Activate account") == "https://example.com/late"


def test_a_broken_address_search_still_reads_recent_mail():
    client, box = inbox(MemoryMailbox(search_works=False))
    address = client.unique_address()
    box.messages.append(
        raw_message(to=address, html=button("Activate account", "https://example.com/a"))
    )
    message = client.wait_for(address, timeout=1)
    assert message.link("Activate account") == "https://example.com/a"


def test_two_recipients_do_not_see_each_others_mail():
    client, box = inbox()
    first = client.unique_address()
    second = client.unique_address()
    box.messages.append(
        raw_message(to=first, html=button("Activate account", "https://example.com/first"))
    )
    box.messages.append(
        raw_message(to=second, html=button("Accept invitation", "https://example.com/second"))
    )
    assert client.wait_for(first, timeout=1).link("Activate account") == "https://example.com/first"
    assert client.wait_for(second, timeout=1).link("Accept invitation") == "https://example.com/second"


def test_the_newest_matching_message_wins():
    client, box = inbox()
    address = "qa+ada@example.com"
    box.messages.append(
        raw_message(to=address, html=button("Activate account", "https://example.com/old"))
    )
    box.messages.append(
        raw_message(to=address, html=button("Activate account", "https://example.com/new"))
    )
    assert client.wait_for(address, timeout=1).link("Activate account") == "https://example.com/new"


def test_newer_than_ignores_mail_that_was_already_there():
    client, box = inbox()
    address = "qa+ada@example.com"
    box.messages.append(
        raw_message(
            to=address,
            subject="Reset your password",
            html=button("Reset password", "https://example.com/old"),
        )
    )
    mark = client.mark()
    box.messages.append(
        raw_message(
            to=address,
            subject="Reset your password",
            html=button("Reset password", "https://example.com/new"),
        )
    )
    found = client.wait_for(address, timeout=1, newer_than=mark)
    assert found.link("Reset password") == "https://example.com/new"


def test_subject_filter_skips_other_mail_to_the_same_address():
    client, box = inbox()
    address = client.unique_address()
    box.messages.append(raw_message(to=address, subject="Welcome", plain="hi"))
    box.messages.append(
        raw_message(
            to=address,
            subject="Reset your password",
            html=button("Reset password", "https://example.com/reset"),
        )
    )
    found = client.wait_for(address, timeout=1, subject_contains="reset")
    assert found.link("Reset password") == "https://example.com/reset"


def test_timeout_names_the_messages_that_were_seen():
    client, box = inbox()
    box.messages.append(raw_message(to="qa+other@example.com", subject="Weekly digest"))
    with pytest.raises(EmailTimeout) as caught:
        client.wait_for("qa+missing@example.com", timeout=0.05)
    assert "qa+missing@example.com" in str(caught.value)
    assert "Weekly digest" in str(caught.value)


def test_a_refused_connection_is_tried_again():
    client, box = inbox()
    address = client.unique_address()
    box.messages.append(
        raw_message(to=address, html=button("Activate account", "https://example.com/a"))
    )
    attempts = {"count": 0}
    real_connect = box.connect

    def connect():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectionRefusedError("down")
        return real_connect()

    client._connect = connect
    assert client.wait_for(address, timeout=2).link("Activate account") == "https://example.com/a"


def test_delivered_to_is_enough_when_the_visible_to_was_rewritten():
    client, box = inbox()
    box.messages.append(
        raw_message(
            to="qa@example.com",
            delivered_to="qa+tag@example.com",
            html=button("Activate account", "https://example.com/a"),
        )
    )
    found = client.wait_for("qa+tag@example.com", timeout=1)
    assert found.link("Activate account") == "https://example.com/a"
