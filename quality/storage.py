"""PostgreSQL storage for the legacy reporting SQL, isolated from attendance."""
import os
import re
import sqlite3


def database_url():
    value = os.getenv('QUALITY_DATABASE_URL') or os.getenv('DATABASE_URL', '')
    return value if value.startswith(('postgresql:', 'postgres:', 'postgresql+psycopg2:')) else None


def prepare():
    import psycopg2
    with psycopg2.connect(database_url().replace('postgresql+psycopg2:', 'postgresql:')) as con:
        with con.cursor() as cur:
            cur.execute('CREATE SCHEMA IF NOT EXISTS miell_quality')
    con.close()


class Result:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def __iter__(self):
        return iter(self.cursor)


class Connection:
    def __init__(self):
        import psycopg2
        from psycopg2.extras import DictCursor
        self.con = psycopg2.connect(database_url().replace('postgresql+psycopg2:', 'postgresql:'), cursor_factory=DictCursor)
        with self.con.cursor() as cur:
            cur.execute('SET search_path TO miell_quality')

    def execute(self, sql, args=()):
        import psycopg2
        pragma = re.fullmatch(r'PRAGMA table_info\((\w+)\)', sql.strip(), re.I)
        if pragma:
            sql = 'SELECT column_name AS name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s'
            args = ('miell_quality', pragma[1])
        else:
            # Only replace placeholders outside SQL string literals.
            segments = re.split(r"('(?:''|[^'])*')", sql)
            sql = ''.join(s.replace('%', '%%').replace('?', '%s') if i % 2 == 0 else s.replace('%', '%%') for i, s in enumerate(segments))
            sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
            sql = re.sub(r'\bREAL\b', 'DOUBLE PRECISION', sql)
        returning = bool(re.match(r'\s*INSERT INTO (users|jobs|job_parts|job_errors|records)\s*\(', sql, re.I))
        if returning:
            sql = sql.rstrip().rstrip(';') + ' RETURNING id'
        cur = self.con.cursor()
        try:
            cur.execute(sql, args)
        except psycopg2.IntegrityError as exc:
            self.con.rollback()
            cur.close()
            self.con.close()
            raise sqlite3.IntegrityError('Reporting constraint violation') from exc
        lastrowid = cur.fetchone()[0] if returning else None
        return Result(cur, lastrowid)

    def executescript(self, script):
        for statement in script.split(';'):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self.con.commit()

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        if not self.con.closed:
            try:
                self.con.rollback() if kind else self.con.commit()
            finally:
                self.con.close()
