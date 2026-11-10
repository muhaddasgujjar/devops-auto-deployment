"""Deployment identity, durable post-promotion health and serialized recovery."""
from alembic import op

revision = '0002_recovery'
down_revision = '0001_release_state'
branch_labels = depends_on = None


def upgrade():
    for statement in [
        'ALTER TABLE releases DROP CONSTRAINT releases_environment_id_build_id_key',
        'ALTER TABLE releases ADD CONSTRAINT release_deployment_unique UNIQUE(environment_id,build_id,environment_commit)',
        'ALTER TABLE releases ADD COLUMN promoted_at timestamptz',
        "UPDATE releases SET promoted_at=observed_at WHERE status='promoted'",
        'ALTER TABLE environments ADD COLUMN observation_sequence bigint NOT NULL DEFAULT 0',
        '''UPDATE environments e SET observation_sequence=COALESCE((SELECT max(r.observation_sequence)
           FROM releases r WHERE r.environment_id=e.id AND r.source_uid=e.source_uid),0)''',
        '''CREATE TABLE recoveries (
          id text PRIMARY KEY, environment_id text NOT NULL REFERENCES environments(id),
          origin_release_id text NOT NULL REFERENCES releases(id), target_release_id text REFERENCES releases(id),
          base_commit text NOT NULL CHECK(base_commit ~ '^[a-f0-9]{40}$'),
          policy text NOT NULL, trigger jsonb NOT NULL,
          phase text NOT NULL CHECK(phase IN ('proposed','applying','verifying','recovered','failed','superseded')),
          version bigint NOT NULL DEFAULT 0, recovery_commit text CHECK(recovery_commit ~ '^[a-f0-9]{40}$'),
          outcome text, evidence jsonb NOT NULL DEFAULT '{}',
          created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE(environment_id,origin_release_id,policy))''',
        '''CREATE UNIQUE INDEX one_active_recovery ON recoveries(environment_id)
          WHERE phase IN ('proposed','applying','verifying')''',
        'ALTER TABLE releases ADD COLUMN recovery_id text REFERENCES recoveries(id)',
        '''CREATE TABLE health_windows (
          id text PRIMARY KEY, environment_id text NOT NULL REFERENCES environments(id),
          release_id text NOT NULL REFERENCES releases(id), window_end timestamptz NOT NULL,
          quality text NOT NULL CHECK(quality IN ('measured','unavailable')),
          data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE(environment_id,release_id,window_end))''',
        '''CREATE TABLE recovery_events (
          id text PRIMARY KEY, recovery_id text NOT NULL REFERENCES recoveries(id),
          event_id text NOT NULL UNIQUE REFERENCES incoming_events(id), phase text NOT NULL,
          data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())''',
    ]:
        op.execute(statement)


def downgrade():
    raise RuntimeError('Restore a verified backup into a new database; destructive downgrade is disabled')
