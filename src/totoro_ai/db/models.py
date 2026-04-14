from datetime import datetime
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from totoro_ai.db.base import Base

# CRITICAL: Must match config.embeddings.dimensions in app.yaml (currently 1024)
# ADR-040: Voyage 4-lite chosen for 9.25% better retrieval quality
# If embedding model changes, update BOTH this constant AND app.yaml
EMBEDDING_DIMENSIONS = 1024


class Place(Base):
    """The `places` table. Reshape per ADR-054 / feature 019.

    Tier 1 storage — holds only OUR data. No Google content lives here beyond
    the namespaced `provider_id` string. Tier 2/3 data (lat/lng, address,
    hours, rating, phone, photo, popularity) lives in Redis and is attached
    at read time by PlacesService.enrich_batch.

    The only code that reads or writes this ORM is `core/places/repository.py`
    (PlacesRepository). Every other service in the app consumes `PlaceObject`
    (Pydantic) instances.
    """

    __tablename__ = "places"
    __table_args__ = (
        # Partial unique index: at most one place per provider_id (non-null);
        # many places with provider_id=NULL are allowed.
        Index(
            "uq_places_provider_id",
            "provider_id",
            unique=True,
            postgresql_where=text("provider_id IS NOT NULL"),
        ),
        # Composite index for "all places for this user of this type" queries.
        Index("ix_places_user_type", "user_id", "place_type"),
        # The `places_fts_idx` GIN index and the `search_vector` generated
        # column are created directly by migration
        # a1b2c3d4e5f6_places_search_vector_generated_column. Do not declare
        # them here — SQLAlchemy cannot express a GENERATED ALWAYS AS STORED
        # column natively, and we don't want autogenerate to drop/recreate
        # the index on every run.
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    place_name: Mapped[str] = mapped_column(String, nullable=False)
    place_type: Mapped[str] = mapped_column(String, nullable=False)
    subcategory: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Read-only tsvector column (GENERATED ALWAYS AS ... STORED). Computed
    # by PostgreSQL from place_name, subcategory, and selected JSONB
    # attributes. PlacesRepository excludes this from every INSERT/UPDATE.
    search_vector: Mapped[str | None] = mapped_column(
        "search_vector", nullable=True
    )

    embeddings: Mapped[list["Embedding"]] = relationship(
        "Embedding", back_populates="place", cascade="all, delete-orphan"
    )


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    place_id: Mapped[str] = mapped_column(
        String, ForeignKey("places.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    vector: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    place: Mapped["Place"] = relationship("Place", back_populates="embeddings")


class SignalType(PyEnum):
    """Behavioral signal types for taste model updates"""

    SAVE = "save"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"
    REPEAT_VISIT = "repeat_visit"
    SEARCH_ACCEPTED = "search_accepted"
    ONBOARDING_EXPLICIT = "onboarding_explicit"


class TasteModel(Base):
    __tablename__ = "taste_model"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)  # type: ignore[type-arg]
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    interaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InteractionLog(Base):
    """Append-only log of behavioral signals for taste model updates"""

    __tablename__ = "interaction_log"

    id: Mapped[str] = mapped_column(
        PGUUID, primary_key=True, default=lambda: str(UUID(int=0))
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    signal_type: Mapped[SignalType] = mapped_column(
        Enum(
            SignalType,
            native_enum=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    place_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("places.id", ondelete="SET NULL"), nullable=True
    )
    gain: Mapped[float] = mapped_column(Float, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)  # type: ignore[type-arg]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConsultLog(Base):
    """Append-only record of AI consult recommendations (ADR-053).

    Table owned by this repo (Alembic). Distinct from the NestJS 'recommendations'
    table — see ADR-053 for write-ownership split.
    """

    __tablename__ = "consult_logs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)  # type: ignore[type-arg]
    intent: Mapped[str] = mapped_column(String, nullable=False)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    selected_place_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserMemory(Base):
    """Append-only store of personal facts extracted from user messages.

    Extracted facts are deduped at database level via UNIQUE(user_id, memory).
    No foreign key to users table (Constitution VI: cross-repo boundary).
    """

    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "memory",
            name="uq_user_memories_user_memory",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    memory: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
