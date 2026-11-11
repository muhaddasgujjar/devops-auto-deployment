"""Durable alert transitions and bounded local delivery outbox."""
from alembic import op

revision = '0003_monitoring'
down_revision = '0002_recovery'
branch_labels = depends_on = None


def upgrade():
    for statement in [
        '''CREATE TABLE monitoring_state (
          environment_id text PRIMARY KEY REFERENCES environments(id),
          checked_at timestamptz, telemetry_available boolean,
          native_alerts jsonb NOT NULL DEFAULT '[]')''',
        '''CREATE TABLE monitoring_alerts (
          id text PRIMARY KEY, environment_id text NOT NULL REFERENCES environments(id),
          condition_key text NOT NULL, kind text NOT NULL, subject text NOT NULL,
          state text NOT NULL CHECK(state IN ('firing','resolved')),
          generation integer NOT NULL CHECK(generation>0), data jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE(environment_id,condition_key))''',
        '''CREATE TABLE monitoring_events (
          id text PRIMARY KEY, alert_id text NOT NULL REFERENCES monitoring_alerts(id),
          generation integer NOT NULL CHECK(generation>0), state text NOT NULL CHECK(state IN ('firing','resolved')), actor text NOT NULL, data jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(alert_id,generation,state))''',
        '''CREATE TABLE notification_outbox (
          id text PRIMARY KEY, sequence bigserial NOT NULL UNIQUE, environment_id text NOT NULL REFERENCES environments(id),
          event_id text NOT NULL UNIQUE REFERENCES monitoring_events(id), payload jsonb NOT NULL,
          payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[a-f0-9]{64}$'),
          state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','leased','delivered','dead')),
          attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
          next_attempt_at timestamptz NOT NULL DEFAULT now(), lease_id text, lease_until timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(), delivered_at timestamptz,
          CHECK((state='leased')=(lease_id IS NOT NULL AND lease_until IS NOT NULL)),
          CHECK((lease_id IS NULL)=(lease_until IS NULL)),
          CHECK((state='delivered')=(delivered_at IS NOT NULL)))''',
        '''CREATE TABLE notification_events (
          id text PRIMARY KEY, notification_id text NOT NULL REFERENCES notification_outbox(id),
          attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 5),
          phase text NOT NULL CHECK(phase IN ('claimed','delivered','retry','dead','expired')),
          data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE(notification_id,attempt,phase))''',
        "CREATE INDEX notification_due ON notification_outbox(state,next_attempt_at)",
    ]:
        op.execute(statement)


def downgrade():
    raise RuntimeError('Restore a verified backup into a new database; destructive downgrade is disabled')
