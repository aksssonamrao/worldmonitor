import sys
import types
from pathlib import Path

# Ensure ingestor's local `app` package wins over other services' `app` packages during root-level pytest runs.
for key in list(sys.modules):
    if key == 'app' or key.startswith('app.'):
        sys.modules.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if 'asyncpg' not in sys.modules:
    fake = types.ModuleType('asyncpg')
    fake.Pool = object

    async def create_pool(*args, **kwargs):
        raise RuntimeError('asyncpg unavailable in test environment')

    fake.create_pool = create_pool
    sys.modules['asyncpg'] = fake
