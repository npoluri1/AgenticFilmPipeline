"""Small text utilities shared by RAG, memory and providers."""
from __future__ import annotations

import hashlib
import re
import unicodedata


_WORD_RE = re.compile(r"[\w\u0900-\u0DFF\u0C00-\u0C7F']+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def stable_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8", "ignore")).hexdigest()


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return (text[:max_len].strip("-") or "item")


def truncate(text: str, limit: int = 240) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def chunk_text(text: str, size: int = 700, overlap: int = 80) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if size <= 0 or len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            # Prefer paragraph / sentence boundaries.
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("। "))
            if cut > size * 0.55:
                end = start + cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]
