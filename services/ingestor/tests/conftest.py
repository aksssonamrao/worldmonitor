import sys
import types

if 'asyncpg' not in sys.modules:
    fake = types.ModuleType('asyncpg')
    fake.Pool = object

    async def create_pool(*args, **kwargs):
        raise RuntimeError('asyncpg unavailable in test environment')

    fake.create_pool = create_pool
    sys.modules['asyncpg'] = fake
