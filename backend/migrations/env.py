from alembic import context
from sqlalchemy import create_engine
from backend.security import load_url


def run():
    engine = create_engine(load_url('RELEASE_MIGRATION_CONFIG_FILE'))
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
