"""Errors a test can catch when mail or a button is missing."""


class MailfinderError(Exception):
    """Base class for every error this library raises on purpose.

    A test can catch this one type when it does not care which failure it
    was: the mailbox rejected the login, the email never arrived, a button
    was missing, or a label pointed at two different URLs.
    """


class LinkNotFound(MailfinderError):
    """The message was read, and it has no button with the requested label.

    ``label`` is the text the test asked for. ``available`` is the button
    text that really was on the message, in the order the links appear, so
    a failure can show what the mail contained.
    """

    def __init__(self, label: str, available: tuple[str, ...]):
        """Store the missing label and the labels that were present."""

        self.label = label
        self.available = available
        if available:
            found = ", ".join(repr(item) for item in available)
            detail = f"Links present: {found}."
        else:
            detail = "The message has no links."
        super().__init__(f"No link with label {label!r}. {detail}")


class AmbiguousLink(MailfinderError):
    """The same label is attached to two different URLs.

    The library refuses to pick one, because the test would open the wrong
    page. The same button repeated with the same URL is a single link and
    does not raise. ``urls`` lists the different targets, in document order.
    """

    def __init__(self, label: str, urls: tuple[str, ...]):
        """Store the shared label and the URLs it points at."""

        self.label = label
        self.urls = urls
        choices = ", ".join(urls)
        super().__init__(f"Label {label!r} points at more than one URL: {choices}.")


class MailboxError(MailfinderError):
    """The server rejected the connection, the login, or the folder.

    These failures are not retried. A wrong password will not start working
    if the test keeps asking.
    """


class EmailTimeout(MailfinderError, TimeoutError):
    """The mailbox was checked until the timeout, and no message matched.

    ``noticed`` lists subjects and recipients the library did see, so a
    failing test can show what was in the box. Message bodies are left out,
    because they contain the links the test is waiting on.
    """

    def __init__(
        self,
        recipient: str,
        timeout: float,
        subject_contains: str | None,
        noticed: tuple[tuple[str, tuple[str, ...]], ...],
    ):
        """Build the timeout from the search and the messages that did not match."""

        self.recipient = recipient
        self.timeout = timeout
        self.subject_contains = subject_contains
        self.noticed = noticed
        if subject_contains is None:
            summary = f"No email for {recipient} within {timeout:g}s."
        else:
            summary = (
                f"No email for {recipient} with subject containing "
                f"{subject_contains!r} within {timeout:g}s."
            )
        lines = [summary]
        if noticed:
            lines.append("Messages seen:")
            for subject, recipients in noticed:
                who = ", ".join(recipients) or "(no recipient)"
                lines.append(f"- {subject or '(no subject)'} | to={who}")
        else:
            lines.append("No recent messages were read during the wait.")
        super().__init__("\n".join(lines))
