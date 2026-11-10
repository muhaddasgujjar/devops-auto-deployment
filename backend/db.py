from sqlalchemy import MetaData, create_engine, select, text

HEAD = '0001_release_state'


class Database:
    def __init__(self, url):
        self.engine = create_engine(url, pool_size=3, max_overflow=2, pool_pre_ping=True,
                                    connect_args={'connect_timeout': 5})
        self.metadata = MetaData()
        with self.engine.connect() as conn:
            if conn.scalar(text('SELECT version_num FROM alembic_version')) != HEAD:
                raise RuntimeError('Database migrations are not at the supported revision')
            self.metadata.reflect(conn, only=['projects', 'environments', 'builds', 'artifacts',
                                             'releases', 'analyses', 'observations', 'incoming_events', 'audit'])

    def table(self, name):
        return self.metadata.tables[name]

    def ready(self):
        with self.engine.connect() as conn:
            return conn.scalar(text('SELECT version_num FROM alembic_version')) == HEAD

    def close(self):
        self.engine.dispose()
