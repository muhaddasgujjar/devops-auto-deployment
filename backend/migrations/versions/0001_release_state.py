"""Initial PostgreSQL contracts. Immutable migration: use a new revision to change it."""
from alembic import op

revision = '0001_release_state'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        '''CREATE TABLE projects (slug text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now())''',
        '''CREATE TABLE environments (
            id text PRIMARY KEY, project text NOT NULL REFERENCES projects(slug), name text NOT NULL,
            job text NOT NULL, version bigint NOT NULL DEFAULT 0 CHECK(version >= 0),
            desired_release_id text, stable_release_id text, stable_revision text, stable_hash text,
            stable_image text, source_uid text, last_observed_at timestamptz,
            freshness text NOT NULL DEFAULT 'unknown' CHECK(freshness IN ('unknown','historical','current','unavailable')),
            detail text, UNIQUE(project,name))''',
        '''CREATE TABLE builds (
            id text PRIMARY KEY, project text NOT NULL REFERENCES projects(slug), job text NOT NULL,
            number bigint NOT NULL CHECK(number > 0), source_commit text NOT NULL CHECK(source_commit ~ '^[a-f0-9]{40}$'),
            result text NOT NULL, UNIQUE(project,job,number))''',
        '''CREATE TABLE artifacts (
            id text PRIMARY KEY, build_id text NOT NULL UNIQUE REFERENCES builds(id), image text NOT NULL,
            scanned_image_id text, reported_high_critical integer CHECK(reported_high_critical >= 0),
            refs jsonb NOT NULL DEFAULT '{}')''',
        '''CREATE TABLE releases (
            id text PRIMARY KEY, environment_id text NOT NULL REFERENCES environments(id),
            build_id text NOT NULL REFERENCES builds(id), environment_commit text NOT NULL CHECK(environment_commit ~ '^[a-f0-9]{40}$'),
            candidate_hash text, status text NOT NULL CHECK(status IN
                ('published','progressing','promoted','rejected','readiness_aborted','inconclusive','telemetry_error','aborted')),
            observation_sequence bigint NOT NULL CHECK(observation_sequence >= 0),
            source_uid text, observed_at timestamptz NOT NULL, UNIQUE(environment_id,build_id))''',
        '''ALTER TABLE environments ADD CONSTRAINT desired_release_fk FOREIGN KEY(desired_release_id) REFERENCES releases(id)''',
        '''ALTER TABLE environments ADD CONSTRAINT stable_release_fk FOREIGN KEY(stable_release_id) REFERENCES releases(id)''',
        '''CREATE TABLE incoming_events (
            id text PRIMARY KEY, environment_id text NOT NULL REFERENCES environments(id), external_id text NOT NULL,
            payload_hash text NOT NULL CHECK(payload_hash ~ '^[a-f0-9]{64}$'),
            request_hash text NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'), payload jsonb NOT NULL,
            actor text NOT NULL, source text NOT NULL, result jsonb NOT NULL,
            occurred_at timestamptz, ingested_at timestamptz NOT NULL DEFAULT now(), UNIQUE(environment_id,external_id))''',
        '''CREATE TABLE analyses (
            id text PRIMARY KEY, release_id text NOT NULL REFERENCES releases(id), name text NOT NULL,
            phase text NOT NULL, data jsonb NOT NULL, UNIQUE(release_id,name))''',
        '''CREATE TABLE observations (
            id text PRIMARY KEY, release_id text NOT NULL REFERENCES releases(id), event_id text NOT NULL REFERENCES incoming_events(id),
            quality text NOT NULL CHECK(quality IN ('accepted','historical','excluded','not_measured')),
            stable_requests integer NOT NULL CHECK(stable_requests >= 0),
            stable_non_200 integer NOT NULL CHECK(stable_non_200 >= 0 AND stable_non_200 <= stable_requests),
            data jsonb NOT NULL, UNIQUE(event_id,release_id))''',
        '''CREATE TABLE audit (
            id bigserial PRIMARY KEY, environment_id text NOT NULL REFERENCES environments(id),
            event_id text NOT NULL REFERENCES incoming_events(id), action text NOT NULL,
            version bigint NOT NULL, data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())''',
        '''CREATE INDEX releases_environment_idx ON releases(environment_id)''',
        '''CREATE INDEX audit_environment_idx ON audit(environment_id,id)''',
    ]
    for statement in statements:
        op.execute(statement)


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled; restore a verified backup into an empty database')
