"""SQLAlchemy ORM models for places_v2 and user_places tables.

Kept internal to this library (_orm prefix). All external code uses
Pydantic models (PlaceCore, UserPlace) — only PlacesRepo and UserPlacesRepo
touch these ORM classes.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from totoro_ai.db.base import Base


class PlaceV2(Base):
    __tablename__ = "places_v2"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    provider_id: Mapped[str | None] = mapped_column(String, nullable=True, index=False)

    place_name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    attributes: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    location: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user_places: Mapped[list[UserPlaceOrm]] = relationship(
        "UserPlaceOrm", back_populates="place", cascade="all, delete-orphan"
    )


class UserPlaceOrm(Base):
    __tablename__ = "user_places"

    user_place_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    place_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("places_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    needs_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    liked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    visited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    place: Mapped[PlaceV2] = relationship("PlaceV2", back_populates="user_places")
