from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha = Annotated[str, Field(pattern=r'^[a-f0-9]{40}$')]
DigestImage = Annotated[str, Field(pattern=r'^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$', max_length=512)]
PodHash = Annotated[str, Field(pattern=r'^[a-z0-9]{5,32}$')]
Revision = Annotated[str, Field(pattern=r'^[a-f0-9]{40}-jenkins-[1-9][0-9]*$')]
EventId = Annotated[str, Field(pattern=r'^[A-Za-z0-9_.:-]{1,160}$')]
Status = Literal['published', 'progressing', 'promoted', 'rejected', 'readiness_aborted',
                 'inconclusive', 'telemetry_error', 'aborted']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Analysis(Contract):
    name: str = Field(min_length=1, max_length=253)
    phase: Literal['Pending', 'Running', 'Successful', 'Failed', 'Error', 'Inconclusive']
    metrics: list[dict] = Field(default_factory=list, max_length=20)


class ReleaseObservation(Contract):
    build_number: int = Field(gt=0, le=2**63 - 1)
    source_commit: Sha
    image: DigestImage
    environment_commit: Sha
    candidate_hash: PodHash | None = None
    status: Status
    observation_sequence: int = Field(default=1, ge=1, le=2**63 - 1)
    source_uid: str | None = Field(default=None, min_length=1, max_length=64)
    observed_at: datetime
    stable_revision: Revision | None = None
    stable_hash: PodHash | None = None
    stable_image: DigestImage | None = None
    scanned_image_id: Annotated[str, Field(pattern=r'^sha256:[a-f0-9]{64}$')] | None = None
    reported_high_critical: int | None = Field(default=None, ge=0)
    artifacts: dict[str, str] = Field(default_factory=dict)
    analyses: list[Analysis] = Field(default_factory=list, max_length=20)
    quality: Literal['accepted', 'historical', 'excluded', 'not_measured'] = 'not_measured'
    stable_requests: int = Field(default=0, ge=0)
    stable_non_200: int = Field(default=0, ge=0)
    observation_details: dict = Field(default_factory=dict)
    recovery_id: Annotated[str, Field(pattern=r'^[a-f0-9-]{36}$')] | None = None

    @model_validator(mode='after')
    def consistent(self):
        if self.observed_at.tzinfo is None:
            raise ValueError('Observed time must include a timezone')
        if self.stable_non_200 > self.stable_requests:
            raise ValueError('Non-200 count exceeds total samples')
        if self.quality == 'accepted' and (self.stable_requests < 2 or self.stable_non_200):
            raise ValueError('Accepted observations require measured healthy stable requests')
        if self.status == 'promoted' and (not self.candidate_hash or self.stable_hash != self.candidate_hash or
                self.stable_revision != f'{self.source_commit}-jenkins-{self.build_number}'):
            raise ValueError('Promoted candidate must match the serving revision and hash')
        if bool(self.stable_hash) != bool(self.stable_revision):
            raise ValueError('Stable hash and revision must be supplied together')
        if len({x.name for x in self.analyses}) != len(self.analyses):
            raise ValueError('Duplicate analysis identity')
        return self


class ImportRequest(Contract):
    event_id: EventId
    expected_version: int = Field(ge=0)
    kind: Literal['ci_acceptance', 'runtime_acceptance', 'ci_negative_gate', 'recovery_target']
    report: dict


class CallbackRequest(Contract):
    event_id: EventId
    expected_version: int = Field(ge=0)
    release: ReleaseObservation | None = None
    unavailable: Literal['sources_unavailable', 'sources_changing', 'identity_mismatch'] | None = None

    @model_validator(mode='after')
    def exactly_one(self):
        if (self.release is None) == (self.unavailable is None):
            raise ValueError('Supply one release observation or an unavailability code')
        if self.release and self.release.status != 'published' and not self.release.source_uid:
            raise ValueError('Controller observations require a controller UID')
        return self


class FailedBuild(Contract):
    build_number: int = Field(gt=0, le=2**63 - 1)
    source_commit: Sha


class HealthWindow(Contract):
    event_id: EventId
    expected_version: int = Field(ge=0)
    release_id: str = Field(max_length=64)
    pod_hash: PodHash
    window_end: datetime
    quality: Literal['measured', 'unavailable']
    data: dict


class RecoveryEvent(Contract):
    event_id: EventId
    expected_version: int = Field(ge=0)
    expected_recovery_version: int = Field(ge=0)
    phase: Literal['applying', 'verifying', 'recovered', 'failed', 'superseded']
    recovery_commit: Sha | None = None
    outcome: Literal['git_unavailable','concurrent_git_change','verification_timeout','source_unavailable',
                     'no_accepted_target','healthy_target_verified','newer_release'] | None = None
    evidence: dict = Field(default_factory=dict)


class NativeAlert(Contract):
    name: Literal['DemoPodsUnavailable','DemoRequestErrors','DemoRequestLatency']
    revision: str = Field(max_length=64,pattern=r'^[a-z0-9-]*$')
    state: Literal['pending','firing']


class MonitoringTick(Contract):
    observed_at: datetime
    telemetry_available: bool = Field(strict=True)
    alerts: list[NativeAlert] = Field(default_factory=list,max_length=20)

    @model_validator(mode='after')
    def consistent_probe(self):
        if not self.telemetry_available and self.alerts:
            raise ValueError('Unavailable telemetry cannot supply current native alerts')
        return self


class DeliveryResult(Contract):
    lease_id: str = Field(min_length=36,max_length=36)
    delivered: bool = Field(strict=True)
    receipt_id: str | None = Field(default=None,max_length=64)
    receipt_sha256: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    result: Literal['receiver_acknowledged','receiver_unavailable','invalid_receipt']
