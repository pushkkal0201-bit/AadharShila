"""Relational domain model. Flexible snapshot payloads are additionally versioned JSON."""
from datetime import datetime, timezone
from sqlalchemy import String, ForeignKey, DateTime, Integer, Boolean, Text, Numeric, JSON, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
import uuid

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)

class Organization(Base):
    __tablename__="organizations"
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    name: Mapped[str] = mapped_column(String(140), unique=True)

class User(Base):
    __tablename__="users"
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'),index=True)
    username: Mapped[str] = mapped_column(String(100),unique=True,index=True)
    password_hash: Mapped[str] = mapped_column(String(250))
    oidc_subject: Mapped[str|None] = mapped_column(String(200),nullable=True,unique=True,index=True)
    role: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean,default=True)

class Application(Base):
    __tablename__="applications"
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'),index=True)
    reference: Mapped[str] = mapped_column(String(30),unique=True,index=True)
    product: Mapped[str] = mapped_column(String(20))
    applicant_type: Mapped[str] = mapped_column(String(20))
    applicant_name: Mapped[str] = mapped_column(String(150))
    location: Mapped[str] = mapped_column(String(150),default='')
    amount: Mapped[float] = mapped_column(Numeric(16,2))
    tenure_months: Mapped[int] = mapped_column(Integer)
    declared_income: Mapped[float] = mapped_column(Numeric(16,2))
    existing_obligations: Mapped[float] = mapped_column(Numeric(16,2),default=0)
    property_value: Mapped[float] = mapped_column(Numeric(16,2),default=0)
    employment: Mapped[str] = mapped_column(String(150),default='')
    workflow: Mapped[str] = mapped_column(String(30),default='DRAFT')
    verification: Mapped[str] = mapped_column(String(30),default='NOT_REQUESTED')
    revision: Mapped[int] = mapped_column(Integer,default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class Participant(Base):
    __tablename__='participants'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    relationship: Mapped[str]=mapped_column(String(24)) # APPLICANT/CO_APPLICANT/GUARANTOR
    name: Mapped[str]=mapped_column(String(150))
    accepted_monthly_income: Mapped[float]=mapped_column(Numeric(16,2),default=0)

class Consent(Base):
    __tablename__='consents'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    subject_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    purpose: Mapped[str]=mapped_column(String(80))
    provider: Mapped[str]=mapped_column(String(80),default='')
    categories: Mapped[list]=mapped_column(JSON,default=list)
    notice_version: Mapped[str]=mapped_column(String(20),default='demo-v1')
    granted_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    revoked_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)

class Evidence(Base):
    __tablename__='evidence'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    key: Mapped[str]=mapped_column(String(80),index=True)
    value: Mapped[dict]=mapped_column(JSON)
    provider: Mapped[str]=mapped_column(String(100),default='borrower')
    mode: Mapped[str]=mapped_column(String(20),default='SELF_REPORTED')
    verification: Mapped[str]=mapped_column(String(30),default='UNRESOLVED')
    captured_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    revision: Mapped[int]=mapped_column(Integer,default=1)
    source_document_id: Mapped[str|None]=mapped_column(String(36),nullable=True)
    provider_invocation_id: Mapped[str|None]=mapped_column(ForeignKey('provider_invocations.id'),nullable=True,index=True)

