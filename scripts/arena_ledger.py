"""SQLite journal and conservative reservations for concurrent external jobs."""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path
from scripts.arena_config import canonical, digest


class BudgetExceeded(RuntimeError):
    pass


class AmbiguousAttempt(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, config TEXT NOT NULL,
              max_tokens INTEGER NOT NULL, max_ms INTEGER NOT NULL, used_tokens INTEGER NOT NULL DEFAULT 0,
              elapsed_ms INTEGER NOT NULL DEFAULT 0, state TEXT, status TEXT NOT NULL DEFAULT 'ready');
            CREATE TABLE IF NOT EXISTS jobs(run TEXT NOT NULL, id TEXT NOT NULL, status TEXT NOT NULL,
              reservation INTEGER NOT NULL, result TEXT, result_hash TEXT, tokens INTEGER, elapsed_ms INTEGER,
              reason TEXT, started REAL NOT NULL, PRIMARY KEY(run,id));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              run TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, timestamp REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS charges(run TEXT NOT NULL, job TEXT NOT NULL, owner TEXT NOT NULL,
              PRIMARY KEY(run,job));
            CREATE TABLE IF NOT EXISTS identities(run TEXT PRIMARY KEY, content TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checks(run TEXT NOT NULL, job TEXT NOT NULL, result TEXT NOT NULL,
              elapsed_ms INTEGER NOT NULL, PRIMARY KEY(run,job));
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'identity_hash' not in {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN identity_hash TEXT')

    @contextlib.contextmanager
    def campaign_lock(self, run: str):
        """Exclusive nonblocking OS lock; automatically released after a crash.

        Acquire before interrupted-job recovery and retain through the entire
        campaign invocation. Lock files are stable and must never be unlinked.
        """
        path = self.path.parent / ('campaign-' + digest(run) + '.lock')
        with path.open('a+b') as stream:
            if not stream.seek(0, 2):
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(f'Campaign {run} is already active in another invocation') from exc
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @contextlib.contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _event(db, run, kind, payload):
        db.execute('INSERT INTO events(run,kind,payload,timestamp) VALUES(?,?,?,?)',
                   (run,kind,canonical(payload).decode(),time.time()))

    def start_run(self, run: str, config: dict, max_tokens: int, max_ms: int):
        if max_tokens <= 0 or max_ms <= 0:
            raise ValueError('Positive token and elapsed-time budgets are required')
        with self._db() as db:
            db.execute('INSERT INTO runs(id,config,max_tokens,max_ms) VALUES(?,?,?,?)',
                       (run,canonical(config).decode(),max_tokens,max_ms))
            self._event(db,run,'run.created',{'config_hash':digest(config)})

    def budget(self, run: str) -> dict:
        with self._db() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?',(run,)).fetchone()
            if row is None:
                raise ValueError(f'Unknown run: {run}')
            pending = db.execute("SELECT COALESCE(SUM(reservation),0) FROM jobs WHERE run=? AND status IN ('running','ambiguous')",(run,)).fetchone()[0]
            return {'max_tokens':row['max_tokens'],'max_ms':row['max_ms'],
                    'used_tokens':row['used_tokens'],'reserved_tokens':pending,
                    'elapsed_ms':row['elapsed_ms'],'status':row['status']}

    def reserve(self, run: str, job: str, tokens: int, *, identity_hash: str | None = None):
        if tokens <= 0:
            raise ValueError('Reservation must be positive')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT status,identity_hash FROM jobs WHERE run=? AND id=?',(run,job)).fetchone()
            if old:
                if identity_hash is not None and old['identity_hash'] != identity_hash:
                    raise ValueError(f'{job}: frozen job identity differs from requested prompt/model/schema/role')
                if old['status'] == 'complete':
                    return False
                if old['status'] != 'not_started':
                    raise AmbiguousAttempt(f'{job}: existing {old["status"]} attempt requires reconciliation')
            row = db.execute('SELECT * FROM runs WHERE id=?',(run,)).fetchone()
            if row is None:
                raise ValueError(f'Unknown run: {run}')
            reserved = db.execute("SELECT COALESCE(SUM(reservation),0) FROM jobs WHERE run=? AND status IN ('running','ambiguous')",(run,)).fetchone()[0]
            if row['used_tokens'] + reserved + tokens > row['max_tokens'] or row['elapsed_ms'] >= row['max_ms']:
                raise BudgetExceeded('Insufficient remaining token/time budget; resume with larger explicit limits')
            if old:
                db.execute("UPDATE jobs SET status='running',reservation=?,started=?,reason=NULL WHERE run=? AND id=?",
                           (tokens,time.time(),run,job))
            else:
                db.execute('INSERT INTO jobs(run,id,status,reservation,started,identity_hash) VALUES(?,?,?,?,?,?)',
                           (run,job,'running',tokens,time.time(),identity_hash))
            self._event(db,run,'job.dispatched',{'job':job,'reservation':tokens})
        return True

    def pre_dispatch_failed(self, run: str, job: str, reason: str):
        """Release only an attempt explicitly proven not to have spawned a child."""
        with self._db() as db:
            old = db.execute('SELECT status FROM jobs WHERE run=? AND id=?',(run,job)).fetchone()
            if old is None or old['status'] != 'running':
                raise ValueError('Only a reserved running attempt can be marked not_started')
            db.execute("UPDATE jobs SET status='not_started',reason=? WHERE run=? AND id=?",(reason,run,job))
            self._event(db,run,'job.not_started',{'job':job,'reason':reason})

    def finish(self, run: str, job: str, result: dict, tokens: int | None, elapsed_ms: int):
        if tokens is None:
            self.mark_ambiguous(run,job,'Usage counters missing; result requires reconciliation')
            raise AmbiguousAttempt('Cannot settle unknown token usage')
        if tokens < 0 or elapsed_ms < 0:
            raise ValueError('Negative usage')
        content_hash = digest(result)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM jobs WHERE run=? AND id=?',(run,job)).fetchone()
            if old is None:
                raise ValueError('Job has no reservation')
            if old['status'] == 'complete':
                if old['result_hash'] != content_hash or old['tokens'] != tokens:
                    raise ValueError('Conflicting duplicate job receipt')
                return
            db.execute('UPDATE jobs SET status=?,result=?,result_hash=?,tokens=?,elapsed_ms=? WHERE run=? AND id=?',
                       ('complete',canonical(result).decode(),content_hash,tokens,elapsed_ms,run,job))
            db.execute('UPDATE runs SET used_tokens=used_tokens+? WHERE id=?',(tokens,run))
            self._event(db,run,'job.completed',{'job':job,'hash':content_hash,'tokens':tokens})

    def mark_ambiguous(self, run: str, job: str, reason: str):
        with self._db() as db:
            db.execute("UPDATE jobs SET status='ambiguous',reason=? WHERE run=? AND id=? AND status!='complete'",(reason,run,job))
            db.execute("UPDATE runs SET status='needs_reconciliation' WHERE id=?",(run,))
            self._event(db,run,'job.ambiguous',{'job':job,'reason':reason})

    def recover_interrupted(self, run: str) -> list[str]:
        with self._db() as db:
            rows = db.execute("SELECT id FROM jobs WHERE run=? AND status='running'",(run,)).fetchall()
        for row in rows:
            self.mark_ambiguous(run,row['id'],'Supervisor interrupted while external execution might have completed')
        return [r['id'] for r in rows]

    def completed(self, run: str, job: str, *, identity_hash: str | None = None):
        with self._db() as db:
            row = db.execute("SELECT result,identity_hash FROM jobs WHERE run=? AND id=? AND status='complete'",(run,job)).fetchone()
            if row is not None and identity_hash is not None and row['identity_hash'] != identity_hash:
                raise ValueError(f'{job}: frozen job identity differs from requested prompt/model/schema/role')
            return json.loads(row['result']) if row else None

    def checkpoint(self, run: str, state: dict, status: str | None = None):
        with self._db() as db:
            db.execute('UPDATE runs SET state=? WHERE id=?',(canonical(state).decode(),run))
            if status:
                db.execute('UPDATE runs SET status=? WHERE id=?',(status,run))

    def load_state(self, run: str):
        with self._db() as db:
            row = db.execute('SELECT state FROM runs WHERE id=?',(run,)).fetchone()
            if not row:
                raise ValueError(f'Unknown run: {run}')
            return json.loads(row['state']) if row['state'] else None

    def add_elapsed(self, run: str, milliseconds: int):
        with self._db() as db:
            db.execute('UPDATE runs SET elapsed_ms=elapsed_ms+? WHERE id=?',(max(0,milliseconds),run))

    def extend(self, run: str, max_tokens: int, max_ms: int):
        current = self.budget(run)
        if max_tokens < current['max_tokens'] or max_ms < current['max_ms']:
            raise ValueError('Resume budgets are cumulative ceilings and cannot decrease')
        with self._db() as db:
            db.execute('UPDATE runs SET max_tokens=?,max_ms=? WHERE id=?',(max_tokens,max_ms,run))
            self._event(db,run,'budget.extended',{'max_tokens':max_tokens,'max_ms':max_ms})

    def list_jobs(self, run: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute('SELECT id,status,tokens,elapsed_ms,reason,reservation,identity_hash FROM jobs WHERE run=? ORDER BY started',(run,)).fetchall()
            return [dict(r) for r in rows]

    def freeze_identity(self, run: str, identity: dict):
        content = canonical(identity).decode()
        with self._db() as db:
            db.execute('INSERT OR IGNORE INTO identities(run,content) VALUES(?,?)',(run,content))
            if db.execute('SELECT content FROM identities WHERE run=?',(run,)).fetchone()[0] != content:
                raise ValueError('Frozen campaign identity differs from its journal')

    def frozen_identity(self, run: str):
        with self._db() as db:
            row = db.execute('SELECT content FROM identities WHERE run=?',(run,)).fetchone()
            return json.loads(row[0]) if row else None

    def record_check(self, run: str, job: str, result: dict, elapsed_ms: int):
        with self._db() as db:
            db.execute('INSERT OR IGNORE INTO checks(run,job,result,elapsed_ms) VALUES(?,?,?,?)',
                       (run,job,canonical(result).decode(),elapsed_ms))

    def check_result(self, run: str, job: str):
        with self._db() as db:
            row = db.execute('SELECT result,elapsed_ms FROM checks WHERE run=? AND job=?',(run,job)).fetchone()
            return {'result':json.loads(row['result']),'elapsed_ms':row['elapsed_ms']} if row else None

    def check_summary(self, run: str):
        with self._db() as db:
            row = db.execute('SELECT COUNT(*) AS checks,COALESCE(SUM(elapsed_ms),0) AS execution_ms FROM checks WHERE run=?',(run,)).fetchone()
            return dict(row)

    def record_event(self, run: str, kind: str, payload: dict):
        with self._db() as db:
            self._event(db,run,kind,payload)

    def charge_once(self, run: str, job: str, owner: str) -> bool:
        """Attach reusable drafting cost to exactly one episode, stable across replay."""
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO charges(run,job,owner) VALUES(?,?,?)',(run,job,owner))
            return db.execute('SELECT owner FROM charges WHERE run=? AND job=?',(run,job)).fetchone()[0] == owner

    def usage_summary(self, run: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute('''SELECT COALESCE(json_extract(result,'$.role'),'unknown') AS role,
                COUNT(*) AS calls, SUM(tokens) AS tokens,
                SUM(COALESCE(json_extract(result,'$.execution_ms'),elapsed_ms)) AS execution_ms,
                SUM(COALESCE(json_extract(result,'$.wait_ms'),0)) AS wait_ms,
                SUM(json_extract(result,'$.cost_usd')) AS estimated_usd
                FROM jobs WHERE run=? AND status='complete' GROUP BY role''',(run,)).fetchall()
            return [dict(row) for row in rows]
