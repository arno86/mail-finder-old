"""Wait for one test's email in a shared IMAP mailbox."""

from __future__ import annotations

import imaplib
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

from mailfinder.errors import EmailTimeout, MailboxError
from mailfinder.message import Message, parse

# How many of the newest messages to read when the server's text search
# misses one. A message for the run that is happening now is in this window.
# Older matches depend on the server finding the address itself.
_RECENT_WINDOW = 100
_SOCKET_TIMEOUT_SECONDS = 15
log = logging.getLogger("mailfinder")


@dataclass(frozen=True)
class Mark:
    """How far the mailbox had gotten before the app was asked to send.

    ``uid_validity`` changes when the server rebuilds the mailbox. ``uid_next``
    is the number the server will give the next message that arrives. Mail
    already in the box has a smaller number. The values come from the server,
    so the clock on the machine running the test does not matter.
    """

    uid_validity: int
    uid_next: int


class Inbox:
    """One IMAP account a test reads while it waits for mail.

    The account is shared by every parallel run, and old messages stay in it.
    ``unique_address`` gives this run an address nobody else is using.
    ``wait_for`` returns the message sent to that address. It looks at mail
    already in the folder first, because the app may have sent it before the
    test started waiting.

    ``mark`` is for an address that is reused, such as a password reset.
    Call it before the app sends. Pass the result as ``newer_than`` so last
    run's message is ignored.

    Each look opens its own connection and closes it. Two waits can run at
    the same time. The library only reads: it does not delete mail, and it
    does not mark mail as seen.

    ``connect``, when passed, opens a session. Tests use an in-memory mailbox
    there. Left unset, the session is a real IMAP connection.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        address: str | None = None,
        port: int | None = None,
        ssl: bool = True,
        starttls: bool = False,
        folder: str = "INBOX",
        poll_interval: float = 0.5,
        connect: Callable[[], _Session] | None = None,
    ):
        """Store the connection settings. Nothing is contacted yet.

        ``ssl`` speaks IMAP over TLS from the start, which is what Gmail
        expects on port 993. ``starttls`` starts plain and upgrades, which
        is what many company servers expect on port 143. A lab server such
        as GreenMail often uses neither. ``address`` is the mailbox that
        receives plus-addresses, for example ``qa@example.com``. It defaults
        to ``username`` when that is an email address.
        """

        if ssl and starttls:
            raise ValueError("Use ssl or starttls, not both.")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive.")
        self.host = host
        self.username = username
        self._password = password
        self.address = address if address is not None else username
        self.port = port if port is not None else (993 if ssl else 143)
        self.ssl = ssl
        self.starttls = starttls
        self.folder = folder
        self.poll_interval = poll_interval
        self._connect = connect or self._open_imap

    def unique_address(self) -> str:
        """Return a plus-address that no other run is using.

        ``qa@example.com`` becomes ``qa+<random>@example.com``. An address
        that already has a plus-tag uses the part in front of the plus, so
        every generated address still lands in the same mailbox on a server
        that folds plus-addresses.
        """

        if "@" not in self.address:
            raise MailboxError(
                "Set address to the mailbox that receives mail, such as qa@example.com."
            )
        local, domain = self.address.split("@", 1)
        local = local.split("+", 1)[0]
        generated = f"{local}+{uuid.uuid4().hex}@{domain}"
        log.info("address for this run: %s", generated)
        return generated

    def mark(self) -> Mark:
        """Record the server's next message number.

        Call this before asking the app to send to an address that already
        has mail in the box.
        """

        with self._connect() as session:
            validity, uid_next = session.status()
        log.info("bookmark: next message number %s (validity %s)", uid_next, validity)
        return Mark(uid_validity=validity, uid_next=uid_next)

    def wait_for(
        self,
        recipient: str,
        *,
        timeout: float,
        subject_contains: str | None = None,
        newer_than: Mark | None = None,
    ) -> Message:
        """Return the newest message for ``recipient``, waiting up to ``timeout`` seconds.

        Mail that is already in the folder counts. When several messages
        match, the one with the highest server number is returned. That is
        the one that arrived last. ``subject_contains`` keeps a message only
        when that text appears in the subject, ignoring letter case.
        ``newer_than`` keeps a message only when it arrived after ``mark``.

        Raises ``EmailTimeout`` when nothing matched. The error lists
        subjects the wait did see. Raises ``MailboxError`` when the server
        rejects the login or the folder.
        """

        if timeout < 0:
            raise ValueError("timeout must be zero or positive.")
        log.info(
            "waiting up to %ss for %s%s%s",
            timeout,
            recipient,
            f" subject {subject_contains!r}" if subject_contains else "",
            f" newer than {newer_than.uid_next}" if newer_than else "",
        )
        deadline = time.monotonic() + timeout
        noticed: list[tuple[str, tuple[str, ...]]] = []
        checked: set[tuple[int, int]] = set()
        delay = self.poll_interval
        while True:
            try:
                found = self._look(
                    recipient, subject_contains, newer_than, checked, noticed
                )
            except MailboxError:
                raise
            except (imaplib.IMAP4.abort, OSError) as exc:
                log.warning("mailbox connection failed (%s); looking again", exc.__class__.__name__)
                found = None
            if found is not None:
                log.info(
                    "found message for %s subject %r",
                    recipient,
                    found.subject,
                )
                return found
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.info("gave up waiting for %s after %ss", recipient, timeout)
                raise EmailTimeout(
                    recipient, timeout, subject_contains, tuple(noticed)
                )
            time.sleep(min(delay, remaining))
            delay = min(delay * 1.5, 2.0)

    def _look(
        self,
        recipient: str,
        subject_contains: str | None,
        newer_than: Mark | None,
        checked: set[tuple[int, int]],
        noticed: list[tuple[str, tuple[str, ...]]],
    ) -> Message | None:
        """Read the folder once and return a match, or None."""

        with self._connect() as session:
            validity, uid_next = session.status()
            minimum = 1
            if newer_than is not None and newer_than.uid_validity == validity:
                minimum = newer_than.uid_next
            window = max(minimum, uid_next - _RECENT_WINDOW)
            # The address search is a hint. The recent numbers cover a server
            # whose search has not indexed a message that just arrived, and a
            # server that will not match a plus-address.
            uids = session.search_to(recipient) | session.uids_from(window)
            pending = sorted((uid for uid in uids if uid >= minimum), reverse=True)
            log.debug(
                "look for %s: %s candidate(s), next number %s",
                recipient,
                len(pending),
                uid_next,
            )
            for uid in pending:
                key = (validity, uid)
                if key in checked:
                    continue
                try:
                    raw = session.fetch(uid)
                except MailboxError:
                    checked.add(key)
                    continue
                message = parse(raw)
                checked.add(key)
                if not _matches(message, recipient, subject_contains):
                    log.debug("skip uid %s subject %r to %s", uid, message.subject, message.to)
                    _notice(noticed, message)
                    continue
                return message
        return None

    def _open_imap(self) -> ImapSession:
        """Open the real server configured on this inbox."""

        return ImapSession(
            self.host,
            self.port,
            self.username,
            self._password,
            ssl=self.ssl,
            starttls=self.starttls,
            folder=self.folder,
        )


class ImapSession:
    """One short IMAP login. Used as a context manager.

    The folder is opened read-only, and message bodies are fetched with
    ``BODY.PEEK``, which does not set the seen flag. Both choices matter
    when other tests are reading the same account.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        ssl: bool,
        starttls: bool,
        folder: str,
    ):
        """Remember how to log in. The socket opens in ``__enter__``."""

        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._ssl = ssl
        self._starttls = starttls
        self._folder = folder
        self._imap: imaplib.IMAP4 | None = None

    def __enter__(self) -> ImapSession:
        """Log in and open the folder read-only."""

        try:
            if self._ssl:
                imap: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                    self._host, self._port, timeout=_SOCKET_TIMEOUT_SECONDS
                )
            else:
                imap = imaplib.IMAP4(
                    self._host, self._port, timeout=_SOCKET_TIMEOUT_SECONDS
                )
                if self._starttls:
                    imap.starttls()
            imap.login(self._username, self._password)
            typ, _data = imap.select(self._folder, readonly=True)
            if typ != "OK":
                raise MailboxError(f"IMAP folder {self._folder!r} could not be opened.")
        except MailboxError:
            _close(imap)
            raise
        except imaplib.IMAP4.error as exc:
            _close(imap)
            raise MailboxError(
                f"IMAP login failed for {self._username} at {self._host}."
            ) from exc
        self._imap = imap
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Log out. An error from the wait is not swallowed."""

        imap = self._imap
        self._imap = None
        if imap is not None:
            _close(imap)
        return False

    def status(self) -> tuple[int, int]:
        """Return ``UIDVALIDITY`` and ``UIDNEXT`` for the open folder.

        Every IMAP server can report these. They are what ``mark`` stores.
        """

        imap = self._require()
        typ, data = imap.status(self._folder, "(UIDVALIDITY UIDNEXT)")
        if typ != "OK" or not data or not data[0]:
            raise MailboxError("The IMAP server did not report message numbers.")
        text = data[0].decode("utf-8", "replace") if isinstance(data[0], bytes) else str(data[0])
        validity = _status_number(text, "UIDVALIDITY")
        uid_next = _status_number(text, "UIDNEXT")
        if validity is None or uid_next is None:
            raise MailboxError("The IMAP server did not report message numbers.")
        return validity, uid_next

    def search_to(self, recipient: str) -> set[int]:
        """Ask the server which messages mention this recipient.

        An empty set means the server found nothing. It can also mean this
        server does not search that header well. Callers still read recent
        messages themselves.
        """

        try:
            return self._search("TO", f'"{recipient}"')
        except imaplib.IMAP4.error:
            return set()

    def uids_from(self, start: int) -> set[int]:
        """Return message numbers from ``start`` through the newest."""

        try:
            return self._search("UID", f"{max(start, 1)}:*")
        except imaplib.IMAP4.error:
            return set()

    def fetch(self, uid: int) -> bytes:
        """Return one raw message without marking it seen."""

        imap = self._require()
        typ, data = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if typ != "OK" or not data:
            raise MailboxError(f"IMAP message {uid} could not be read.")
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
        raise MailboxError(f"IMAP message {uid} could not be read.")

    def _search(self, key: str, value: str) -> set[int]:
        imap = self._require()
        typ, data = imap.uid("SEARCH", key, value)
        if typ != "OK" or not data or not data[0]:
            return set()
        blob = data[0] if isinstance(data[0], bytes) else str(data[0]).encode()
        if not blob.strip():
            return set()
        return {int(part) for part in blob.split()}

    def _require(self) -> imaplib.IMAP4:
        if self._imap is None:
            raise MailboxError("The IMAP session is not open.")
        return self._imap


class _Session(Protocol):
    """The methods ``Inbox`` needs from whatever it is connected to."""

    def __enter__(self) -> _Session: ...

    def __exit__(self, exc_type, exc, tb) -> bool: ...

    def status(self) -> tuple[int, int]: ...

    def search_to(self, recipient: str) -> set[int]: ...

    def uids_from(self, start: int) -> set[int]: ...

    def fetch(self, uid: int) -> bytes: ...


def _matches(message: Message, recipient: str, subject_contains: str | None) -> bool:
    if not message.addressed_to(recipient):
        return False
    if subject_contains is None:
        return True
    return subject_contains.casefold() in message.subject.casefold()


def _notice(noticed: list[tuple[str, tuple[str, ...]]], message: Message) -> None:
    item = (message.subject, message.to)
    if item not in noticed:
        noticed.append(item)
    del noticed[:-10]


def _status_number(text: str, name: str) -> int | None:
    match = re.search(rf"{name}\s+(\d+)", text, flags=re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1))


def _close(imap: imaplib.IMAP4) -> None:
    try:
        imap.logout()
    except (imaplib.IMAP4.error, OSError):
        try:
            imap.shutdown()
        except OSError:
            pass
