from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel


# ── Read models (full rows returned from DB) ──────────────────────────────────

class Agency(BaseModel):
    id: UUID
    name: str
    industry: Optional[str] = None
    created_at: datetime


class Job(BaseModel):
    id: UUID
    agency_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    required_skills: List[str] = []
    screening_questions: List[dict] = []
    interviewer_tone: str = "professional"
    created_at: datetime


class Candidate(BaseModel):
    id: UUID
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    created_at: datetime


class Interview(BaseModel):
    id: UUID
    job_id: Optional[UUID] = None
    candidate_id: Optional[UUID] = None
    status: str = "pending"
    transcript: List[dict] = []
    scorecard: dict = {}
    recording_url: Optional[str] = None
    interviewer_name: str = "Maya"
    created_at: datetime


class Score(BaseModel):
    id: UUID
    interview_id: UUID
    dimension: str
    score: Optional[int] = None
    reasoning: Optional[str] = None
    overall_score: Optional[int] = None
    hire_recommendation: Optional[bool] = None
    summary: Optional[str] = None
    created_at: datetime


# ── Create / input models (no id or created_at) ───────────────────────────────

class CreateAgency(BaseModel):
    name: str
    industry: Optional[str] = None


class CreateJob(BaseModel):
    agency_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    required_skills: List[str] = []
    screening_questions: List[dict] = []
    interviewer_tone: str = "professional"


class CreateCandidate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None


class CreateInterview(BaseModel):
    job_id: Optional[UUID] = None
    candidate_id: Optional[UUID] = None
    status: str = "pending"
    transcript: List[dict] = []
    scorecard: dict = {}
    recording_url: Optional[str] = None
    interviewer_name: str = "Maya"
