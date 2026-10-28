from pathlib import Path

import pytest

from mailfinder import Message, parse

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def activation() -> Message:
    return parse((FIXTURES / "activation.eml").read_bytes())


@pytest.fixture
def invitation() -> Message:
    return parse((FIXTURES / "site_invitation.eml").read_bytes())
