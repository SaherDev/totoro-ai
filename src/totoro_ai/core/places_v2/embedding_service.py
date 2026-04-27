"""EmbeddingService — turn PlaceCore rows into vectors and persist them.

Black-box contract: the service serializes the whole `PlaceCore` (via
`model_dump_json`) and hands the string to an external embedder. No
field-by-field hand picking — when `PlaceCore` grows new fields, the
embedded text grows with it for free, and retrieval evals can tune the
embedder/model without touching this code.

Diff-then-embed: every row's source text is hashed (SHA-256). Before
hitting the embedder we read the stored `(text_hash, model_name)` for
each place and skip the rows where both still match — no re-embedding,
no DB write. Saves Voyage credits and DB churn on no-op upserts.

Wiring: `EmbeddingService(repo, embedder, model_name)`. The repo persists,
the embedder produces vectors, `model_name` is stamped on every row so
the consumer can detect model drift.
"""

from __future__ import annotations

import hashlib

from .models import PlaceCore
from .protocols import EmbedderProtocol, EmbeddingsRepoProtocol


class EmbeddingService:
    def __init__(
        self,
        repo: EmbeddingsRepoProtocol,
        embedder: EmbedderProtocol,
        model_name: str,
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        self._model_name = model_name

    async def embed_and_store(self, cores: list[PlaceCore]) -> None:
        """Embed cores whose text or model has changed and upsert the vectors.

        Cores without an `id` are skipped — there's nothing to key the
        stored vector against. Empty input is a no-op.
        """
        if not cores:
            return

        usable = [c for c in cores if c.id is not None]
        if not usable:
            return

        texts = [self._build_text(c) for c in usable]
        hashes = [self._hash(t) for t in texts]

        existing = await self._repo.get_signatures_by_place_ids(
            [c.id for c in usable if c.id is not None]
        )

        # Keep only rows whose (hash, model) doesn't already match the DB.
        pending: list[tuple[str, str, str]] = []  # (place_id, text, hash)
        for core, text, h in zip(usable, texts, hashes, strict=True):
            assert core.id is not None  # filtered above
            sig = existing.get(core.id)
            if sig is not None and sig == (h, self._model_name):
                continue
            pending.append((core.id, text, h))

        if not pending:
            return

        vectors = await self._embedder.embed(
            [text for _, text, _ in pending], input_type="document"
        )

        records = [
            (pid, vec, self._model_name, h)
            for (pid, _, h), vec in zip(pending, vectors, strict=True)
        ]
        await self._repo.upsert_embeddings(records)

    @staticmethod
    def _build_text(core: PlaceCore) -> str:
        """Serialize the core as JSON for embedding.

        Identity and timestamp fields carry no semantic signal for retrieval
        and are dropped to keep the embedded text stable across re-saves.
        """
        return core.model_dump_json(
            exclude={"id", "provider_id", "created_at", "refreshed_at"}
        )

    @staticmethod
    def _hash(text: str) -> str:
        """SHA-256 hex of the source text — the diff key for re-embed checks."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
