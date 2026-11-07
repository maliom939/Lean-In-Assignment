"""API response models. Field names here are the public contract."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Personalization = Literal["interests", "memberships", "cold_start"]
ReasonCode = Literal[
    "topic_match",
    "tag_match",
    "related_to_your_circles",
    "active",
    "open_to_join",
    "request_to_join",
    "spots_left",
    "near_you",
    "virtual",
    "popular",
]
ExclusionReason = Literal["already_member", "unlisted", "full", "inactive"]


class CircleSummary(BaseModel):
    id: int
    name: str
    topic: str | None
    topic_label: str | None
    format: Literal["in_person", "virtual", "hybrid"]
    join_policy: Literal["open", "request"]
    member_count: int
    max_members: int | None = Field(description="null = uncapped")
    spots_left: int | None = Field(description="null = uncapped")


class Reason(BaseModel):
    code: ReasonCode
    text: str


class LeaderSummary(BaseModel):
    first_name: str
    job_title: str | None


class SimilarCircle(BaseModel):
    id: int
    name: str


class ScoreBreakdown(BaseModel):
    topic: int
    activity: int
    join: int
    attend: int
    total: int


class Recommendation(BaseModel):
    rank: int
    circle: CircleSummary
    explanation: str
    reasons: list[Reason]
    leader: LeaderSummary | None = None
    similar_circles: list[SimilarCircle] = Field(default_factory=list)
    score: ScoreBreakdown | None = Field(default=None, description="Only with ?debug=true")


class ExcludedCircle(BaseModel):
    id: int
    name: str
    reason: ExclusionReason


class DebugInfo(BaseModel):
    excluded: list[ExcludedCircle]


class RecommendationResponse(BaseModel):
    user_id: int
    reference_time: datetime
    personalization: Personalization
    recommendations: list[Recommendation]
    hint: str | None = None
    debug: DebugInfo | None = Field(default=None, description="Only with ?debug=true")
