from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core import queue


class FakeConn:
    def __init__(self):
        self.rows = {}

    async def execute(self, sql, *args):
        if 'CREATE TABLE IF NOT EXISTS job_queue' in sql:
            return 'CREATE TABLE'
        if 'INSERT INTO job_queue' in sql:
            job_id, job_type, payload, max_attempts, run_after = args
            self.rows[job_id] = {
                'id': job_id,
                'job_type': job_type,
                'payload': payload,
                'status': 'queued',
                'attempts': 0,
                'max_attempts': max_attempts,
                'run_after': run_after or datetime.now(timezone.utc),
                'locked_at': None,
                'locked_by': None,
                'last_error': None,
                'created_at': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc),
            }
            return 'INSERT 1'
        if "SET status='succeeded'" in sql:
            row = self.rows[args[0]]
            row['status'] = 'succeeded'
            row['locked_at'] = None
            row['locked_by'] = None
            return 'UPDATE 1'
        if "SET status='queued', run_after=$2" in sql:
            row = self.rows[args[0]]
            row['status'] = 'queued'
            row['run_after'] = args[1]
            row['locked_at'] = None
            row['locked_by'] = None
            row['last_error'] = args[2]
            return 'UPDATE 1'
        if "SET status='dead'" in sql:
            row = self.rows[args[0]]
            row['status'] = 'dead'
            row['last_error'] = args[1]
            row['locked_at'] = None
            row['locked_by'] = None
            return 'UPDATE 1'
        if "WHERE status='running'" in sql:
            n = 0
            now = datetime.now(timezone.utc)
            stale_min = args[0]
            for row in self.rows.values():
                if row['status'] == 'running' and row['locked_at'] and row['locked_at'] < now - timedelta(minutes=stale_min):
                    row['status'] = 'queued'
                    row['locked_at'] = None
                    row['locked_by'] = None
                    row['run_after'] = now
                    n += 1
            return f'UPDATE {n}'
        return 'OK'

    async def fetchrow(self, sql, *args):
        if 'SELECT attempts, max_attempts FROM job_queue' in sql:
            row = self.rows.get(args[0])
            return {'attempts': row['attempts'], 'max_attempts': row['max_attempts']} if row else None
        if 'WITH candidate AS' in sql:
            worker_id = args[0]
            now = datetime.now(timezone.utc)
            candidates = [r for r in self.rows.values() if r['status'] == 'queued' and r['run_after'] <= now]
            if not candidates:
                return None
            candidates.sort(key=lambda r: (r['run_after'], r['created_at']))
            row = candidates[0]
            row['status'] = 'running'
            row['locked_at'] = now
            row['locked_by'] = worker_id
            row['attempts'] += 1
            return row.copy()
        if "SELECT run_after FROM job_queue WHERE status='queued'" in sql:
            queued = [r for r in self.rows.values() if r['status'] == 'queued']
            if not queued:
                return None
            queued.sort(key=lambda r: r['run_after'])
            return {'run_after': queued[0]['run_after']}
        if "SELECT last_error FROM job_queue WHERE status='dead'" in sql:
            dead = [r for r in self.rows.values() if r['status'] == 'dead']
            if not dead:
                return None
            return {'last_error': dead[-1]['last_error']}
        return None

    async def fetch(self, sql, *args):
        if 'SELECT status, count(*)::int AS count FROM job_queue GROUP BY status' in sql:
            counts = {}
            for r in self.rows.values():
                counts[r['status']] = counts.get(r['status'], 0) + 1
            return [{'status': k, 'count': v} for k, v in counts.items()]
        return []


class AcquireCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        return False


class FakePool:
    def __init__(self):
        self.conn = FakeConn()

    def acquire(self):
        return AcquireCtx(self.conn)


def test_enqueue_creates_row():
    pool = FakePool()
    job_id = __import__('asyncio').run(queue.enqueue(pool, 'ingest_gdelt', {'x': 1}, None))
    assert isinstance(job_id, UUID)
    assert pool.conn.rows[job_id]['job_type'] == 'ingest_gdelt'


def test_claim_next_claims_only_once_sequentially():
    pool = FakePool()
    job_id = __import__('asyncio').run(queue.enqueue(pool, 'ingest_gdelt', {}, None))
    first = __import__('asyncio').run(queue.claim_next(pool, 'w1'))
    second = __import__('asyncio').run(queue.claim_next(pool, 'w2'))
    assert first is not None and first['id'] == job_id
    assert second is None


def test_failed_job_retries_then_dead():
    pool = FakePool()
    job_id = __import__('asyncio').run(queue.enqueue(pool, 'cache_cleanup', {}, None, max_attempts=2))
    __import__('asyncio').run(queue.claim_next(pool, 'w1'))
    __import__('asyncio').run(queue.mark_failed(pool, job_id, 'boom1', retry=True))
    assert pool.conn.rows[job_id]['status'] == 'queued'
    pool.conn.rows[job_id]['run_after'] = datetime.now(timezone.utc) - timedelta(seconds=1)
    __import__('asyncio').run(queue.claim_next(pool, 'w1'))
    __import__('asyncio').run(queue.mark_failed(pool, job_id, 'boom2', retry=True))
    assert pool.conn.rows[job_id]['status'] == 'dead'


def test_enqueue_claim_succeed_flow():
    pool = FakePool()
    job_id = __import__('asyncio').run(queue.enqueue(pool, 'ingest_reliefweb', {}, None))
    claimed = __import__('asyncio').run(queue.claim_next(pool, 'w1'))
    assert claimed is not None and claimed['id'] == job_id
    __import__('asyncio').run(queue.mark_succeeded(pool, job_id))
    assert pool.conn.rows[job_id]['status'] == 'succeeded'


def test_reap_stale_returns_to_queue():
    pool = FakePool()
    job_id = __import__('asyncio').run(queue.enqueue(pool, 'ingest_gdelt', {}, None))
    __import__('asyncio').run(queue.claim_next(pool, 'w1'))
    pool.conn.rows[job_id]['locked_at'] = datetime.now(timezone.utc) - timedelta(minutes=20)
    released = __import__('asyncio').run(queue.release_stale_locks(pool, stale_minutes=15))
    assert released == 1
    assert pool.conn.rows[job_id]['status'] == 'queued'
