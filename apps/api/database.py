import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def database(url=None):
    url = url or os.environ['RELEASE_DATABASE_URL']
    options = {'pool_pre_ping': True}
    if url.startswith('postgresql'):
        options.update(pool_size=3, max_overflow=1, connect_args={'connect_timeout': 5})
    elif url.startswith('sqlite'):
        options['connect_args'] = {'check_same_thread': False}
    engine = create_engine(url, **options)
    return engine, sessionmaker(engine, expire_on_commit=False)
