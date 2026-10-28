from email.message import EmailMessage

import pytest

from mailfinder import AmbiguousLink, LinkNotFound, parse


def build(*, html: str | None = None, plain: str | None = None, headers=None):
    message = EmailMessage()
    message["From"] = "Example Cloud <noreply@example.com>"
    message["To"] = "qa+one@example.com"
    message["Subject"] = "Hello"
    if headers:
        for name, value in headers:
            message[name] = value
    if plain is not None and html is not None:
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
    elif html is not None:
        message.set_content(html, subtype="html")
    else:
        message.set_content(plain or "")
    return parse(message.as_bytes())


def test_button_label_ignores_case_and_odd_spaces():
    message = build(html='<a href="https://example.com/a">Activate&nbsp;account</a>')
    assert message.link("activate   account") == "https://example.com/a"


def test_words_split_across_tags_are_one_label():
    message = build(
        html='<a href="https://example.com/a"><span>Accept</span> invitation</a>'
    )
    assert message.link("Accept invitation") == "https://example.com/a"


def test_the_same_button_twice_is_one_link():
    message = build(
        html=(
            '<a href="https://example.com/a">Activate account</a>'
            '<a href="https://example.com/a">Activate account</a>'
        )
    )
    assert message.link("Activate account") == "https://example.com/a"


def test_two_urls_for_one_label_are_reported():
    message = build(
        html=(
            '<a href="https://example.com/one">Activate account</a>'
            '<a href="https://example.com/two">Activate account</a>'
        )
    )
    with pytest.raises(AmbiguousLink) as caught:
        message.link("Activate account")
    assert caught.value.urls == ("https://example.com/one", "https://example.com/two")


def test_a_missing_label_names_the_links_that_exist(activation):
    with pytest.raises(LinkNotFound) as caught:
        activation.link("Reset password")
    assert "Activate account" in caught.value.available
    assert "www.example.com" in caught.value.available


def test_html_button_wins_when_the_plain_part_uses_different_words():
    message = build(
        plain="Accept the invitation: https://example.com/plain",
        html='<a href="https://example.com/html">Accept invitation</a>',
    )
    assert message.link("Accept invitation") == "https://example.com/html"
    with pytest.raises(LinkNotFound):
        message.link("Accept the invitation")


def test_plain_text_uses_the_words_on_the_same_line():
    message = build(plain="Accept the invitation: https://example.com/a\n")
    assert message.link("Accept the invitation") == "https://example.com/a"


def test_delivered_to_counts_when_the_visible_to_was_rewritten():
    message = build(
        plain="Hello",
        headers=[("Delivered-To", "qa+tag@example.com")],
    )
    assert message.to == ("qa+one@example.com",)
    assert message.addressed_to("qa+tag@example.com")
    assert not message.addressed_to("qa+tag-other@example.com")
