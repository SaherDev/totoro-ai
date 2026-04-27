"""EmbeddingService — turn PlaceCore rows into vectors and persist them.

Black-box contract: the service serializes the whole `PlaceCore` (via
`model_dump_json`) and hands the string to an external embedder. No
field-by-field hand picking — when `PlaceCore` grows new fields, the
embedded text grows with it for free, and retrieval evals can tune the
embedder/model without touching this code.

Wiring: `EmbeddingService(repo, embedder, model_name)`. The repo persists,
the embedder produces vectors, `model_name` is stamped on every row so
the consumer can detect model drift.
"""

from __future__ import annotations

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
        """Embed every core and upsert the vectors.

        Cores without an `id` are skipped — there's nothing to key the
        stored vector against. Empty input is a no-op.
        """
        if not cores:
            return

        usable = [c for c in cores if c.id is not None]
        if not usable:
            return

        texts = [self._build_text(c) for c in usable]
        vectors = await self._embedder.embed(texts, input_type="document")

        records = [
            (c.id, vec, self._model_name)
            for c, vec in zip(usable, vectors, strict=True)
            if c.id is not None
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
