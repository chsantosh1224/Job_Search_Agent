import html
import re

from bs4 import BeautifulSoup


def html_to_text(markup: str | None) -> str:
    """Plain text from (possibly entity-escaped) HTML, keeping paragraph breaks."""
    if not markup:
        return ""
    if "&lt;" in markup:  # Greenhouse double-escapes its HTML
        markup = html.unescape(markup)
    text = BeautifulSoup(markup, "html.parser").get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def normalize_name(value: str) -> str:
    """Lowercase alphanumerics only, used for company and dedupe keys."""
    value = re.sub(r"\([^)]*\)", " ", value.lower())
    value = re.sub(r"\b(inc|llc|ltd|corp|co|gmbh|labs?|technologies|ai)\b\.?", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()
