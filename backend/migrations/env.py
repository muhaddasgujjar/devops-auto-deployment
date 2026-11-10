from alembic import context
from sqlalchemy import create_engine
from backend.config import load_settings


def run():
    engine = create_engine(load_settings().database_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
