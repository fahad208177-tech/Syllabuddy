"""Embedding generation and a content-addressed cache.

Embeddings are cached by a hash of ``model + text``, not by index position, so
adding one textbook chapter re-embeds only that chapter's chunks. The previous
design fingerprinted the whole corpus and rebuilt everything on any change,
which is fine for 79 chunks and painful for a few thousand.

Vectors are stored in a compressed ``.npz`` as float32. The equivalent JSON was
roughly 5 KB per vector; this is about 1.5 KB.

**Why the default embedder is not Ollama.** Measured on this machine, embedding
one query through Ollama took 2.3s warm and over 20s if the model had been
unloaded, because every HTTP request re-establishes the model context. The same
work in-process through ONNX takes 19ms. Since a query must be embedded before
retrieval can start, that latency sits in front of every single question. The
in-process path also removes the need for a running server, so retrieval works
even when Ollama is down.
"""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

# Stronger on retrieval benchmarks than all-minilm, same 384 dimensions, ~65 MB
# of quantised ONNX on disk.
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Keep the model next to the project rather than in the system temp folder,
# which gets cleared and would force a re-download.
MODEL_CACHE = "cache/models"


# BGE models are trained asymmetrically: passages are embedded as-is, but a short
# query is embedded behind this instruction. Measured on the retrieval evaluation
# set, adding it moves top-1 accuracy from 88% to 96%. It costs nothing, because
# the query is one short string either way.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingClient(Protocol):
    model: str
    query_prefix: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedClient:
    """In-process ONNX embeddings. No server, no per-request model reload."""

    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        cache_dir: str | Path = MODEL_CACHE,
    ) -> None:
        self.model = model
        self._cache_dir = str(cache_dir)
        self._embedder = None
        self.query_prefix = BGE_QUERY_PREFIX if "bge" in model.lower() else ""

    def _load(self):
        # Deferred so importing this module stays cheap; the ONNX runtime and
        # the model together take a few seconds to bring up.
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as error:
                raise EmbeddingUnavailable(
                    "fastembed is not installed. Run 'pip install fastembed', "
                    "or set TUTOR_EMBEDDER=ollama to use the Ollama backend."
                ) from error

            Path(self._cache_dir).mkdir(parents=True, exist_ok=True)
            try:
                self._embedder = TextEmbedding(self.model, cache_dir=self._cache_dir)
            except Exception as error:  # model download or ONNX startup failure
                raise EmbeddingUnavailable(
                    f"Could not load embedding model '{self.model}': {error}"
                ) from error
        return self._embedder

    def embed(self, texts: list[str]) -> list[list[float]]:
        embedder = self._load()
        try:
            return [vector.tolist() for vector in embedder.embed(texts)]
        except Exception as error:
            raise EmbeddingUnavailable(f"Embedding failed: {error}") from error


class OllamaEmbeddingClient:
    """Embeddings from a local Ollama server.

    Kept as a fallback and so you can compare embedding models you have pulled.
    """

    def __init__(
        self,
        model: str = "all-minilm",
        base_url: str = "http://localhost:11434",
        timeout_seconds: int = 180,
        keep_alive: str = "30m",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        # Without this Ollama unloads the model between calls and every request
        # pays a ~20s reload.
        self.keep_alive = keep_alive
        self.query_prefix = BGE_QUERY_PREFIX if "bge" in model.lower() else ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps(
            {"model": self.model, "input": texts, "keep_alive": self.keep_alive}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, socket.timeout, urllib.error.URLError) as error:
            raise EmbeddingUnavailable(
                f"Could not reach Ollama at {self.base_url}: {error}. "
                f"Start it with 'ollama serve' and pull the model with "
                f"'ollama pull {self.model}'."
            ) from error

        if "error" in data:
            raise EmbeddingUnavailable(f"Ollama error for '{self.model}': {data['error']}")

        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingUnavailable("Ollama returned an unexpected embedding payload.")

        return embeddings


class EmbeddingUnavailable(RuntimeError):
    """Raised when embeddings cannot be produced, so callers can fall back."""


def create_client(backend: str | None = None, model: str | None = None) -> EmbeddingClient:
    """Build the configured embedding client.

    ``TUTOR_EMBEDDER=ollama`` switches backends; ``TUTOR_EMBED_MODEL`` overrides
    the model name for whichever backend is selected.
    """
    import os

    choice = (backend or os.environ.get("TUTOR_EMBEDDER") or "fastembed").lower()
    name = model or os.environ.get("TUTOR_EMBED_MODEL")

    if choice == "ollama":
        return OllamaEmbeddingClient(model=name or "all-minilm")
    return FastEmbedClient(model=name or DEFAULT_EMBEDDING_MODEL)


class EmbeddingStore:
    """A persistent content-addressed cache of embedding vectors."""

    def __init__(self, path: str | Path, client: EmbeddingClient, batch_size: int = 16) -> None:
        self.path = Path(path)
        self.client = client
        self.batch_size = batch_size
        self._vectors: dict[str, np.ndarray] = {}
        self._load()

    def _key(self, text: str) -> str:
        raw = f"{self.client.model}\0{text}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with np.load(self.path, allow_pickle=False) as archive:
                keys = archive["keys"]
                vectors = archive["vectors"]
            self._vectors = {str(key): vectors[i] for i, key in enumerate(keys)}
        except (OSError, ValueError, KeyError):
            # A corrupt or outdated cache is not worth failing over; rebuild it.
            self._vectors = {}

    def save(self) -> None:
        if not self._vectors:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys = list(self._vectors)
        vectors = np.stack([self._vectors[key] for key in keys]).astype(np.float32)
        np.savez_compressed(self.path, keys=np.array(keys), vectors=vectors)

    def embed(
        self,
        texts: list[str],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> np.ndarray:
        """Return one row per text, embedding only what is not already cached."""
        missing = [text for text in texts if self._key(text) not in self._vectors]
        # Deduplicate while preserving order, so repeated text is embedded once.
        missing = list(dict.fromkeys(missing))

        for start in range(0, len(missing), self.batch_size):
            batch = missing[start : start + self.batch_size]
            for text, vector in zip(batch, self.client.embed(batch)):
                self._vectors[self._key(text)] = np.asarray(vector, dtype=np.float32)
            if on_progress:
                on_progress(min(start + len(batch), len(missing)), len(missing))

        if missing:
            self.save()

        return np.stack([self._vectors[self._key(text)] for text in texts])

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a search query, applying the model's query instruction.

        Kept separate from :meth:`embed` so document vectors are never built
        with the prefix attached.
        """
        prefix = getattr(self.client, "query_prefix", "")
        return self.embed([f"{prefix}{query}"])
