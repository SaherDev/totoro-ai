from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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
    __tablename__ = "places"
    __table_args__ = (
        UniqueConstraint(
            "external_provider",
            "external_id",
            name="uq_places_provider_external",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    place_name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=False)
    cuisine: Mapped[str | None] = mapped_column(String, nullable=True)
    price_range: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    external_provider: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    ambiance: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
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
