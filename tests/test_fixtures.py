from datetime import datetime, timezone

ACTIVATION_URL = (
    "https://cloud.example.com/activate?code="
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJxYSs1ZTBjN2EzMUBleGFtcGxlLmNvbSIsImV4cCI6MTc5MDA3MjEwMn0."
    "26BhCE-jyNF95wsG0HxupxhABvmyoCh4tAMHIU_coy8&lang=en"
)
INVITATION_URL = (
    "https://cloud.example.com/invite/accept?token="
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJxYSs5YjI0ZDZmMEBleGFtcGxlLmNvbSIsInNpdGUiOiI2ZjFjMmE5ZS0zYjdk"
    "LTRlMGEtOWM1NS0wZDhlNGIxZjdhMjEifQ."
    "ZvBriYMfxEA-gE5GXoZz2kAJSn8Zq726s9t7PWaQ2AY"
    "&site=6f1c2a9e-3b7d-4e0a-9c55-0d8e4b1f7a21"
)


def test_activation_button_is_the_account_link(activation):
    assert activation.link("Activate account") == ACTIVATION_URL
    assert activation.link("www.example.com") == "https://www.example.com"
    assert activation.link("support.example.com") == "https://support.example.com"
    assert activation.link("Example Cloud") == (
        "https://cloud.example.com/?utm_source=email&utm_campaign=activation"
    )


def test_activation_headers_are_decoded(activation):
    assert activation.subject == "Activate your Example Cloud™ account"
    assert activation.sender == "noreply@cloud.example.com"
    assert activation.to == ("qa+5e0c7a31@example.com",)
    assert activation.date == datetime(2026, 9, 21, 10, 15, 2, tzinfo=timezone.utc)
    assert activation.message_id == "<20260921101502.4f8a2c61e9b3@cloud.example.com>"
    assert activation.addressed_to("QA+5E0C7A31@example.com")
    assert not activation.addressed_to("qa+5e0c7a3@example.com")
    assert not activation.addressed_to("qa+5e0c7a311@example.com")


def test_invitation_button_is_the_accept_link(invitation):
    assert invitation.link("Accept invitation") == INVITATION_URL
    assert invitation.link("Warehouse – North") == (
        "https://cloud.example.com/sites/6f1c2a9e-3b7d-4e0a-9c55-0d8e4b1f7a21"
    )
    assert invitation.link("Example Cloud") == "https://cloud.example.com/"


def test_invitation_headers_keep_the_display_name_off_the_address(invitation):
    assert invitation.subject == "José Müller invites you to Example Cloud™"
    assert invitation.sender == "noreply@cloud.example.com"
    assert invitation.to == ("qa+9b24d6f0@example.com",)
    assert invitation.addressed_to("qa+9b24d6f0@example.com")
    assert invitation.date == datetime(2026, 9, 21, 10, 42, 37, tzinfo=timezone.utc)
