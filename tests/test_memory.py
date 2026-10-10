from __future__ import annotations

import math
import json
from pathlib import Path
import re
import sqlite3

import pytest

from scripts.arena_memory import MemoryIndex


class FixedVectors:
    """Deterministic test vectors; deliberately not a semantic model."""

    model_id = "test/fixed-vectors"
    revision = "fixture-v1"
    dimensions = 3
    is_fake = True
    artifact_sha256 = "fixture-artifact-sha256"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            if "query" in lowered or "galaxy" in lowered or "orbit" in lowered:
                vectors.append([1.0, 0.0, 0.0])
            elif "orthogonal" in lowered or "recipe" in lowered or "kitchen" in lowered:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


def write_doc(path: Path, *, kind: str = "note", title: str = "Doc", body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntype: {kind}\ntitle: {title}\n---\n{body}\n", encoding="utf-8")
    return path


def test_search_uses_cosine_math_and_marks_injected_test_backend_as_fake(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    write_doc(docs / "close.md", title="Close", body="# Query notes\nA galaxy follows an orbit.")
    write_doc(docs / "side.md", title="Side", body="# Cooking\nA recipe for the kitchen.")
    backend = FixedVectors()
    index = MemoryIndex(tmp_path, embedding_backend=backend)

    stats = index.index([docs], namespace="research")
    results = index.search("query", namespace="research", topk=5, context_token_budget=200)

    assert stats["chunks"] == 2
    assert len(results) == 2
    assert results[0]["source"].endswith("close.md")
    assert results[0]["vector_score"] == pytest.approx(1.0)
    assert results[1]["vector_score"] == pytest.approx(0.0)
    assert all(result["semantic"] is False for result in results)
    assert results[0]["model_id"] == backend.model_id
    assert results[0]["model_revision"] == backend.revision
    assert results[0]["artifact_sha256"] == backend.artifact_sha256
    assert results[0]["metadata"]["semantic"] is False
    assert results[0]["metadata"]["model"]["artifact_sha256"] == backend.artifact_sha256
    assert results[0]["content_hash"]
    assert results[0]["heading"] == "Query notes"
    assert results[0]["start_offset"] < results[0]["end_offset"]
    assert all(math.isfinite(result["score"]) for result in results)

    with sqlite3.connect(index.db_path) as connection:
        persisted = json.loads(
            connection.execute(
                "SELECT metadata_json FROM namespace_metadata WHERE namespace = ?", ("research",)
            ).fetchone()[0]
        )
    assert persisted["namespace"] == "research"
    assert persisted["model"]["artifact_sha256"] == backend.artifact_sha256
    assert persisted["semantic"] is False
    assert persisted["chunking"]["window_tokens"] == 96


def test_exclusions_and_forbidden_paths_are_applied_before_read_or_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / ".docs"
    safe = write_doc(docs / "safe.md", body="# Safe\nGalaxy query material.")
    excluded = write_doc(docs / "holdout" / "secret.md", body="# Secret\nprivate query data.")
    custom_excluded = write_doc(docs / "private.md", body="# Private\nprivate query data.")
    write_doc(tmp_path / "elsewhere.md", body="# Outside\nnot an approved corpus.")
    backend = FixedVectors()
    index = MemoryIndex(tmp_path, embedding_backend=backend)
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == excluded:
            pytest.fail("holdout content was read before exclusion")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    index.index([docs, tmp_path / "elsewhere.md"], namespace="safe", exclusions=[custom_excluded])
    results = index.search("private", namespace="safe", topk=10, context_token_budget=200)

    assert len(backend.calls[0]) == 1
    embedded_text = "\n".join(backend.calls[0])
    assert "private query data" not in embedded_text
    assert all(result["source"].endswith("safe.md") for result in results)
    assert all("secret.md" not in result["source"] for result in results)


def test_only_explicit_approved_markdown_with_type_is_indexed(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    write_doc(docs / "typed.md", body="# Typed\nGalaxy query.")
    (docs / "untagged.md").write_text("# Untagged\nGalaxy query.\n", encoding="utf-8")
    (docs / "index.md").write_text("# Index\nGalaxy query.\n", encoding="utf-8")
    write_doc(tmp_path / ".playbooks" / "workflow.md", body="# Workflow\nKitchen recipe.")
    write_doc(tmp_path / "random.md", body="# Random\nGalaxy query.")
    index = MemoryIndex(tmp_path, embedding_backend=FixedVectors())

    stats = index.index([docs, tmp_path / ".playbooks"], namespace="allowed")
    results = index.search("query", namespace="allowed", topk=10, context_token_budget=300)

    sources = {result["source"] for result in results}
    assert stats["documents"] == 3
    assert any(source.endswith("typed.md") for source in sources)
    assert any(source.endswith("index.md") for source in sources)
    assert any(source.endswith("workflow.md") for source in sources)
    assert not any(source.endswith("untagged.md") for source in sources)
    assert not any(source.endswith("random.md") for source in sources)


def test_chunking_covers_long_documents_without_exceeding_window(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    body = "# Long section\n" + " ".join(f"token{i}" for i in range(65))
    write_doc(docs / "long.md", body=body)
    backend = FixedVectors()
    index = MemoryIndex(tmp_path, embedding_backend=backend, chunk_size_tokens=12, chunk_overlap_tokens=2)

    stats = index.index([docs], namespace="chunks")
    results = index.search("query", namespace="chunks", topk=20, context_token_budget=1000)

    assert stats["chunks"] >= 6
    assert all(result["token_count"] <= 12 for result in results)
    merged = " ".join(result["text"] for result in results)
    assert "token64" in merged
    assert "token0" in merged


def test_model_tokenizer_rechunks_before_inference_instead_of_relying_on_truncation(
    tmp_path: Path,
) -> None:
    class PieceCountingVectors(FixedVectors):
        max_input_tokens = 8

        def token_count(self, text: str) -> int:
            return sum(max(1, math.ceil(len(word) / 3)) for word in re.findall(r"\S+", text))

    docs = tmp_path / ".docs"
    body = "# Long section\n" + " ".join(f"token{i}" for i in range(30))
    write_doc(docs / "long.md", body=body)
    backend = PieceCountingVectors()
    index = MemoryIndex(tmp_path, embedding_backend=backend, chunk_size_tokens=8, chunk_overlap_tokens=1)

    index.index([docs], namespace="tokenizer")
    results = index.search("query", namespace="tokenizer", topk=20, context_token_budget=1000)

    assert results
    assert all(result["token_count"] <= 8 for result in results)
    assert "token29" in " ".join(result["text"] for result in results)


def test_incremental_index_skips_unchanged_documents_and_removes_deleted_ones(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    first_path = write_doc(docs / "first.md", body="# First\nGalaxy query.")
    second_path = write_doc(docs / "second.md", body="# Second\nKitchen recipe.")
    backend = FixedVectors()
    index = MemoryIndex(tmp_path, embedding_backend=backend)

    first = index.index([docs], namespace="incremental")
    calls_after_first = len(backend.calls)
    again = index.index([docs], namespace="incremental")
    second_path.unlink()
    after_delete = index.index([docs], namespace="incremental")

    assert first["embedded"] == 2
    assert again["embedded"] == 0
    assert len(backend.calls) == calls_after_first
    assert after_delete["removed"] == 1
    results = index.search("query", namespace="incremental", topk=10, context_token_budget=500)
    assert all(result["source"].endswith(first_path.name) for result in results)


def test_model_revision_change_rebuilds_the_namespace(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    write_doc(docs / "one.md", body="# One\nGalaxy query.")
    backend = FixedVectors()
    index = MemoryIndex(tmp_path, embedding_backend=backend)

    index.index([docs], namespace="revision")
    backend.revision = "fixture-v2"
    rebuilt = index.index([docs], namespace="revision")
    result = index.search("query", namespace="revision", topk=1, context_token_budget=100)

    assert rebuilt["embedded"] == 1
    assert result[0]["model_revision"] == "fixture-v2"


def test_artifact_fingerprint_change_rebuilds_namespace_and_updates_provenance(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    write_doc(docs / "one.md", body="# One\nGalaxy query.")
    backend = FixedVectors()
    index = MemoryIndex(tmp_path, embedding_backend=backend)
    index.index([docs], namespace="fingerprint")
    backend.artifact_sha256 = "replacement-artifact-sha256"

    rebuilt = index.index([docs], namespace="fingerprint")
    result = index.search("query", namespace="fingerprint", topk=1, context_token_budget=100)

    assert rebuilt["embedded"] == 1
    assert result[0]["artifact_sha256"] == "replacement-artifact-sha256"
    assert result[0]["metadata"]["model"]["artifact_sha256"] == "replacement-artifact-sha256"


def test_new_exclusion_evicts_previously_indexed_content_from_fts_and_search(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    public = write_doc(docs / "public.md", body="# Public\nGalaxy query.")
    private = write_doc(docs / "private.md", body="# Private\nuniqueclassifiedterm.")
    backend = FixedVectors()
    index = MemoryIndex(tmp_path, embedding_backend=backend)
    index.index([docs], namespace="exclusion-update")
    encoded_calls = len(backend.calls)

    updated = index.index([docs], namespace="exclusion-update", exclusions=[private])
    assert len(backend.calls) == encoded_calls
    results = index.search(
        "uniqueclassifiedterm", namespace="exclusion-update", topk=10, context_token_budget=100
    )
    with sqlite3.connect(index.db_path) as connection:
        fts_hits = connection.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? AND namespace = ?",
            ('"uniqueclassifiedterm"', "exclusion-update"),
        ).fetchall()

    assert updated["removed"] == 1
    assert not any(row["source"].endswith(private.name) for row in results)
    assert all(row["source"].endswith(public.name) for row in results)
    assert fts_hits == []


def test_search_is_namespace_scoped_and_context_budget_never_truncates_chunks(
    tmp_path: Path,
) -> None:
    docs = tmp_path / ".docs"
    write_doc(docs / "alpha.md", body="# Alpha\nGalaxy query.")
    write_doc(docs / "beta.md", body="# Beta\nGalaxy query.")
    index = MemoryIndex(tmp_path, embedding_backend=FixedVectors())
    index.index([docs], namespace="alpha")
    index.index([docs], namespace="beta")

    alpha = index.search("query", namespace="alpha", topk=10, context_token_budget=100)
    too_small = index.search("query", namespace="alpha", topk=10, context_token_budget=1)
    all_namespaces = index.search("query", namespace="beta", topk=10, context_token_budget=100)

    assert all(result["namespace"] == "alpha" for result in alpha)
    assert all(result["namespace"] == "beta" for result in all_namespaces)
    assert too_small == []
    with pytest.raises(ValueError, match="namespace"):
        index.search("query", namespace="alpha' OR 1=1 --", topk=10, context_token_budget=100)


def test_vector_candidates_are_filtered_by_namespace_before_nearest_search(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    for number in range(105):
        write_doc(docs / f"other-{number}.md", body=f"# Other {number}\nGalaxy notes.")
    alpha_doc = write_doc(docs / "target.md", body="# Target\nAn orbit.")
    index = MemoryIndex(tmp_path, embedding_backend=FixedVectors())

    index.index([docs / "other-0.md", *[docs / f"other-{n}.md" for n in range(1, 105)]], namespace="other")
    index.index([alpha_doc], namespace="target")
    results = index.search("query", namespace="target", topk=1, context_token_budget=100)

    assert len(results) == 1
    assert results[0]["source"].endswith("target.md")
    assert results[0]["vector_score"] == pytest.approx(1.0)


def test_graph_resolves_obsidian_and_markdown_links(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    write_doc(docs / "source.md", title="Source", body="# Source\nSee [[Target]] and [target](target.md).")
    write_doc(docs / "target.md", title="Target", body="# Target\nGalaxy query.")
    index = MemoryIndex(tmp_path, embedding_backend=FixedVectors())
    index.index([docs], namespace="graph")

    graph = index.graph(namespace="graph")

    assert {node["source"] for node in graph["nodes"]} == {".docs/source.md", ".docs/target.md"}
    assert {edge["kind"] for edge in graph["edges"]} == {"wikilink", "markdown"}
    assert all(edge["target"] == ".docs/target.md" for edge in graph["edges"])


def test_invalid_namespace_and_path_escape_are_rejected(tmp_path: Path) -> None:
    docs = tmp_path / ".docs"
    write_doc(docs / "one.md", body="# One\nGalaxy query.")
    outside = tmp_path.parent / "outside.md"
    outside.write_text("---\ntype: note\n---\nprivate", encoding="utf-8")
    index = MemoryIndex(tmp_path, embedding_backend=FixedVectors())

    with pytest.raises(ValueError, match="namespace"):
        index.index([docs], namespace="bad namespace")
    with pytest.raises(ValueError, match="approved|workspace|outside|path"):
        index.index([outside], namespace="safe")


def test_default_database_and_model_cache_are_workspace_local_and_separate(tmp_path: Path) -> None:
    index = MemoryIndex(tmp_path)

    assert index.db_path == (tmp_path / ".memory" / "arena" / "knowledge.sqlite").resolve()
    assert index.embedding_backend.cache_dir == (
        tmp_path / ".codex" / "arena" / "models"
    ).resolve()
    assert index.db_path != tmp_path / ".memory" / "arena" / "state.sqlite"
