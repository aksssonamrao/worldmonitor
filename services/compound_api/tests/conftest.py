import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault('GOOGLE_WEATHER_API_KEY', 'test-key')

if 'asyncpg' not in sys.modules:
    fake = types.ModuleType('asyncpg')
    fake.Pool = object

    async def create_pool(*args, **kwargs):
        raise RuntimeError('asyncpg unavailable in test environment')

    fake.create_pool = create_pool
    sys.modules['asyncpg'] = fake
