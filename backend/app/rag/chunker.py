"""Split the clinic markdown documents into chunks.

Each document has one ``# Title`` line and several ``## Heading`` sections.
Default granularity is one chunk per section; a section longer than
``max_words`` is split with ``overlap`` words repeated between pieces.
``by_heading=False`` makes one chunk per whole document (used by the
retrieval eval to compare granularity).

Every chunk's text starts with "Title - Heading" so the embedding carries
context a bare paragraph would lack.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

DOCS_DIR = Path(__file__).parent / "docs"
DEFAULT_MAX_WORDS = 150
DEFAULT_OVERLAP = 25


@dataclass(frozen=True)
class Chunk:
    source: str   # file stem, e.g. "cancellation-policy"
    title: str    # document title, used as the citation label
    heading: str  # section heading ("" for whole-document chunks)
    content: str  # text that gets embedded and returned to the agent

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def _split_words(text: str, max_words: int, overlap: int) -> List[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text.strip()]
    step = max(1, max_words - overlap)
    pieces = []
    for start in range(0, len(words), step):
        pieces.append(" ".join(words[start:start + max_words]))
        if start + max_words >= len(words):
            break
    return pieces


def _parse(markdown: str) -> Tuple[str, List[Tuple[str, str]]]:
    title = ""
    sections = []  # type: List[Tuple[str, str]]
    heading = ""
    body = []  # type: List[str]

    def flush() -> None:
        text = " ".join(" ".join(body).split())
        if text:
            sections.append((heading, text))

    for line in markdown.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            heading, body = line[3:].strip(), []
        else:
            body.append(line.strip())
    flush()
    return title, sections


def chunk_markdown(
    source: str,
    markdown: str,
    max_words: int = DEFAULT_MAX_WORDS,
    overlap: int = DEFAULT_OVERLAP,
    by_heading: bool = True,
) -> List[Chunk]:
    title, sections = _parse(markdown)
    title = title or source
    if not by_heading:
        text = " ".join(body for _, body in sections)
        return [
            Chunk(source, title, "", "%s - %s" % (title, piece))
            for piece in _split_words(text, max_words * 4, overlap)
        ]
    chunks = []
    for heading, body in sections:
        label = "%s - %s" % (title, heading) if heading else title
        for piece in _split_words(body, max_words, overlap):
            chunks.append(Chunk(source, title, heading, "%s: %s" % (label, piece)))
    return chunks


def load_chunks(
    docs_dir: Path = DOCS_DIR,
    max_words: int = DEFAULT_MAX_WORDS,
    overlap: int = DEFAULT_OVERLAP,
    by_heading: bool = True,
) -> List[Chunk]:
    chunks = []  # type: List[Chunk]
    for path in sorted(Path(docs_dir).glob("*.md")):
        chunks.extend(
            chunk_markdown(
                path.stem,
                path.read_text(encoding="utf-8"),
                max_words=max_words,
                overlap=overlap,
                by_heading=by_heading,
            )
        )
    return chunks
