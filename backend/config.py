import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_keys: dict[str, str]
    callback_secret: str
    project: str = 'release-demo'
    environment: str = 'dev'
    job: str = 'release-merged'
    stale_seconds: int = 300
    max_body_bytes: int = 1_048_576

    def __post_init__(self):
        if not self.database_url.startswith('postgresql+psycopg://'):
            raise ValueError('A PostgreSQL psycopg URL is required')
        if not self.api_keys or any(not re.fullmatch(r'[a-f0-9]{64}', key) or
                                    role not in {'read', 'developer', 'admin', 'recovery', 'notifier'} for key, role in self.api_keys.items()):
            raise ValueError('Configure hashed API keys and read/developer/admin roles')
        if len(self.callback_secret) < 32:
            raise ValueError('A separate callback secret of at least 32 characters is required')


def load_settings():
    path = os.environ.get('RELEASE_CONFIG_FILE')
    if not path:
        raise RuntimeError('Set RELEASE_CONFIG_FILE to a protected configuration file')
    return Settings(**json.loads(Path(path).read_text()))
