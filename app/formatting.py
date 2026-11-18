import bleach
from markdown_it import MarkdownIt


# The js-default preset renders tables/strikethrough but disables raw HTML parsing.
_markdown = MarkdownIt("js-default", {"linkify": False, "typographer": False})
_cleaner = bleach.Cleaner(
    tags={
        "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4", "h5", "h6",
        "hr", "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th", "thead", "tr", "ul",
    },
    attributes={"a": ["href", "title"], "code": ["class"]},
    protocols={"http", "https", "mailto"},
    strip=True,
    strip_comments=True,
)


def render_markdown(source: str) -> str:
    """Render model Markdown to a small safe HTML subset for the chat UI."""
    return _cleaner.clean(_markdown.render(source or ""))
