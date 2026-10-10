"""Local, namespace-scoped Markdown memory with offline embeddings."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_MODEL_REVISION = "bundled-fastembed-0.9.0"
DEFAULT_DIMENSIONS = 384
_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_FRONTMATTER_TYPE = re.compile(r"(?m)^\s*type\s*:\s*([^\r\n#]+)")
_FRONTMATTER_TITLE = re.compile(r"(?m)^\s*title\s*:\s*([^\r\n#]+)")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_WIKILINK = re.compile(r"!?\[\[([^\]]+)\]\]")
_MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
_NAMESPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ALLOWED_CORPORA = (".docs", ".playbooks", ".memory")
_FORBIDDEN_COMPONENTS = {
    ".git",
    "git",
    ".scratch",
    "scratch",
    ".holdout",
    "holdout",
    "heldout",
    "__pycache__",
    ".pytest_cache",
}


@dataclass(frozen=True)
class _Chunk:
    text: str
    heading: str | None
    start_offset: int
    end_offset: int
    token_count: int


@dataclass(frozen=True)
class _Document:
    path: Path
    source: str
    text: str
    content_hash: str
    title: str
    chunks: tuple[_Chunk, ...]
    links: tuple[tuple[str, str], ...]


class FastEmbedBackend:
    """FastEmbed adapter which only loads cached models during normal use."""

    model_id = DEFAULT_MODEL_ID
    dimensions = DEFAULT_DIMENSIONS
    max_input_tokens = 128
    is_fake = False

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        model_revision: str = DEFAULT_MODEL_REVISION,
        dimensions: int = DEFAULT_DIMENSIONS,
    ) -> None:
        self.cache_dir = Path(cache_dir).expanduser().resolve(strict=False)
        self.model_id = model_id
        self.model_revision = model_revision
        self.dimensions = int(dimensions)
        if self.dimensions < 1:
            raise ValueError("embedding dimensions must be positive")
        self._embedder: Any = None
        self._artifact_hash: str | None = None
        self._effective_revision: str | None = None

    @property
    def revision(self) -> str:
        self._load_local_model()
        assert self._effective_revision is not None
        return self._effective_revision

    @property
    def artifact_sha256(self) -> str | None:
        self._load_local_model()
        return self._artifact_hash

    @classmethod
    def download_model(
        cls,
        cache_dir: str | Path,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        model_revision: str = DEFAULT_MODEL_REVISION,
        dimensions: int = DEFAULT_DIMENSIONS,
    ) -> dict[str, Any]:
        """Explicitly download and validate the configured FastEmbed ONNX model."""
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("FastEmbed is not installed in this workspace environment") from exc

        cache_path = Path(cache_dir).expanduser().resolve(strict=False)
        cache_path.mkdir(parents=True, exist_ok=True)
        try:
            embedder = TextEmbedding(
                model_name=model_id,
                cache_dir=str(cache_path),
                local_files_only=False,
            )
        except Exception as exc:
            raise RuntimeError(f"could not download FastEmbed model {model_id}: {exc}") from exc
        actual_dimensions = int(embedder.embedding_size)
        if actual_dimensions != int(dimensions):
            raise RuntimeError(
                f"FastEmbed model {model_id} has {actual_dimensions} dimensions; expected {dimensions}"
            )
        artifact_hash = _model_cache_hash(cache_path)
        if artifact_hash is None:
            raise RuntimeError(f"FastEmbed did not leave model files in {cache_path}")
        return {
            "model_id": model_id,
            "revision": f"{model_revision}+sha256:{artifact_hash}",
            "dimensions": actual_dimensions,
            "cache_dir": str(cache_path),
            "artifact_sha256": artifact_hash,
        }

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        embedder = self._load_local_model()
        try:
            return [[float(value) for value in row] for row in embedder.embed(list(texts))]
        except Exception as exc:
            raise RuntimeError(f"local FastEmbed inference failed: {exc}") from exc

    def token_count(self, text: str) -> int:
        """Count the model's input tokens before passing a chunk to ONNX."""
        try:
            return int(self._load_local_model().token_count([text]))
        except Exception as exc:
            raise RuntimeError(f"could not count FastEmbed model tokens: {exc}") from exc

    def _load_local_model(self) -> Any:
        if self._embedder is not None:
            return self._embedder
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                "FastEmbed is not installed; use the explicit model download/bootstrap command"
            ) from exc
        try:
            self._embedder = TextEmbedding(
                model_name=self.model_id,
                cache_dir=str(self.cache_dir),
                local_files_only=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"cached FastEmbed model {self.model_id} is unavailable; download it explicitly first: {exc}"
            ) from exc
        actual_dimensions = int(self._embedder.embedding_size)
        if actual_dimensions != self.dimensions:
            self._embedder = None
            raise RuntimeError(
                f"FastEmbed model {self.model_id} has {actual_dimensions} dimensions; "
                f"expected {self.dimensions}"
            )
        self._artifact_hash = _model_cache_hash(self.cache_dir)
        if self._artifact_hash is None:
            self._embedder = None
            raise RuntimeError(f"could not fingerprint cached FastEmbed files in {self.cache_dir}")
        self._effective_revision = f"{self.model_revision}+sha256:{self._artifact_hash}"
        return self._embedder


