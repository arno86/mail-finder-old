"""Turn a raw email into a message a test can read."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from mailfinder.links import Link, links_from_html, links_from_text, url_for_label

# Headers a receiving server may use for the address the app actually sent to.
# To and Cc are standard. The others show up when a relay rewrites To.
_ADDRESS_HEADERS = (
    "to",
    "cc",
    "delivered-to",
    "x-original-to",
    "envelope-to",
    "x-envelope-to",
)


@dataclass(frozen=True)
class Message:
    """One email, already decoded, ready for a test to read.

    ``subject``, ``sender``, ``to``, ``date``, and ``message_id`` come from
    the headers. Encoded words such as ``=?utf-8?...?=`` are already turned
    into normal text, so a subject can contain ``™`` or ``José``. ``sender``
    is the address only, without the display name. ``to`` is the addresses
    on the To line, in order.

    ``text`` and ``html`` are the decoded bodies. Either one can be missing.
    ``links`` is every clickable item taken from the HTML, or from the plain
    text when there is no HTML.

    ``link`` returns the URL behind a button. The label is the words on the
    button, so "Activate account" is that button and not the footer.
    """

    subject: str
    sender: str
    to: tuple[str, ...]
    date: datetime | None
    message_id: str | None
    text: str | None
    html: str | None
    links: tuple[Link, ...] = field(repr=False)
    # Every address we are willing to match, including delivery headers that
    # a server adds when it rewrites the visible To line. Kept off the repr
    # because tests read it through addressed_to.
    _match_addresses: tuple[str, ...] = field(repr=False)

    def link(self, label: str) -> str:
        """Return the URL of the button whose visible text is ``label``.

        Raises ``LinkNotFound`` when no button has that text, and
        ``AmbiguousLink`` when the text points at two different URLs.
        """

        return url_for_label(self.links, label)

    def addressed_to(self, recipient: str) -> bool:
        """True when this exact address is written on the message.

        The check looks at To, Cc, and the delivery headers a relay may add
        (Delivered-To, X-Original-To, Envelope-To). Letter case is ignored.
        A shorter or longer plus-tag does not match: ``qa+abc`` is a
        different recipient from ``qa+abcd``.
        """

        wanted = recipient.casefold()
        return any(address.casefold() == wanted for address in self._match_addresses)


def parse(raw: bytes) -> Message:
    """Decode a raw RFC 822 message into a ``Message``.

    Quoted-printable and base64 bodies are decoded, and header encoding is
    undone. The button list comes from the HTML part. The plain part is
    used only when the message has no HTML, because it often describes the
    same link in different words. On the invitation sample, the plain text
    says "Accept the invitation" and the button says "Accept invitation".
    """

    parsed = message_from_bytes(raw, policy=policy.default)
    if not isinstance(parsed, EmailMessage):
        raise TypeError("expected a parsed email message")
    text, html = _bodies(parsed)
    extracted = links_from_html(html) if html is not None else links_from_text(text or "")
    _name, sender = parseaddr(parsed.get("from", ""))
    return Message(
        subject=str(parsed.get("subject") or ""),
        sender=sender,
        to=_addresses(parsed, ("to",)),
        date=_date(parsed),
        message_id=_optional_header(parsed, "message-id"),
        text=text,
        html=html,
        links=tuple(extracted),
        _match_addresses=_addresses(parsed, _ADDRESS_HEADERS),
    )


def _bodies(message: EmailMessage) -> tuple[str | None, str | None]:
    """Return the plain-text body and the HTML body.

    Either value is ``None`` when that part is absent. A nested
    ``multipart/related`` part, such as the invitation's inline logo, still
    yields the HTML document. The image itself is left alone.
    """

    return (
        _text(message.get_body(preferencelist=("plain",))),
        _text(message.get_body(preferencelist=("html",))),
    )


def _text(part: EmailMessage | None) -> str | None:
    """Return a part's decoded text, or ``None`` when there is nothing to read.

    ``get_content`` undoes the transfer encoding and the charset. A part
    that decodes to bytes, such as the logo image, is not text and is
    skipped.
    """

    if part is None:
        return None
    content = part.get_content()
    if isinstance(content, str):
        return content
    return None


def _addresses(message: EmailMessage, headers: tuple[str, ...]) -> tuple[str, ...]:
    """Pull email addresses out of the named headers, in the order found.

    Display names are dropped, so ``Anna Schmidt <qa+id@example.com>``
    contributes ``qa+id@example.com``. The same address twice, differing
    only by case, is kept once, in the spelling seen first.
    """

    values: list[str] = []
    for name in headers:
        values.extend(message.get_all(name, []))
    found: list[str] = []
    seen: set[str] = set()
    for _name, address in getaddresses(values):
        address = address.strip()
        if not address:
            continue
        key = address.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(address)
    return tuple(found)


def _date(message: EmailMessage) -> datetime | None:
    """Parse the Date header into an aware datetime.

    Returns ``None`` when the header is missing or garbled. A bad date
    should not stop the test from reading the button.
    """

    raw = message.get("date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError):
        return None


def _optional_header(message: EmailMessage, name: str) -> str | None:
    """Return one header as a stripped string, or ``None`` when it is absent."""

    value = message.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None
