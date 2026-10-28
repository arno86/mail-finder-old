"""Read the URL behind a button from an HTML or plain-text body."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

from bs4 import BeautifulSoup

from mailfinder.errors import AmbiguousLink, LinkNotFound

# A URL running to the end of a line, or up to a quote or angle bracket.
_URL = re.compile(r"https?://[^\s<>\"']+")
# Characters mail clients drop into button text that a person never sees.
_INVISIBLE = str.maketrans("", "", "\u200b\u200c\u200d\ufeff\u00ad")


@dataclass(frozen=True)
class Link:
    """One thing a person could click inside the message.

    ``label`` is the visible text of the link. When the link is only a
    picture, such as the logo, the label is that picture's alt text.
    ``url`` is the address the click opens, with HTML escapes already
    turned back into normal characters (``&amp;`` becomes ``&``).
    """

    label: str
    url: str


def links_from_html(html: str) -> list[Link]:
    """Collect every anchor in the HTML, in the order they appear.

    An anchor with no ``href`` is skipped. The same label and the same URL
    repeated later in the message, which Outlook-style mail often does, is
    kept once.
    """

    soup = BeautifulSoup(html, "html.parser")
    found: list[Link] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        url = unescape(href).strip()
        label = _anchor_label(anchor)
        key = (normalize(label), url)
        if key in seen:
            continue
        seen.add(key)
        found.append(Link(label=label, url=url))
    return found


def links_from_text(text: str) -> list[Link]:
    """Collect URLs from a plain-text body, one line at a time.

    The label is the words on that line before the URL, with a trailing
    colon removed. ``Accept the invitation: https://...`` becomes a link
    labeled "Accept the invitation". A URL sitting on a line by itself has
    an empty label. Used only when the message has no HTML part.
    """

    found: list[Link] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        match = _URL.search(line)
        if match is None:
            continue
        url = match.group(0).rstrip(".,)")
        label = collapse(line[: match.start()].strip(" \t-:"))
        key = (normalize(label), url)
        if key in seen:
            continue
        seen.add(key)
        found.append(Link(label=label, url=url))
    return found


def url_for_label(links: tuple[Link, ...] | list[Link], label: str) -> str:
    """Return the single URL whose visible text matches ``label``.

    Matching ignores letter case and the difference between a normal space
    and the odd spaces mail HTML inserts. The whole label has to match, so
    "Activate" does not hit "Activate account". Several anchors with that
    label and one shared URL count as one answer.
    """

    wanted = normalize(label)
    matches = [link for link in links if normalize(link.label) == wanted]
    urls = list(dict.fromkeys(link.url for link in matches))
    if not urls:
        available = tuple(dict.fromkeys(link.label for link in links if link.label))
        raise LinkNotFound(label, available)
    if len(urls) > 1:
        raise AmbiguousLink(label, tuple(urls))
    return urls[0]


def normalize(value: str) -> str:
    """Reduce a label to the form used for comparison.

    Spaces are collapsed first, then letter case is folded, so the stored
    label can keep its original capitals for error messages.
    """

    return collapse(value).casefold()


def collapse(value: str) -> str:
    """Turn mail-HTML whitespace into single ordinary spaces.

    Non-breaking spaces and zero-width characters become nothing or a
    normal space, then runs of whitespace shrink to one space. The words
    and their capitals stay as they were.
    """

    cleaned = value.replace("\xa0", " ").replace("\u202f", " ").translate(_INVISIBLE)
    return " ".join(cleaned.split())


def _anchor_label(anchor) -> str:
    """Read the words a person would see on this anchor.

    Text spread across nested tags is joined with spaces, so
    ``<span>Accept</span> invitation`` is "Accept invitation". When the
    anchor has no text and only holds an image, the image alt text is the
    label. Otherwise the label is empty.
    """

    label = collapse(anchor.get_text(" ", strip=True))
    if label:
        return label
    for image in anchor.find_all("img"):
        alt = image.get("alt")
        if isinstance(alt, str):
            label = collapse(alt)
            if label:
                return label
    return ""