def _model_cache_hash(cache_dir: Path) -> str | None:
    """Fingerprint files in the dedicated workspace cache, excluding lock files."""
    if not cache_dir.exists():
        return None
    digest = hashlib.sha256()
    found = False
    for path in sorted(cache_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name.endswith(".lock"):
            continue
        relative = path.relative_to(cache_dir).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            with path.open("rb") as file_obj:
                for block in iter(lambda: file_obj.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError:
            return None
        digest.update(b"\0")
        found = True
    return digest.hexdigest() if found else None


def _token_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _TOKEN.finditer(text)]


def _split_frontmatter(text: str) -> tuple[str | None, str | None, int, str]:
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None, None, 0, text
    lines = text.splitlines(keepends=True)
    frontmatter_end_line: int | None = None
    offset = 0
    frontmatter_lines: list[str] = []
    body_start = 0
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            frontmatter_end_line = index
            body_start = sum(len(part) for part in lines[: index + 1])
            break
        frontmatter_lines.append(line)
    if frontmatter_end_line is None:
        return None, None, 0, text
    metadata = "".join(frontmatter_lines)
    type_match = _FRONTMATTER_TYPE.search(metadata)
    title_match = _FRONTMATTER_TITLE.search(metadata)
    kind = _strip_scalar(type_match.group(1)) if type_match else None
    title = _strip_scalar(title_match.group(1)) if title_match else None
    return kind, title, body_start, text[body_start:]


def _strip_scalar(value: str) -> str:
    return value.strip().strip("\"'").strip()


def _split_sections(body: str, body_offset: int) -> list[tuple[str | None, int, str]]:
    lines = body.splitlines(keepends=True)
    sections: list[tuple[str | None, int, str]] = []
    current_heading: str | None = None
    section_start = body_offset
    section_parts: list[str] = []
    source_offset = body_offset
    for line in lines:
        heading_match = _HEADING.match(line.rstrip("\r\n"))
        if heading_match:
            if section_parts:
                sections.append((current_heading, section_start, "".join(section_parts)))
            current_heading = heading_match.group(2).strip()
            section_start = source_offset
            section_parts = [line]
        else:
            if not section_parts:
                section_start = source_offset
            section_parts.append(line)
        source_offset += len(line)
    if section_parts:
        sections.append((current_heading, section_start, "".join(section_parts)))
    if not sections and body:
        sections.append((None, body_offset, body))
    return sections


def _make_chunks(text: str, body_offset: int, size: int, overlap: int) -> tuple[_Chunk, ...]:
    if size < 1:
        raise ValueError("chunk_size_tokens must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("chunk_overlap_tokens must be nonnegative and smaller than the chunk size")
    chunks: list[_Chunk] = []
    for heading, section_offset, section in _split_sections(text, body_offset):
        spans = _token_spans(section)
        cursor = 0
        while cursor < len(spans):
            stop = min(cursor + size, len(spans))
            start_in_section = spans[cursor][0]
            end_in_section = spans[stop - 1][1]
            chunk_text = section[start_in_section:end_in_section]
            chunks.append(
                _Chunk(
                    text=chunk_text,
                    heading=heading,
                    start_offset=section_offset + start_in_section,
                    end_offset=section_offset + end_in_section,
                    token_count=stop - cursor,
                )
            )
            if stop == len(spans):
                break
            cursor = stop - overlap
    return tuple(chunks)


def _fit_chunks_to_backend(
    chunks: Sequence[_Chunk],
    backend: Any,
    max_tokens: int,
) -> tuple[_Chunk, ...]:
    """Re-split heuristic chunks using the live model tokenizer when available."""
    counter = getattr(backend, "token_count", None)
    if not callable(counter):
        return tuple(chunks)
    fitted: list[_Chunk] = []

    def split(chunk: _Chunk, start: int = 0, end: int | None = None) -> None:
        if end is None:
            end = len(chunk.text)
        fragment = chunk.text[start:end]
        if not fragment.strip():
            return
        token_count = int(counter(fragment))
        if token_count <= max_tokens:
            spans = _token_spans(fragment)
            if spans:
                fitted.append(
                    _Chunk(
                        text=fragment,
                        heading=chunk.heading,
                        start_offset=chunk.start_offset + start,
                        end_offset=chunk.start_offset + end,
                        token_count=token_count,
                    )
                )
            return

        spans = _token_spans(fragment)
        if len(spans) > 1:
            boundary = spans[len(spans) // 2][0]
            if boundary <= 0 or boundary >= len(fragment):
                boundary = len(fragment) // 2
            split(chunk, start, start + boundary)
            split(chunk, start + boundary, end)
            return

        # A single unusually long lexical token can still exceed the model window.
        # Split it by character so no part is silently discarded or truncated.
        low = 1
        high = len(fragment)
        best = 0
        while low <= high:
            middle = (low + high) // 2
            if int(counter(fragment[:middle])) <= max_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best <= 0 or best >= len(fragment):
            if best <= 0:
                raise ValueError("a source token cannot fit within the configured model token window")
            split(chunk, start, start + best)
            split(chunk, start + best, end)
            return
        split(chunk, start, start + best)
        split(chunk, start + best, end)

    for chunk in chunks:
        split(chunk)
    return tuple(fitted)


def _parse_links(text: str) -> tuple[tuple[str, str], ...]:
    links: list[tuple[str, str]] = []
    for match in _WIKILINK.finditer(text):
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            links.append((target, "wikilink"))
    for match in _MARKDOWN_LINK.finditer(text):
        target = match.group(1).strip().strip("<>").split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:", "//", "#")):
            continue
        links.append((target, "markdown"))
    return tuple(links)


def _markdown_document(path: Path, workspace: Path, chunk_size: int, overlap: int) -> _Document | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Markdown source is not valid UTF-8: {path}") from exc
    kind, frontmatter_title, body_offset, body = _split_frontmatter(raw)
    relative = path.relative_to(workspace).as_posix()
    if kind is None and path.name.casefold() not in {"index.md", "log.md"}:
        return None
    if kind is not None and kind.casefold() in {"holdout", "private", "secret"}:
        return None
    if kind is not None and not kind.strip():
        return None
    if not body.strip():
        return None
    first_heading = next(
        (match.group(2).strip() for line in body.splitlines() if (match := _HEADING.match(line))),
        None,
    )
    title = frontmatter_title or first_heading or path.stem
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    chunks = _make_chunks(body, body_offset, chunk_size, overlap)
    if not chunks:
        return None
    return _Document(
        path=path,
        source=relative,
        text=raw,
        content_hash=digest,
        title=title,
        chunks=chunks,
        links=_parse_links(body),
    )


def _path_key(path: Path, workspace: Path) -> str:
    return path.resolve(strict=False).relative_to(workspace).as_posix()


def _has_forbidden_component(path: Path) -> bool:
    for part in path.parts:
        lowered = part.casefold()
        if lowered in _FORBIDDEN_COMPONENTS or "holdout" in lowered or "scratch" in lowered:
            return True
    return False


def _same_or_child(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _path_has_link_component(path: Path, workspace: Path) -> bool:
    try:
        parts = path.absolute().relative_to(workspace.absolute()).parts
    except ValueError:
        return True
    cursor = workspace.absolute()
    if cursor.is_symlink():
        return True
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            return True
    return False


def _vector_bytes(vector: Sequence[float], dimensions: int) -> bytes:
    if len(vector) != dimensions:
        raise ValueError(f"embedding has {len(vector)} dimensions; expected {dimensions}")
    normalized = _normalize(vector)
    try:
        return struct.pack("<" + "f" * dimensions, *normalized)
    except (OverflowError, struct.error) as exc:
        raise ValueError("embedding contains values outside float32 range") from exc


def _vector_from_bytes(raw: bytes, dimensions: int) -> list[float]:
    if len(raw) != dimensions * 4:
        raise RuntimeError("stored embedding has an invalid byte length")
    return list(struct.unpack("<" + "f" * dimensions, raw))


def _normalize(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding contains a non-finite value")
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("cannot compare embeddings with different dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


class MemoryIndex:
    """SQLite Markdown index with explicit corpus roots and namespace filtering."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        db_path: str | Path | None = None,
        embedding_backend: Any | None = None,
        chunk_size_tokens: int = 96,
        chunk_overlap_tokens: int = 12,
        model_id: str = DEFAULT_MODEL_ID,
        model_revision: str = DEFAULT_MODEL_REVISION,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        if not self.workspace.is_dir():
            raise ValueError(f"workspace must be an existing directory: {self.workspace}")
        if chunk_size_tokens < 1 or chunk_overlap_tokens < 0 or chunk_overlap_tokens >= chunk_size_tokens:
            raise ValueError("chunk size must be positive and overlap smaller than size")
        self.chunk_size_tokens = int(chunk_size_tokens)
        self.chunk_overlap_tokens = int(chunk_overlap_tokens)
        self.db_path = (
            Path(db_path).expanduser()
            if db_path is not None
            else self.workspace / ".memory" / "arena" / "knowledge.sqlite"
        )
        if not self.db_path.is_absolute():
            self.db_path = self.workspace / self.db_path
        self.db_path = self.db_path.resolve(strict=False)
        try:
            self.db_path.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("memory database must stay inside the workspace") from exc
        self.model_id = model_id
        self.model_revision = model_revision
        self.embedding_backend = embedding_backend or FastEmbedBackend(
            self.workspace / ".codex" / "arena" / "models",
            model_id=model_id,
            model_revision=model_revision,
        )
        self.dimensions = int(getattr(self.embedding_backend, "dimensions", DEFAULT_DIMENSIONS))
        if self.dimensions < 1:
            raise ValueError("embedding backend dimensions must be positive")
        max_input_tokens = getattr(self.embedding_backend, "max_input_tokens", None)
        if max_input_tokens is not None and chunk_size_tokens > int(max_input_tokens):
            raise ValueError(
                f"chunk_size_tokens cannot exceed the model input limit ({max_input_tokens})"
            )
        self._semantic = not bool(getattr(self.embedding_backend, "is_fake", False))
        self._vector_table = f"vec_chunks_d{self.dimensions}"

    def download_model(self) -> dict[str, Any]:
        """Explicitly download the configured real embedding model into this workspace."""
        if not isinstance(self.embedding_backend, FastEmbedBackend):
            raise ValueError("model download is available only for the FastEmbed backend")
        result = self.embedding_backend.download_model(
            self.embedding_backend.cache_dir,
            model_id=self.embedding_backend.model_id,
            model_revision=self.embedding_backend.model_revision,
            dimensions=self.embedding_backend.dimensions,
        )
        self.embedding_backend._effective_revision = str(result["revision"])
        self.embedding_backend._artifact_hash = str(result["artifact_sha256"])
        return result

    def index(
        self,
        paths: str | Path | Iterable[str | Path],
        namespace: str,
        exclusions: Iterable[str | Path] = (),
    ) -> dict[str, Any]:
        namespace = self._validate_namespace(namespace)
        scan_paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
        excluded_paths = [self._resolve_exclusion(path) for path in exclusions]
        scopes = self._validate_scopes(scan_paths)
        candidates = self._discover(scopes, excluded_paths)

        # Loading is local-only. It happens after explicit path exclusions have been checked.
        model_id, model_revision, dimensions, artifact_sha256 = self._backend_metadata()
        if dimensions != self.dimensions:
            raise RuntimeError("embedding backend dimension changed after MemoryIndex construction")

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.is_symlink() or (hasattr(self.db_path, "is_junction") and self.db_path.is_junction()):
            raise ValueError(f"refusing to use a linked memory database: {self.db_path}")
        connection = self._connect()
        try:
            self._initialize(connection)
            namespace_row = connection.execute(
                "SELECT model_id, model_revision, dimensions, artifact_sha256 "
                "FROM namespace_models WHERE namespace = ?",
                (namespace,),
            ).fetchone()
            full_rebuild = namespace_row is not None and (
                namespace_row[0] != model_id
                or namespace_row[1] != model_revision
                or int(namespace_row[2]) != dimensions
                or namespace_row[3] != artifact_sha256
            )
            if full_rebuild:
                old_sources = connection.execute(
                    "SELECT source FROM documents WHERE namespace = ?", (namespace,)
                ).fetchall()
                for (source,) in old_sources:
                    previous = self.workspace / Path(source)
                    safe_previous = self._stored_source(previous)
                    if safe_previous is not None and self._is_excluded(safe_previous, excluded_paths):
                        continue
                    if safe_previous is not None and safe_previous.exists() and safe_previous not in candidates:
                        candidates.append(safe_previous)
                scopes = scopes + tuple((path, True) for path in candidates)

            documents: dict[str, _Document] = {}
            for candidate in sorted(set(candidates), key=lambda item: item.as_posix().casefold()):
                document = _markdown_document(
                    candidate,
                    self.workspace,
                    self.chunk_size_tokens,
                    self.chunk_overlap_tokens,
                )
                if document is not None:
                    chunks = _fit_chunks_to_backend(
                        document.chunks,
                        self.embedding_backend,
                        self.chunk_size_tokens,
                    )
                    document = replace(document, chunks=chunks)
                    documents[document.source] = document

            connection.execute("BEGIN IMMEDIATE")
            existing_rows = connection.execute(
                "SELECT id, source, content_hash, model_id, model_revision, artifact_sha256 "
                "FROM documents WHERE namespace = ?",
                (namespace,),
            ).fetchall()
            existing_by_source = {row[1]: row for row in existing_rows}
            scope_sources = {
                source
                for source in existing_by_source
                if self._source_in_scopes(source, scopes)
            }
            if full_rebuild:
                scope_sources.update(existing_by_source)

            changed_documents: list[tuple[_Document, list[list[float]]]] = []
            skipped = 0
            for source, document in documents.items():
                old = existing_by_source.get(source)
                if (
                    old is not None
                    and old[2] == document.content_hash
                    and old[3] == model_id
                    and old[4] == model_revision
                    and old[5] == artifact_sha256
                ):
                    skipped += 1
                    continue
                chunk_texts = [chunk.text for chunk in document.chunks]
                vectors = self._encode(chunk_texts, dimensions)
                changed_documents.append((document, vectors))

            present_sources = set(documents)
            stale_sources = scope_sources - present_sources
            removed = 0
            if full_rebuild:
                stale_sources = set(existing_by_source) - present_sources
            for source in sorted(stale_sources):
                self._delete_document(connection, namespace, source)
                removed += 1

            embedded = 0
            for document, vectors in changed_documents:
                old = existing_by_source.get(document.source)
                if old is not None:
                    self._delete_chunks_for_doc(connection, int(old[0]))
                    connection.execute("DELETE FROM documents WHERE id = ?", (int(old[0]),))
                cursor = connection.execute(
                    "INSERT INTO documents(namespace, source, title, content_hash, model_id, model_revision, "
                    "artifact_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        namespace,
                        document.source,
                        document.title,
                        document.content_hash,
                        model_id,
                        model_revision,
                        artifact_sha256,
                    ),
                )
                doc_id = int(cursor.lastrowid)
                for chunk, vector in zip(document.chunks, vectors):
                    vector_blob = _vector_bytes(vector, dimensions)
                    cursor = connection.execute(
                        "INSERT INTO chunks(doc_id, namespace, source, heading, start_offset, end_offset, text, "
                        "token_count, content_hash, model_id, model_revision, artifact_sha256, embedding, semantic) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            doc_id,
                            namespace,
                            document.source,
                            chunk.heading,
                            chunk.start_offset,
                            chunk.end_offset,
                            chunk.text,
                            chunk.token_count,
                            document.content_hash,
                            model_id,
                            model_revision,
                            artifact_sha256,
                            vector_blob,
                            int(self._semantic),
                        ),
                    )
                    chunk_id = int(cursor.lastrowid)
                    connection.execute(
                        "INSERT INTO chunks_fts(rowid, chunk_id, namespace, heading, text) VALUES (?, ?, ?, ?, ?)",
                        (chunk_id, chunk_id, namespace, chunk.heading or "", chunk.text),
                    )
                    if self._vec_enabled:
                        self._insert_vec(connection, chunk_id, namespace, vector_blob)
                    embedded += 1
                connection.execute("DELETE FROM links WHERE namespace = ? AND source = ?", (namespace, document.source))
                connection.executemany(
                    "INSERT INTO links(namespace, source, target_ref, kind, target_source) VALUES (?, ?, ?, ?, NULL)",
                    [(namespace, document.source, target, kind) for target, kind in document.links],
                )

            connection.execute(
                "INSERT INTO namespace_models(namespace, model_id, model_revision, dimensions, artifact_sha256) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(namespace) DO UPDATE SET model_id = excluded.model_id, "
                "model_revision = excluded.model_revision, dimensions = excluded.dimensions, "
                "artifact_sha256 = excluded.artifact_sha256",
                (namespace, model_id, model_revision, dimensions, artifact_sha256),
            )
            self._resolve_links(connection, namespace)
            metadata = {
                "schema_version": 1,
                "namespace": namespace,
                "indexed_at_utc": datetime.now(timezone.utc).isoformat(),
                "semantic": self._semantic,
                "vector_engine": "sqlite-vec" if self._vec_enabled else "numpy-cosine",
                "model": {
                    "id": model_id,
                    "revision": model_revision,
                    "dimensions": dimensions,
                    "artifact_sha256": artifact_sha256,
                },
                "chunking": {
                    "window_tokens": self.chunk_size_tokens,
                    "overlap_tokens": self.chunk_overlap_tokens,
                    "tokenizer": "model-tokenizer" if callable(getattr(self.embedding_backend, "token_count", None)) else "unicode-word-punctuation",
                },
                "document_count": len(documents),
                "chunk_count": int(connection.execute(
                    "SELECT COUNT(*) FROM chunks WHERE namespace = ?", (namespace,)
                ).fetchone()[0]),
            }
            metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            connection.execute(
                "INSERT INTO namespace_metadata(namespace, metadata_json) VALUES (?, ?) "
                "ON CONFLICT(namespace) DO UPDATE SET metadata_json = excluded.metadata_json",
                (namespace, metadata_json),
            )
            connection.commit()
            total_documents = connection.execute(
                "SELECT COUNT(*) FROM documents WHERE namespace = ?", (namespace,)
            ).fetchone()[0]
            total_chunks = connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE namespace = ?", (namespace,)
            ).fetchone()[0]
            return {
                "namespace": namespace,
                "documents": int(total_documents),
                "chunks": int(total_chunks),
                "embedded": embedded,
                "skipped": skipped,
                "removed": removed,
                "model_id": model_id,
                "model_revision": model_revision,
                "vector_engine": "sqlite-vec" if self._vec_enabled else "numpy-cosine",
                "semantic": self._semantic,
                "metadata": metadata,
                "metadata_json": metadata_json,
            }
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def search(
        self,
        query: str,
        namespace: str,
        topk: int = 8,
        context_token_budget: int = 1200,
    ) -> list[dict[str, Any]]:
        namespace = self._validate_namespace(namespace)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a nonempty string")
        if not isinstance(topk, int) or topk < 1:
            raise ValueError("topk must be a positive integer")
        if not isinstance(context_token_budget, int) or context_token_budget < 0:
            raise ValueError("context_token_budget must be a nonnegative integer")
        if context_token_budget == 0:
            return []

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            return []
        connection = self._connect()
        try:
            self._initialize(connection)
            stored_model = connection.execute(
                "SELECT model_id, model_revision, dimensions, artifact_sha256 "
                "FROM namespace_models WHERE namespace = ?",
                (namespace,),
            ).fetchone()
            if stored_model is None:
                return []
            model_id, model_revision, dimensions, artifact_sha256 = self._backend_metadata()
            if (
                stored_model[0] != model_id
                or stored_model[1] != model_revision
                or int(stored_model[2]) != dimensions
                or stored_model[3] != artifact_sha256
            ):
                raise RuntimeError("memory namespace uses a different embedding model; re-index it before searching")
            metadata_row = connection.execute(
                "SELECT metadata_json FROM namespace_metadata WHERE namespace = ?", (namespace,)
            ).fetchone()
            if metadata_row is None:
                raise RuntimeError("memory namespace provenance is missing; re-index it before searching")
            try:
                index_metadata = json.loads(metadata_row[0])
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("memory namespace provenance is invalid; re-index it before searching") from exc
            query_vector = self._encode([query], dimensions)[0]
            query_blob = _vector_bytes(query_vector, dimensions)

            fts_ranks: dict[int, int] = {}
            terms = [token for token in re.findall(r"\w+", query, re.UNICODE) if token]
            if terms:
                fts_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
                fts_rows = connection.execute(
                    "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? AND namespace = ? "
                    "ORDER BY bm25(chunks_fts) LIMIT ?",
                    (fts_query, namespace, max(topk * 20, 100)),
                ).fetchall()
                fts_ranks = {int(row[0]): rank for rank, row in enumerate(fts_rows, start=1)}

            total = int(
                connection.execute("SELECT COUNT(*) FROM chunks WHERE namespace = ?", (namespace,)).fetchone()[0]
            )
            candidate_limit = min(total, max(topk * 20, 100))
            vector_ranks: dict[int, int] = {}
            vector_scores: dict[int, float] = {}
            vector_rows: list[tuple[int, float]]
            if self._vec_enabled and candidate_limit:
                vector_rows = self._query_vec(connection, query_blob, namespace, candidate_limit)
            else:
                vector_rows = self._numpy_nearest(connection, query_blob, namespace, candidate_limit, dimensions)
            for rank, (chunk_id, score) in enumerate(vector_rows, start=1):
                vector_ranks[chunk_id] = rank
                vector_scores[chunk_id] = score

            candidate_ids = set(fts_ranks) | set(vector_ranks)
            if not candidate_ids:
                return []
            placeholders = ",".join("?" for _ in candidate_ids)
            parameters: list[Any] = [namespace, *sorted(candidate_ids)]
            rows = connection.execute(
                "SELECT id, namespace, source, heading, start_offset, end_offset, text, token_count, "
                "content_hash, model_id, model_revision, artifact_sha256, semantic "
                f"FROM chunks WHERE namespace = ? AND id IN ({placeholders})",
                parameters,
            ).fetchall()
            ranked: list[tuple[float, sqlite3.Row]] = []
            for row in rows:
                chunk_id = int(row[0])
                reciprocal_rank_score = 0.0
                if chunk_id in vector_ranks:
                    reciprocal_rank_score += 1.0 / (60.0 + vector_ranks[chunk_id])
                if chunk_id in fts_ranks:
                    reciprocal_rank_score += 1.0 / (60.0 + fts_ranks[chunk_id])
                ranked.append((reciprocal_rank_score, row))
            ranked.sort(key=lambda item: (-item[0], -vector_scores.get(int(item[1][0]), -2.0), item[1][2], item[1][4]))

            results: list[dict[str, Any]] = []
            used_tokens = 0
            for score, row in ranked:
                token_count = int(row[7])
                if used_tokens + token_count > context_token_budget:
                    continue
                used_tokens += token_count
                chunk_id = int(row[0])
                results.append(
                    {
                        "namespace": row[1],
                        "source": row[2],
                        "heading": row[3] or None,
                        "start_offset": int(row[4]),
                        "end_offset": int(row[5]),
                        "text": row[6],
                        "token_count": token_count,
                        "content_hash": row[8],
                        "model_id": row[9],
                        "model_revision": row[10],
                        "artifact_sha256": row[11],
                        "semantic": bool(row[12]),
                        "metadata": index_metadata,
                        "vector_score": vector_scores.get(chunk_id),
                        "score": score,
                        "used_tokens": used_tokens,
                    }
                )
                if len(results) >= topk:
                    break
            return results
        finally:
            connection.close()

    def graph(self, namespace: str | None = None) -> dict[str, list[dict[str, Any]]]:
        if namespace is not None:
            namespace = self._validate_namespace(namespace)
        if not self.db_path.exists():
            return {"nodes": [], "edges": []}
        connection = self._connect()
        try:
            self._initialize(connection)
            if namespace is None:
                node_rows = connection.execute(
                    "SELECT namespace, source, title, content_hash FROM documents ORDER BY namespace, source"
                ).fetchall()
                edge_rows = connection.execute(
                    "SELECT namespace, source, target_source, target_ref, kind FROM links "
                    "WHERE target_source IS NOT NULL ORDER BY namespace, source, target_source"
                ).fetchall()
            else:
                node_rows = connection.execute(
                    "SELECT namespace, source, title, content_hash FROM documents WHERE namespace = ? ORDER BY source",
                    (namespace,),
                ).fetchall()
                edge_rows = connection.execute(
                    "SELECT namespace, source, target_source, target_ref, kind FROM links "
                    "WHERE namespace = ? AND target_source IS NOT NULL ORDER BY source, target_source",
                    (namespace,),
                ).fetchall()
            return {
                "nodes": [
                    {"namespace": row[0], "source": row[1], "title": row[2], "content_hash": row[3]}
                    for row in node_rows
                ],
                "edges": [
                    {
                        "namespace": row[0],
                        "source": row[1],
                        "target": row[2],
                        "target_ref": row[3],
                        "kind": row[4],
                    }
                    for row in edge_rows
                ],
            }
        finally:
            connection.close()

    @staticmethod
    def _validate_namespace(namespace: str) -> str:
        if not isinstance(namespace, str) or not _NAMESPACE.fullmatch(namespace):
            raise ValueError("namespace must be 1-64 ASCII letters, digits, dot, underscore, or hyphen")
        return namespace

    def _backend_metadata(self) -> tuple[str, str, int, str | None]:
        model_id = str(getattr(self.embedding_backend, "model_id", self.model_id))
        model_revision = str(getattr(self.embedding_backend, "revision", self.model_revision))
        dimensions = int(getattr(self.embedding_backend, "dimensions", self.dimensions))
        artifact_sha256 = getattr(self.embedding_backend, "artifact_sha256", None)
        if artifact_sha256 is not None:
            artifact_sha256 = str(artifact_sha256)
        return model_id, model_revision, dimensions, artifact_sha256

    def _encode(self, texts: Sequence[str], dimensions: int) -> list[list[float]]:
        if not texts:
            return []
        encoder = getattr(self.embedding_backend, "encode", None)
        if not callable(encoder):
            raise ValueError("embedding_backend must provide encode(texts)")
        try:
            vectors = list(encoder(list(texts)))
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"embedding backend failed: {exc}") from exc
        if len(vectors) != len(texts):
            raise ValueError("embedding backend returned a different number of vectors than inputs")
        normalized: list[list[float]] = []
        for vector in vectors:
            if len(vector) != dimensions:
                raise ValueError(f"embedding has {len(vector)} dimensions; expected {dimensions}")
            normalized.append(_normalize(vector))
        return normalized

    def _allowed_roots(self) -> tuple[Path, ...]:
        roots: list[Path] = []
        for name in _ALLOWED_CORPORA:
            root = self.workspace / name
            if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
                continue
            roots.append(root.resolve(strict=False))
        return tuple(roots)

    def _validate_scopes(self, paths: Sequence[str | Path]) -> tuple[tuple[Path, bool], ...]:
        scopes: list[tuple[Path, bool]] = []
        roots = self._allowed_roots()
        for raw_path in paths:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = self.workspace / path
            resolved = path.resolve(strict=False)
            if not _same_or_child(resolved, self.workspace):
                raise ValueError(f"index path escapes workspace: {raw_path}")
            if path.exists() and _path_has_link_component(path, self.workspace):
                raise ValueError(f"index path contains a symlink or junction: {raw_path}")
            allowed = [root for root in roots if _same_or_child(resolved, root)]
            if not allowed:
                if _same_or_child(resolved, self.workspace):
                    continue
                raise ValueError(f"index path must stay inside the workspace: {raw_path}")
            root = max(allowed, key=lambda item: len(item.parts))
            if _has_forbidden_component(resolved.relative_to(self.workspace)):
                # Explicitly supplied holdout/scratch roots are empty by policy.
                continue
            scopes.append((resolved, resolved.is_file()))
        return tuple(scopes)

    def _resolve_exclusion(self, raw_path: str | Path) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve(strict=False)
        if not _same_or_child(resolved, self.workspace):
            raise ValueError(f"exclusion path escapes workspace: {raw_path}")
        return resolved

    def _is_excluded(self, path: Path, exclusions: Sequence[Path]) -> bool:
        try:
            relative = path.resolve(strict=False).relative_to(self.workspace)
        except ValueError:
            return True
        if _has_forbidden_component(relative) or _path_has_link_component(path, self.workspace):
            return True
        for excluded in exclusions:
            if _same_or_child(path, excluded):
                return True
        return False

    def _discover(self, scopes: Sequence[tuple[Path, bool]], exclusions: Sequence[Path]) -> list[Path]:
        found: set[Path] = set()
        for scope, is_file in scopes:
            if self._is_excluded(scope, exclusions):
                continue
            if is_file:
                paths = [scope] if scope.suffix.casefold() == ".md" else []
            elif scope.is_dir():
                paths = list(scope.rglob("*.md"))
            else:
                paths = []
            for candidate in paths:
                if candidate.suffix.casefold() != ".md" or self._is_excluded(candidate, exclusions):
                    continue
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve(strict=False)
                if not _same_or_child(resolved, self.workspace):
                    raise ValueError(f"Markdown path escapes workspace: {candidate}")
                if not any(_same_or_child(resolved, root) for root in self._allowed_roots()):
                    raise ValueError(f"Markdown path is outside an approved corpus: {candidate}")
                found.add(resolved)
        return sorted(found, key=lambda item: item.as_posix().casefold())

    def _stored_source(self, path: Path) -> Path | None:
        resolved = path.resolve(strict=False)
        if not _same_or_child(resolved, self.workspace) or _path_has_link_component(path, self.workspace):
            return None
        if not any(_same_or_child(resolved, root) for root in self._allowed_roots()):
            return None
        if self._is_excluded(path, ()) or resolved.suffix.casefold() != ".md":
            return None
        return resolved

    def _source_in_scopes(self, source: str, scopes: Sequence[tuple[Path, bool]]) -> bool:
        full_path = self.workspace / Path(source)
        for scope, is_file in scopes:
            if is_file:
                if full_path.resolve(strict=False) == scope.resolve(strict=False):
                    return True
            elif _same_or_child(full_path, scope):
                return True
        return False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        self._vec_enabled = self._load_vector_extension(connection)
        return connection

    @staticmethod
    def _load_vector_extension(connection: sqlite3.Connection) -> bool:
        try:
            import sqlite_vec

            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            return True
        except (ImportError, AttributeError, sqlite3.Error, OSError):
            try:
                connection.enable_load_extension(False)
            except (AttributeError, sqlite3.Error):
                pass
            return False

    def _initialize(self, connection: sqlite3.Connection) -> None:
        try:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS namespace_models ("
                "namespace TEXT PRIMARY KEY, model_id TEXT NOT NULL, model_revision TEXT NOT NULL, "
                "dimensions INTEGER NOT NULL, artifact_sha256 TEXT);"
                "CREATE TABLE IF NOT EXISTS documents ("
                "id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, source TEXT NOT NULL, title TEXT NOT NULL, "
                "content_hash TEXT NOT NULL, model_id TEXT NOT NULL, model_revision TEXT NOT NULL, "
                "artifact_sha256 TEXT, "
                "UNIQUE(namespace, source));"
                "CREATE TABLE IF NOT EXISTS chunks ("
                "id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, "
                "namespace TEXT NOT NULL, source TEXT NOT NULL, heading TEXT, start_offset INTEGER NOT NULL, "
                "end_offset INTEGER NOT NULL, text TEXT NOT NULL, token_count INTEGER NOT NULL, "
                "content_hash TEXT NOT NULL, model_id TEXT NOT NULL, model_revision TEXT NOT NULL, "
                "artifact_sha256 TEXT, embedding BLOB NOT NULL, semantic INTEGER NOT NULL);"
                "CREATE TABLE IF NOT EXISTS namespace_metadata ("
                "namespace TEXT PRIMARY KEY, metadata_json TEXT NOT NULL);"
                "CREATE INDEX IF NOT EXISTS chunks_namespace_idx ON chunks(namespace);"
                "CREATE TABLE IF NOT EXISTS links ("
                "id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, source TEXT NOT NULL, target_ref TEXT NOT NULL, "
                "kind TEXT NOT NULL, target_source TEXT);"
                "CREATE INDEX IF NOT EXISTS links_namespace_idx ON links(namespace);"
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                "chunk_id UNINDEXED, namespace UNINDEXED, heading, text, tokenize='unicode61');"
            )
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).casefold():
                raise RuntimeError("this Python SQLite build does not include FTS5") from exc
            raise
        self._ensure_column(connection, "namespace_models", "artifact_sha256", "TEXT")
        self._ensure_column(connection, "documents", "artifact_sha256", "TEXT")
        self._ensure_column(connection, "chunks", "artifact_sha256", "TEXT")
        if self._vec_enabled:
            try:
                connection.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {self._vector_table} USING vec0("
                    f"embedding float[{self.dimensions}], namespace text)"
                )
            except sqlite3.Error:
                self._vec_enabled = False

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _insert_vec(self, connection: sqlite3.Connection, chunk_id: int, namespace: str, blob: bytes) -> None:
        connection.execute(
            f"INSERT OR REPLACE INTO {self._vector_table}(rowid, embedding, namespace) VALUES (?, ?, ?)",
            (chunk_id, blob, namespace),
        )

    def _delete_chunks_for_doc(self, connection: sqlite3.Connection, doc_id: int) -> None:
        chunk_ids = [int(row[0]) for row in connection.execute("SELECT id FROM chunks WHERE doc_id = ?", (doc_id,))]
        for chunk_id in chunk_ids:
            connection.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
            if self._vec_enabled:
                connection.execute(f"DELETE FROM {self._vector_table} WHERE rowid = ?", (chunk_id,))
        connection.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))

    def _delete_document(self, connection: sqlite3.Connection, namespace: str, source: str) -> None:
        row = connection.execute(
            "SELECT id FROM documents WHERE namespace = ? AND source = ?", (namespace, source)
        ).fetchone()
        if row is None:
            return
        doc_id = int(row[0])
        self._delete_chunks_for_doc(connection, doc_id)
        connection.execute("DELETE FROM links WHERE namespace = ? AND source = ?", (namespace, source))
        connection.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    def _query_vec(
        self,
        connection: sqlite3.Connection,
        query_blob: bytes,
        namespace: str,
        limit: int,
    ) -> list[tuple[int, float]]:
        rows = connection.execute(
            f"SELECT rowid, distance FROM {self._vector_table} "
            "WHERE embedding MATCH ? AND k = ? AND namespace = ? ORDER BY distance",
            (query_blob, limit, namespace),
        ).fetchall()
        if not rows:
            return []
        ids = [int(row[0]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        vectors = connection.execute(
            "SELECT id, embedding FROM chunks WHERE namespace = ? "
            f"AND id IN ({placeholders})",
            [namespace, *ids],
        ).fetchall()
        query_vector = _vector_from_bytes(query_blob, self.dimensions)
        by_id = {int(row[0]): _cosine(query_vector, _vector_from_bytes(row[1], self.dimensions)) for row in vectors}
        result = [(int(row[0]), by_id.get(int(row[0]), 0.0)) for row in rows]
        result.sort(key=lambda item: (-item[1], item[0]))
        return result

    def _numpy_nearest(
        self,
        connection: sqlite3.Connection,
        query_blob: bytes,
        namespace: str,
        limit: int,
        dimensions: int,
    ) -> list[tuple[int, float]]:
        if limit <= 0:
            return []
        rows = connection.execute(
            "SELECT id, embedding FROM chunks WHERE namespace = ?", (namespace,)
        ).fetchall()
        query_vector = _vector_from_bytes(query_blob, dimensions)
        try:
            import numpy as np

            matrix = np.asarray(
                [_vector_from_bytes(row[1], dimensions) for row in rows], dtype=np.float32
            )
            query_array = np.asarray(query_vector, dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_array)
            dots = matrix @ query_array
            scores = np.divide(dots, norms, out=np.zeros_like(dots), where=norms != 0)
            result = [(int(row[0]), float(score)) for row, score in zip(rows, scores)]
        except ImportError:
            result = [
                (int(row[0]), _cosine(query_vector, _vector_from_bytes(row[1], dimensions)))
                for row in rows
            ]
        result.sort(key=lambda item: (-item[1], item[0]))
        return result[:limit]

    def _resolve_links(self, connection: sqlite3.Connection, namespace: str) -> None:
        documents = connection.execute(
            "SELECT source, title FROM documents WHERE namespace = ?", (namespace,)
        ).fetchall()
        source_set = {str(row[0]) for row in documents}
        by_stem: dict[str, str] = {}
        by_title: dict[str, str] = {}
        for source, title in documents:
            source = str(source)
            by_stem.setdefault(Path(source).stem.casefold(), source)
            by_title.setdefault(str(title).casefold(), source)
        links = connection.execute(
            "SELECT id, source, target_ref FROM links WHERE namespace = ?", (namespace,)
        ).fetchall()
        for link_id, source, target_ref in links:
            target = self._resolve_link_target(str(source), str(target_ref), source_set, by_stem, by_title)
            connection.execute("UPDATE links SET target_source = ? WHERE id = ?", (target, int(link_id)))

    @staticmethod
    def _resolve_link_target(
        source: str,
        reference: str,
        source_set: set[str],
        by_stem: dict[str, str],
        by_title: dict[str, str],
    ) -> str | None:
        cleaned = reference.replace("\\", "/").strip()
        if cleaned.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", cleaned):
            return None
        path = Path(cleaned)
        if path.suffix.casefold() == ".md":
            candidate = (Path(source).parent / path).as_posix()
            if candidate in source_set:
                return candidate
        else:
            candidate = (Path(source).parent / f"{cleaned}.md").as_posix()
            if candidate in source_set:
                return candidate
        basename = Path(cleaned).stem.casefold()
        return by_stem.get(basename) or by_title.get(Path(cleaned).name.casefold()) or by_title.get(cleaned.casefold())


__all__ = [
    "DEFAULT_DIMENSIONS",
    "DEFAULT_MODEL_ID",
    "DEFAULT_MODEL_REVISION",
    "FastEmbedBackend",
    "MemoryIndex",
]
