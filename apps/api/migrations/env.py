from alembic import context
from apps.api.database import database
from apps.api.models import Base

engine, _ = database()
try:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
