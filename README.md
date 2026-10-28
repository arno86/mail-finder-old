# mail-finder

Tests use this library to pick one email out of a shared mailbox and read the link on a button, such as Activate account or Accept invitation.

## Tests

Python 3.12 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

While the tests run, pytest prints a log of each wait: the address, the bookmark, and the subject of the message it kept. The body stays out of the log, because that is where the link is. A failed test still includes that log.

The button tests and the waiting tests that use an in-memory mailbox need no server:

```bash
pytest -m "not integration"
```

The tests that talk to a real IMAP server use GreenMail. Docker is only for that. The library itself is given a host, a port, and a login, and speaks ordinary IMAP.

```bash
docker compose up -d
pytest -m integration
```

GreenMail here has logins turned off, which is a convenience of that test server. Gmail is TLS on port 993 (`ssl=True`). Many company servers start plain and upgrade (`starttls=True`, port 143). GreenMail in this file is plain IMAP on port 3143 (`ssl=False`).

## Decisions

A test asks `unique_address` for a fresh `qa+<random>@example.com`. Parallel runs, including the same test on two machines, do not pick up each other's mail, and old mail left in the box does not match either.

`wait_for` looks in the folder first. The application may have sent the message before the test started waiting.

For an address that already has mail, such as a password reset, the test calls `mark` before the send and passes it as `newer_than`. The mark is the server's own next message number, so it stays right when the test machine and the mail server disagree about the clock.

A server's search for an address is only a hint. Servers differ on plus-addresses, and a message that just arrived is sometimes missing from search. The library reads the message and checks the address itself, and it also reads the recent messages so a slow search does not hide mail from this run.

The library only reads. It does not delete mail or mark it seen, because other tests are in the same account.

Asking the server to push new mail (IMAP IDLE) is left out. Plenty of servers do not offer it. Looking again until the timeout works on all of them.
