"""Find a test email and read the link on its button."""

from mailfinder.errors import (
    AmbiguousLink,
    EmailTimeout,
    LinkNotFound,
    MailboxError,
    MailfinderError,
)
from mailfinder.inbox import Inbox, Mark
from mailfinder.links import Link
from mailfinder.message import Message, parse

__all__ = [
    "AmbiguousLink",
    "EmailTimeout",
    "Inbox",
    "Link",
    "LinkNotFound",
    "MailboxError",
    "MailfinderError",
    "Mark",
    "Message",
    "parse",
]
