from __future__ import annotations

import hashlib
from pathlib import Path

from pypdf import PdfReader

from week_05.models import Document

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".py", ".pdf"}


def _language_for_extension(ext: str) -> str:
    if ext == ".py":
        return "python"
    if ext == ".md":
        return "markdown"
    if ext == ".pdf":
        return "pdf_text"
    return "text"


def _safe_read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    text_parts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            text_parts.append(page_text)
    return "\n\n".join(text_parts)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_documents(source: Path) -> tuple[list[Document], list[str]]:
    """
    Recursively load supported files from source path.
    Returns (documents, warnings).
    """
    warnings: list[str] = []
    documents: list[Document] = []
    if not source.exists():
        return [], [f"Source does not exist: {source}"]

    candidates: list[Path]
    if source.is_file():
        candidates = [source]
    else:
        candidates = sorted(
            (
                p
                for p in source.rglob("*")
                if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
            ),
            key=lambda p: str(p).lower(),
        )

    for path in candidates:
        ext = path.suffix.lower()
        rel = str(path)
        try:
            if ext == ".pdf":
                content = _read_pdf(path)
            else:
                content = _safe_read_text(path)
        except Exception as exc:
            warnings.append(f"Skipping unreadable file {rel}: {exc}")
            continue

        content = content.strip()
        if not content:
            warnings.append(f"Skipping empty file {rel}")
            continue

        title = path.stem
        language = _language_for_extension(ext)
        documents.append(
            Document(
                source=rel,
                title=title,
                content=content,
                extension=ext,
                language=language,
                metadata={"content_hash": _content_hash(content), "filename": path.name},
            )
        )

    if not documents:
        warnings.append(f"No supported non-empty files found in: {source}")
    return documents, warnings
