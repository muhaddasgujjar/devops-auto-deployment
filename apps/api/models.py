"""Product metadata; infrastructure remains authoritative for deployment state."""
from datetime import datetime, timezone
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    repository: Mapped[str] = mapped_column(String(500))
    branch: Mapped[str] = mapped_column(String(160), default='main')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Environment(Base):
    __tablename__ = 'environments'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'))
    name: Mapped[str] = mapped_column(String(80))
    namespace: Mapped[str] = mapped_column(String(80))


class Build(Base):
    __tablename__ = 'builds'
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'))
    number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON)


class Artifact(Base):
    __tablename__ = 'artifacts'
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    image: Mapped[str] = mapped_column(String(500))
    source_commit: Mapped[str | None] = mapped_column(String(64))


class Release(Base):
    __tablename__ = 'releases'
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey('environments.id'))
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey('artifacts.id'))
    state: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON)


class Analysis(Base):
    __tablename__ = 'analyses'
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey('environments.id'))
    data: Mapped[dict] = mapped_column(JSON)


class RecoveryAttempt(Base):
    __tablename__ = 'recovery_attempts'
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey('environments.id'))
    data: Mapped[dict] = mapped_column(JSON)


class EvidenceRun(Base):
    __tablename__ = 'evidence_runs'
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    verdict: Mapped[str] = mapped_column(String(120))
    data: Mapped[dict] = mapped_column(JSON)


class Observation(Base):
    __tablename__ = 'observations'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    data: Mapped[dict] = mapped_column(JSON)


class InboxEvent(Base):
    __tablename__ = 'inbox_events'
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON)


class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    __table_args__ = (UniqueConstraint('deduplication_key'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deduplication_key: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON)
