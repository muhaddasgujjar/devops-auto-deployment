from sqlalchemy import MetaData, create_engine, select, text

HEAD = '0003_monitoring'


class Database:
    def __init__(self, url):
        self.engine = create_engine(url, pool_size=3, max_overflow=2, pool_pre_ping=True,
                                    connect_args={'connect_timeout': 5})
        self.metadata = MetaData()
        with self.engine.connect() as conn:
            privileged = conn.scalar(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls '
                                           'FROM pg_roles WHERE rolname=current_user'))
            owns_tables = conn.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner=current_user"))
            if privileged or owns_tables:
                raise RuntimeError('API requires a restricted role without table ownership')
            if conn.scalar(text('SELECT version_num FROM alembic_version')) != HEAD:
                raise RuntimeError('Database migrations are not at the supported revision')
            self.metadata.reflect(conn, only=['projects', 'environments', 'builds', 'artifacts',
                                             'releases', 'analyses', 'observations', 'incoming_events', 'audit',
                                             'recoveries', 'health_windows', 'recovery_events',
                                             'monitoring_state', 'monitoring_alerts', 'monitoring_events',
                                             'notification_outbox', 'notification_events'])

    def table(self, name):
        return self.metadata.tables[name]

    def ready(self):
        with self.engine.connect() as conn:
            return conn.scalar(text('SELECT version_num FROM alembic_version')) == HEAD

    def close(self):
        self.engine.dispose()
