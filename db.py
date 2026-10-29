import os
import sqlite3
from datetime import datetime, date
from contextlib import contextmanager

class Database:
    def __init__(self):
        self.mode = os.getenv('DB_MODE', 'sqlserver')
        self.path = os.getenv('SQLITE_PATH', 'demo.db')
        self.connection = os.getenv('SQL_CONNECTION_STRING', '')

    @contextmanager
    def transaction(self):
        if self.mode == 'sqlite':
            conn = sqlite3.connect(self.path, timeout=30)
            conn.execute('PRAGMA foreign_keys=ON')
        else:
            import pyodbc
            if not self.connection:
                raise RuntimeError('SQL_CONNECTION_STRING is required')
            conn = pyodbc.connect(self.connection, autocommit=False, timeout=10)
        try:
            yield Session(conn, self.mode)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_demo(self):
        if self.mode != 'sqlite':
            raise RuntimeError('Use schema.sql in SSMS for SQL Server')
        from pathlib import Path
        with sqlite3.connect(self.path) as conn:
            conn.executescript(Path(__file__).with_name('schema_demo.sql').read_text())

class Session:
    def __init__(self, conn, mode):
        self.conn, self.mode = conn, mode

    def execute(self, sql, params=()):
        if self.mode == 'sqlite':
            params = tuple(p.isoformat(sep=' ') if isinstance(p, datetime) else p.isoformat() if isinstance(p, date) else p for p in params)
        return self.conn.cursor().execute(sql, params)

    def rows(self, sql, params=()):
        c = self.execute(sql, params)
        names = [x[0] for x in c.description]
        return [dict(zip(names, row)) for row in c.fetchall()]

    def one(self, sql, params=()):
        rows = self.rows(sql, params)
        return rows[0] if rows else None

    def insert(self, sql, params=()):
        if self.mode == 'sqlite':
            return self.execute(sql, params).lastrowid
        before, after = sql.split(' VALUES', 1)
        return int(self.execute(before + ' OUTPUT INSERTED.Id VALUES' + after, params).fetchone()[0])
