from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from week_05.models import Chunk, Document


class Chunker(Protocol):
    name: str

    def chunk(self, document: Document) -> list[Chunk]: ...


@dataclass(frozen=True)
class _Span:
    section: str
    start: int
    end: int


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_id(source: str, strategy: str, start: int, end: int, text_hash: str) -> str:
    base = f"{source}|{strategy}|{start}|{end}|{text_hash}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _fixed_windows(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    if not text:
        return []
    windows: list[tuple[int, int]] = []
    step = chunk_size - overlap
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + chunk_size)
        windows.append((start, end))
        if end >= length:
            break
        start += step
    return windows


class FixedSizeChunker:
    name = "fixed"

    def __init__(self, chunk_size: int = 1200, overlap: int = 200) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: Document) -> list[Chunk]:
        chunks: list[Chunk] = []
        for start, end in _fixed_windows(document.content, self.chunk_size, self.overlap):
            text = document.content[start:end].strip()
            if not text:
                continue
            text_hash = _hash_text(text)
            chunks.append(
                Chunk(
                    chunk_id=_chunk_id(document.source, self.name, start, end, text_hash),
                    source=document.source,
                    title=document.title,
                    section="full_document",
                    text=text,
                    strategy=self.name,
                    start_char=start,
                    end_char=end,
                    content_hash=text_hash,
                    extension=document.extension,
                    language=document.language,
                    metadata=dict(document.metadata),
                )
            )
        return chunks


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for idx, char in enumerate(text):
        if char == "\n":
            starts.append(idx + 1)
    return starts


def _python_spans(text: str) -> list[_Span]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    starts = _line_starts(text)
    spans: list[_Span] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not getattr(node, "lineno", None) or not getattr(node, "end_lineno", None):
            continue
        start_line = int(node.lineno) - 1
        end_line = int(node.end_lineno) - 1
        if start_line >= len(starts):
            continue
        start = starts[start_line]
        end = starts[end_line + 1] if end_line + 1 < len(starts) else len(text)
        if end <= start:
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        name = getattr(node, "name", "unknown")
        spans.append(_Span(section=f"{kind}:{name}", start=start, end=end))
    return spans


def _markdown_spans(text: str) -> list[_Span]:
    pattern = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")
    matches = list(pattern.finditer(text))
    if not matches:
        return []
    spans: list[_Span] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = match.group(2).strip()
        spans.append(_Span(section=f"heading:{title}", start=start, end=end))
    return spans


def _paragraph_spans(text: str) -> list[_Span]:
    spans: list[_Span] = []
    for match in re.finditer(r"\S[\s\S]*?(?:\n\s*\n|$)", text):
        start, end = match.span()
        if text[start:end].strip():
            spans.append(_Span(section="paragraph", start=start, end=end))
    return spans


class StructureChunker:
    name = "structure"

    def __init__(self, max_section_chars: int = 1800, fallback_overlap: int = 200) -> None:
        self.max_section_chars = max_section_chars
        self.fallback_overlap = fallback_overlap
        self._fallback = FixedSizeChunker(chunk_size=max_section_chars, overlap=fallback_overlap)

    def _spans(self, document: Document) -> list[_Span]:
        if document.extension == ".md":
            spans = _markdown_spans(document.content)
            if spans:
                return spans
        if document.extension == ".py":
            spans = _python_spans(document.content)
            if spans:
                return spans
        return _paragraph_spans(document.content)

    def chunk(self, document: Document) -> list[Chunk]:
        spans = self._spans(document)
        if not spans:
            return self._fallback.chunk(document)

        chunks: list[Chunk] = []
        for span in spans:
            raw = document.content[span.start : span.end]
            if not raw.strip():
                continue
            if len(raw) <= self.max_section_chars:
                text = raw.strip()
                text_hash = _hash_text(text)
                chunks.append(
                    Chunk(
                        chunk_id=_chunk_id(
                            document.source, self.name, span.start, span.end, text_hash
                        ),
                        source=document.source,
                        title=document.title,
                        section=span.section,
                        text=text,
                        strategy=self.name,
                        start_char=span.start,
                        end_char=span.end,
                        content_hash=text_hash,
                        extension=document.extension,
                        language=document.language,
                        metadata=dict(document.metadata),
                    )
                )
                continue

            # oversized section fallback into fixed windows but preserving section name
            for rel_start, rel_end in _fixed_windows(
                raw, self.max_section_chars, self.fallback_overlap
            ):
                text = raw[rel_start:rel_end].strip()
                if not text:
                    continue
                abs_start = span.start + rel_start
                abs_end = span.start + rel_end
                text_hash = _hash_text(text)
                chunks.append(
                    Chunk(
                        chunk_id=_chunk_id(
                            document.source, self.name, abs_start, abs_end, text_hash
                        ),
                        source=document.source,
                        title=document.title,
                        section=span.section,
                        text=text,
                        strategy=self.name,
                        start_char=abs_start,
                        end_char=abs_end,
                        content_hash=text_hash,
                        extension=document.extension,
                        language=document.language,
                        metadata=dict(document.metadata),
                    )
                )
        return chunks