class Document(Base):
    __tablename__='documents'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    filename: Mapped[str]=mapped_column(String(255))
    media_type: Mapped[str]=mapped_column(String(80))
    byte_count: Mapped[int]=mapped_column(Integer)
    sha256: Mapped[str]=mapped_column(String(64),index=True)
    storage_format: Mapped[str]=mapped_column(String(32),default='PLAINTEXT_DEVELOPMENT')
    storage_sha256: Mapped[str|None]=mapped_column(String(64),nullable=True)
    encryption_key_id: Mapped[str|None]=mapped_column(String(64),nullable=True)
    path: Mapped[str]=mapped_column(Text)
    version: Mapped[int]=mapped_column(Integer,default=1)
    parse_status: Mapped[str]=mapped_column(String(30),default='RECEIVED')
    extracted_text: Mapped[str]=mapped_column(Text,default='')
    extracted_fields: Mapped[dict]=mapped_column(JSON,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Policy(Base):
    __tablename__='policies'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    name: Mapped[str]=mapped_column(String(100))
    product: Mapped[str]=mapped_column(String(20),index=True)
    version: Mapped[int]=mapped_column(Integer)
    state: Mapped[str]=mapped_column(String(30),default='DRAFT')
    config: Mapped[dict]=mapped_column(JSON)
    author_id: Mapped[str|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    approver_id: Mapped[str|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    __table_args__=(
        UniqueConstraint('org_id','product','version',name='uq_policies_org_product_version'),
        Index('uq_policies_one_active_per_org_product','org_id','product',unique=True,
              sqlite_where=text("state='ACTIVE'"),postgresql_where=text("state='ACTIVE'")),
    )

class Assessment(Base):
    __tablename__='assessments'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    revision: Mapped[int]=mapped_column(Integer)
    execution: Mapped[str]=mapped_column(String(30),default='COMPLETED')
    outcome: Mapped[str]=mapped_column(String(20))
    policy_id: Mapped[str]=mapped_column(ForeignKey('policies.id'))
    snapshot: Mapped[dict]=mapped_column(JSON)
    result: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    engine_version: Mapped[str]=mapped_column(String(30),default='deterministic-1')

class Conflict(Base):
    __tablename__='conflicts'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    assessment_id: Mapped[str]=mapped_column(ForeignKey('assessments.id'),index=True)
    code: Mapped[str]=mapped_column(String(60))
    detail: Mapped[dict]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String(20),default='OPEN')

class ReviewTask(Base):
    __tablename__='review_tasks'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    assessment_id: Mapped[str|None]=mapped_column(ForeignKey('assessments.id'),nullable=True)
    reason_code: Mapped[str]=mapped_column(String(80))
    status: Mapped[str]=mapped_column(String(20),default='OPEN')
    request_text: Mapped[str]=mapped_column(Text,default='')
    resolution: Mapped[str]=mapped_column(Text,default='')
    actor_id: Mapped[str|None]=mapped_column(ForeignKey('users.id'),nullable=True)

class AuditEvent(Base):
    __tablename__='audit_events'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str|None]=mapped_column(ForeignKey('applications.id'),nullable=True,index=True)
    actor_id: Mapped[str|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    role: Mapped[str]=mapped_column(String(40),default='system')
    action: Mapped[str]=mapped_column(String(80))
    reason: Mapped[str]=mapped_column(Text,default='')
    detail: Mapped[dict]=mapped_column(JSON,default=dict)
    timestamp: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    correlation_id: Mapped[str]=mapped_column(String(36),default=uid)

class Job(Base):
    __tablename__='jobs'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    target_revision: Mapped[int]=mapped_column(Integer)
    kind: Mapped[str]=mapped_column(String(60),default='ASSESS')
    status: Mapped[str]=mapped_column(String(25),default='QUEUED',index=True)
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    claimed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    last_error: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('application_id','target_revision','kind'),)

class ProviderInvocation(Base):
    __tablename__='provider_invocations'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    application_id: Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    evidence_key: Mapped[str]=mapped_column(String(80))
    provider_name: Mapped[str]=mapped_column(String(100))
    operation: Mapped[str]=mapped_column(String(60),default='FETCH_EVIDENCE')
    mode: Mapped[str]=mapped_column(String(20))
    status: Mapped[str]=mapped_column(String(30))
    request_id: Mapped[str]=mapped_column(String(36),default=uid)
    error_category: Mapped[str|None]=mapped_column(String(80),nullable=True)
    response_metadata: Mapped[dict]=mapped_column(JSON,default=dict)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
