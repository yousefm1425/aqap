from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

Rating = Literal["met", "partial", "not_met", "na"]
Adequacy = Literal["suitable", "unsuitable", "insufficient"]
Verdict = Literal["conforms", "not_conforming", "insufficient"]
AssessmentStatus = Literal["draft", "submitted", "returned", "hod_approved", "under_audit", "audited", "final"]
EvidenceKind = Literal["file", "link", "image", "form"]
ActionStatus = Literal["draft", "submitted", "revision", "approved", "completed", "verified", "cancelled"]


class CycleCreate(BaseModel):
    framework_id: int
    title_ar: str = Field(min_length=3)
    academic_year: str
    starts_on: date
    ends_on: date
    department_ids: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _dates(self):
        if self.ends_on < self.starts_on:
            raise ValueError("تاريخ النهاية قبل تاريخ البداية")
        return self


class SelfAssessmentPatch(BaseModel):
    self_rating: Rating | None = None
    self_adequacy: Adequacy | None = None
    self_notes: str | None = None


class ExternalAssessmentPatch(BaseModel):
    ext_verdict: Verdict | None = None
    ext_recommendation: str | None = None


class TransitionIn(BaseModel):
    to_status: AssessmentStatus
    comment: str | None = None


class EvidenceCreate(BaseModel):
    title_ar: str = Field(min_length=3)
    description_ar: str | None = None
    kind: EvidenceKind
    url: HttpUrl | None = None
    department_id: int | None = None
    confidentiality: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def _link(self):
        if self.kind == "link" and self.url is None:
            raise ValueError("الشاهد من نوع رابط يتطلب url")
        return self


class EvidenceLink(BaseModel):
    evidence_id: int
    note: str | None = None


class ActionCreate(BaseModel):
    cycle_id: int
    assessment_id: int | None = None
    department_id: int | None = None
    source: Literal["self_assessment", "external_review", "internal_audit", "kpi", "other"] = "external_review"
    title_ar: str = Field(min_length=3)
    action_ar: str | None = None
    owner_id: int | None = None
    owner_label: str | None = None
    priority: int = Field(default=2, ge=1, le=3)
    due_date: date | None = None


class ActionPatch(BaseModel):
    title_ar: str | None = Field(default=None, min_length=3)
    action_ar: str | None = None
    owner_id: int | None = None
    owner_label: str | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    due_date: date | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    completion_evidence_id: int | None = None
    completed_on: date | None = None


class ActionTransitionIn(BaseModel):
    to_status: ActionStatus
    comment: str | None = None
    adequacy: Adequacy | None = None


class MinutesRecommendationIn(BaseModel):
    text_ar: str = Field(min_length=2)
    responsible_ar: str | None = None
    period_ar: str | None = None


class MinutesAgendaIn(BaseModel):
    title_ar: str = Field(min_length=2)
    recommendations: list[MinutesRecommendationIn] = Field(default_factory=list, max_length=20)


class MinutesAttendeeIn(BaseModel):
    name_ar: str = Field(min_length=2)
    role_ar: str | None = None
    user_id: int | None = None


class MinutesCreate(BaseModel):
    template_id: int
    department_id: int


class MinutesDoc(BaseModel):
    title_ar: str = Field(min_length=3)
    semester: Literal["الأول", "الثاني", "الصيفي"] = "الأول"
    meeting_date: date | None = None
    start_time: str | None = None
    location_ar: str | None = None
    follow_up_owner: str | None = None
    agenda: list[MinutesAgendaIn] = Field(default_factory=list, max_length=12)
    attendees: list[MinutesAttendeeIn] = Field(default_factory=list, max_length=60)


class MinutesTransitionIn(BaseModel):
    to_status: Literal["submitted", "approved", "returned"]
    comment: str | None = None


class FollowUpIn(BaseModel):
    fu_status: Literal["done", "partial", "not_done"] | None = None
    fu_obstacles: str | None = None
    fu_solutions: str | None = None
