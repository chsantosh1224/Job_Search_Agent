import hashlib
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.embeddings import Embedder, mean_vector
from app.models import Resume, ResumeChunk
from app.resume.parser import ParsedResume, parse_resume


def store_resume(session: Session, user_id: int | None, parsed: ParsedResume, filename: str,
                 embedder: Embedder | None = None) -> Resume:
    """Make `parsed` the user's active resume. Re-uploading the same file reuses the row.

    Without an embedder the chunks are stored unembedded; the worker embeds them before ranking
    (keeps the embedding model out of the API process).
    """
    if not parsed.chunks:
        raise ValueError("No resume content could be extracted. Is the PDF text-based?")

    content_hash = hashlib.sha256(parsed.raw_text.encode()).hexdigest()
    session.execute(update(Resume).where(_owned_by(user_id)).values(is_active=False))

    existing = session.scalar(
        select(Resume).where(_owned_by(user_id), Resume.content_hash == content_hash)
    )
    if existing:
        existing.is_active = True
        if embedder is not None and existing.embedding is None:
            embed_resume(existing, embedder)
        return existing

    resume = Resume(
        user_id=user_id,
        filename=filename[:255],
        content_hash=content_hash,
        raw_text=parsed.raw_text,
        sections={"header": parsed.header, **parsed.sections},
        is_active=True,
        chunks=[
            ResumeChunk(position=i, section=c.section, title=c.title, content=c.content)
            for i, c in enumerate(parsed.chunks)
        ],
    )
    session.add(resume)
    session.flush()
    if embedder is not None:
        embed_resume(resume, embedder)
    return resume


def embed_resume(resume: Resume, embedder: Embedder) -> None:
    vectors = embedder.embed([chunk.content for chunk in resume.chunks])
    for chunk, vector in zip(resume.chunks, vectors, strict=True):
        chunk.embedding = vector
    resume.embedding = mean_vector(vectors)


def ingest_resume(session: Session, path: Path, embedder: Embedder,
                  user_id: int | None = None) -> Resume:
    """Parse, chunk and embed a resume file (the CLI path)."""
    return store_resume(session, user_id, parse_resume(path), path.name, embedder)


def get_active_resume(session: Session, user_id: int | None = None) -> Resume | None:
    return session.scalar(
        select(Resume).where(_owned_by(user_id), Resume.is_active.is_(True))
    )


def _owned_by(user_id: int | None):
    return Resume.user_id.is_(None) if user_id is None else Resume.user_id == user_id
