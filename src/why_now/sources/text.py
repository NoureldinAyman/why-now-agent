"""Turning job ad HTML into plain text, so no tag or script from an ad is ever kept."""

import html
import re
from html.parser import HTMLParser

# Tags that start a new line of text.
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "ol", "p", "pre", "section",
    "table", "td", "th", "tr", "ul",
}  # fmt: skip
# Tags whose content is never text a reader would see.
_HIDDEN_TAGS = {"script", "style", "template", "noscript"}
_SPACES = re.compile(r"[^\S\n]+")
# Something that looks like an HTML tag, such as `<b>`, `</p>` or `<!-- -->`.
_TAG = re.compile(r"<[A-Za-z/!][^<>]*>")


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN_TAGS:
            self.hidden += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self.hidden = max(0, self.hidden - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Plain text from HTML: tags and hidden parts removed, one line per block, spaces tidied."""
    parser = _TextParser()
    parser.feed(markup)
    parser.close()
    text = _SPACES.sub(" ", "".join(parser.parts))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def escaped_html_to_text(escaped: str) -> str:
    """For HTML that arrives with its tags escaped, as `&lt;p&gt;`: unescape once, then strip.

    Some ads escape their tags twice, so tags show up only after the first strip.
    Those are stripped again. A plain `<` in prose, as in "teams of < 10", is kept.
    """
    text = html_to_text(html.unescape(escaped))
    return html_to_text(text) if _TAG.search(text) else text
