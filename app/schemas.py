from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    """Write model for a points event (immutable once accepted)."""

    event_id: str = Field(min_length=1, max_length=128)
    participant_id: str = Field(min_length=1, max_length=128)
    points: int
    correction_of: Optional[str] = Field(
        default=None,
        description="event_id of an existing event this event corrects; "
        "corrections may themselves be corrected (chain).",
    )


class EventOut(BaseModel):
    event_id: str
    participant_id: str
    points: int
    correction_of: Optional[str]
    revision: int
    created_at: str


class EffectiveEvent(BaseModel):
    event_id: str
    points: int
    revision: int
    correction_of: Optional[str]


class LeaderboardEntry(BaseModel):
    rank: int
    participant_id: str
    total_points: int
    effective_events: List[EffectiveEvent]


class LeaderboardOut(BaseModel):
    revision: int
    entries: List[LeaderboardEntry]


class LeaderboardPageOut(BaseModel):
    revision: int
    entries: List[LeaderboardEntry]
    next_cursor: Optional[str] = Field(
        default=None,
        description="Signed cursor for the next page; null on the last page.",
    )


class LeaderboardPosition(BaseModel):
    """A participant's rank/total at one snapshot revision."""

    rank: int
    total_points: int


class LeaderboardChange(BaseModel):
    participant_id: str
    before: Optional[LeaderboardPosition] = Field(
        default=None, description="Null when the participant did not exist at from_revision."
    )
    after: Optional[LeaderboardPosition] = Field(
        default=None, description="Null when the participant no longer exists at to_revision."
    )
    points_delta: int


class LeaderboardChangesOut(BaseModel):
    from_revision: int
    to_revision: int
    changes: List[LeaderboardChange]
