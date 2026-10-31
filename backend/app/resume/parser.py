"""Turn a resume PDF into sections and embeddable chunks.

Tuned for a conventional single-column resume: UPPERCASE section headings, experience entries
as a "Role | Company" line followed by bullets, and bullets of the form "Title: description".
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader

KNOWN_SECTIONS = {
    "PROFESSIONAL SUMMARY": "summary",
    "SUMMARY": "summary",
    "PROFILE": "summary",
    "CORE SKILLS": "skills",
    "SKILLS": "skills",
    "TECHNICAL SKILLS": "skills",
    "PROFESSIONAL EXPERIENCE": "experience",
    "EXPERIENCE": "experience",
    "WORK EXPERIENCE": "experience",
    "PROJECTS": "projects",
    "EDUCATION": "education",
    "CERTIFICATIONS": "certifications",
}

# Common bullet glyphs, plus the private-use and DEL (\x7f) symbols that PDF fonts often emit.
BULLET_RE = re.compile(r"^\s*[•●▪◦\-\*•\x7f-]\s*")
DATE_LINE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{4}\s*[–\-]", re.IGNORECASE
)


@dataclass
class Chunk:
    section: str
    content: str
    title: str | None = None


@dataclass
class ParsedResume:
    raw_text: str
    header: str
    sections: dict[str, str] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)


def extract_text(source: Path | BinaryIO) -> str:
    reader = PdfReader(source)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _heading_key(line: str) -> str | None:
    stripped = line.strip()
    if stripped.upper() in KNOWN_SECTIONS and stripped == stripped.upper():
        return KNOWN_SECTIONS[stripped.upper()]
    return None


def split_sections(text: str) -> tuple[str, dict[str, str]]:
    header_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] = header_lines
    for line in text.splitlines():
        key = _heading_key(line)
        if key:
            current = sections.setdefault(key, [])
            continue
        current.append(line.rstrip())
    return (
        "\n".join(header_lines).strip(),
        {k: "\n".join(v).strip() for k, v in sections.items()},
    )


def _bullets(body: str) -> list[tuple[str | None, str]]:
    """Group lines into (context, bullet) pairs, joining wrapped lines.

    Context is the most recent non-bullet "Role | Company" line, so each experience bullet keeps
    track of which job it belongs to.
    """
    items: list[tuple[str | None, str]] = []
    context: str | None = None
    current: list[str] | None = None

    def flush() -> None:
        if current:
            items.append((context, " ".join(current).strip()))

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if BULLET_RE.match(line):
            flush()
            current = [BULLET_RE.sub("", line)]
        elif DATE_LINE_RE.match(line):
            continue
        elif "|" in line and current is not None and not line.endswith((".", ",")):
            flush()
            current = None
            context = line
        elif "|" in line and current is None:
            context = line
        elif current is not None:
            current.append(line)
        else:
            current = [line]
    flush()
    return items


def _split_title(bullet: str) -> tuple[str | None, str]:
    title, sep, _ = bullet.partition(":")
    if sep and len(title) <= 60:
        return title.strip(), bullet
    return None, bullet


def build_chunks(sections: dict[str, str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, body in sections.items():
        if not body:
            continue
        if section in ("summary", "education"):
            chunks.append(Chunk(section=section, content=" ".join(body.split())))
            continue
        for context, bullet in _bullets(body):
            title, content = _split_title(bullet)
            if context:
                content = f"{context} — {content}"
            chunks.append(Chunk(section=section, title=title, content=content))
    return chunks


def parse_resume(source: Path | BinaryIO) -> ParsedResume:
    return parse_text(extract_text(source))


def parse_text(text: str) -> ParsedResume:
    header, sections = split_sections(text)
    return ParsedResume(
        raw_text=text, header=header, sections=sections, chunks=build_chunks(sections)
    )
