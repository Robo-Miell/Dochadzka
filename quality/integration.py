"""Run the V2.4 business handlers inside FastAPI, with central identity only.

No secondary HTTP server or legacy login endpoint is exposed. The small response
adapter lets us retain the tested reporting rules and XLSM template logic.
"""
import io
import json
import os
import re
import sqlite3
import shutil
import threading
from datetime import datetime
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select

from . import legacy
from .exports import install_exports

_lock = threading.RLock()


def configure(data_dir):
    from .storage import database_url, prepare
    if database_url():
        prepare()
    legacy.DATA_DIR = str(data_dir)
    legacy.DB_PATH = str(Path(data_dir) / 'reporting.db')
    legacy.TEMPLATE_PATH = str(Path(data_dir) / 'report_template.xlsm')
    bundled_template = Path(__file__).parent / 'templates' / 'report_template.xlsm'
    if not Path(legacy.TEMPLATE_PATH).exists() and bundled_template.exists():
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_template, legacy.TEMPLATE_PATH)
    legacy.init_db()
    with legacy.db() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS unified_identity (
            central_id INTEGER PRIMARY KEY, quality_id INTEGER UNIQUE NOT NULL,
            FOREIGN KEY(quality_id) REFERENCES users(id))''')
        con.execute('CREATE TABLE IF NOT EXISTS unified_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        if 'central_login' not in legacy.table_columns(con, 'users'):
            con.execute('ALTER TABLE users ADD COLUMN central_login TEXT')
        if 'location_id' not in legacy.table_columns(con, 'jobs'):
            con.execute('ALTER TABLE jobs ADD COLUMN location_id INTEGER')
    install_exports(legacy)


def sync_identity(user):
    """Map by immutable central ID, never by matching login or display name."""
    with _lock, legacy.db() as con:
        row = con.execute('SELECT quality_id FROM unified_identity WHERE central_id=?', (user.id,)).fetchone()
        role = 'admin' if user.role == 'admin' else 'operator'
        if row:
            qid = row[0]
            con.execute('UPDATE users SET display_name=?,role=?,active=?,central_login=? WHERE id=?',
                        (user.name, role, int(user.active), user.login, qid))
        else:
            # This shadow identity has no usable password. Authentication is central.
            cur = con.execute('''INSERT INTO users(username,display_name,role,password_salt,password_hash,active,created_at)
                VALUES(?,?,?,?,?,?,?)''', (f'central:{user.id}', user.name, role, '', '', int(user.active), datetime.now().isoformat()))
            qid = cur.lastrowid
            con.execute('UPDATE users SET central_login=? WHERE id=?',(user.login,qid))
            con.execute('INSERT INTO unified_identity VALUES(?,?)', (user.id, qid))
        return dict(id=qid, username=user.login, display_name=user.name, role=role)


def has_records(central_id):
    with legacy.db() as con:
        return bool(con.execute('''SELECT 1 FROM records r JOIN unified_identity i
            ON i.quality_id=r.user_id WHERE i.central_id=? LIMIT 1''', (central_id,)).fetchone())


def import_initial_users(host):
    """Bootstrap an empty central DB only. Existing account collisions are explicit.

    A unique source marker in personal_number makes a retry safe if the process
    exits between commits to the two stores. Existing attendance installations
    use the separate migration command instead of an implicit name-based merge.
    """
    with host.SessionLocal() as session, legacy.db() as con:
        if con.execute("SELECT 1 FROM unified_metadata WHERE key='users_import_complete'").fetchone():
            return
        existing = session.scalars(select(host.User)).all()
        if existing and any(not u.personal_number.startswith('REPORTING-') for u in existing):
            if con.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                raise RuntimeError('Existujúce účty dochádzky: najprv spusti migrate_users.py s explicitným mapovaním účtov. Pozri README_UNIFIED.md.')
            con.execute("INSERT INTO unified_metadata VALUES('users_import_complete','1')")
            return
        rows = con.execute('SELECT * FROM users ORDER BY id').fetchall()
        for r in rows:
            marker = f"REPORTING-{r['id']}"
            u = session.scalar(select(host.User).where(host.User.personal_number == marker))
            if not u:
                u = host.User(personal_number=marker, name=r['display_name'], login=r['username'],
                    password_hash=f"miell_pbkdf2${r['password_salt']}${r['password_hash']}",
                    role='admin' if r['role'] == 'admin' else 'employee', active=bool(r['active']))
                session.add(u)
                session.commit()
            con.execute('INSERT INTO unified_identity VALUES(?,?) ON CONFLICT DO NOTHING', (u.id, r['id']))
        con.execute("INSERT INTO unified_metadata VALUES('users_import_complete','1') ON CONFLICT(key) DO UPDATE SET value=excluded.value")


class ResponseAdapter(legacy.Handler):
    def __init__(self, method, path, payload, user):
        self.command, self.path, self.payload, self.user = method, path, payload, user
        self.wfile = io.BytesIO()
        self.status = 200
        self.output_headers = {}

    def _body(self):
        return self.payload

    def _session(self):
        return self.user

    def send_response(self, status, message=None):
        self.status = status

    def send_header(self, name, value):
        self.output_headers[name] = str(value)

    def end_headers(self):
        pass

    def send_error(self, code, message=None):
        self._json({'error': message or 'Požiadavka zlyhala.'}, code)

    def _file(self, path, ctype=None, download=None):
        try:
            return super()._file(path, ctype, download)
        finally:
            # Every generated export now has its own directory.
            parent = Path(path).parent
            if parent.name.startswith('miell_export_'):
                Path(path).unlink(missing_ok=True)
                parent.rmdir()

    def run(self):
        getattr(self, 'do_' + self.command)()
        self.output_headers.pop('Content-Length', None)
        return Response(self.wfile.getvalue(), self.status, headers=self.output_headers)


def register(host):
    app = host.app

    @app.get('/quality/')
    def quality_page():
        return FileResponse(Path(legacy.STATIC_DIR) / 'index.html')

    @app.get('/quality/{asset}')
    def quality_asset(asset: str):
        if asset not in {'app.css', 'app.js', 'logo.png', 'shell.css'}:
            raise HTTPException(404)
        return FileResponse(Path(legacy.STATIC_DIR) / asset)

    @app.api_route('/quality/api/{endpoint:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def quality_api(endpoint: str, request: Request, user=Depends(host.get_current_user), session=Depends(host.db)):
        if endpoint == 'me' and request.method == 'GET':
            return {'user': sync_identity(user)}
        if endpoint == 'locations' and request.method == 'GET':
            return {'locations': host.locations(session=session, user=user)}
        if endpoint == 'employees' and request.method == 'GET':
            if user.role != 'admin':
                raise HTTPException(403, 'Len pre administrátora')
            try:
                location_id = int(request.query_params.get('location_id', '0'))
            except ValueError:
                raise HTTPException(400, 'Neplatná prevádzka')
            employees = session.scalars(select(host.User).where(host.User.role=='employee', host.User.active==True)).all()
            return {'employees': [{'id':u.id,'name':u.name,'personal_number':u.personal_number} for u in employees if location_id in host.assigned_location_ids(u)]}
        if endpoint == 'users' and request.method == 'GET':
            if user.role != 'admin':
                raise HTTPException(403, 'Len pre administrátora')
            # Include unmapped historic identities so old records remain filterable.
            all_users = session.scalars(select(host.User)).all()
            for u in all_users:
                sync_identity(u)
            with legacy.db() as con:
                return {'users': [dict(r) for r in con.execute('SELECT id,COALESCE(central_login,username) AS username,display_name,role,active FROM users ORDER BY display_name')]}
        # Keep authentication and user management out of the legacy handler.
        if not re.fullmatch(r'(dashboard|jobs(?:/\d+(?:/(?:summary|archive|restore))?)?|records(?:/\d+(?:/(?:archive|restore))?)?|export/(?:records-xlsx|records-pdf|daily-xlsm|xlsx|pdf))', endpoint):
            raise HTTPException(404, 'Endpoint neexistuje')
        payload = {}
        if request.method in {'POST', 'PUT'}:
            try:
                payload = await request.json()
            except Exception:
                raise HTTPException(400, 'Neplatný JSON')
            if not isinstance(payload, dict):
                raise HTTPException(400, 'Očakáva sa objekt')
        identity = sync_identity(user)
        if request.method in {'POST','PUT'} and re.fullmatch(r'jobs(?:/\d+)?',endpoint):
            if user.role != 'admin':
                raise HTTPException(403, 'Len pre administrátora')
            try:
                lid = int(payload.get('location_id') or 0)
            except (ValueError,TypeError):
                raise HTTPException(400, 'Vyber platnú prevádzku')
            if not lid or session.get(host.Location,lid) is None:
                raise HTTPException(400, 'Vyber prevádzku vytvorenú v Dochádzke')
            payload['location_id']=lid
        if endpoint == 'records' and request.method == 'POST':
            try:
                target_id=int(payload.get('employee_id') or user.id)
                jid=int(payload.get('job_id') or 0)
            except (ValueError,TypeError):
                raise HTTPException(400, 'Neplatný zamestnanec alebo zákazka')
            if user.role!='admin' and target_id!=user.id:
                raise HTTPException(403, 'Záznam môžeš zadávať iba za seba')
            target=session.get(host.User,target_id)
            if not target or not target.active:
                raise HTTPException(400, 'Zamestnanec nie je aktívny')
            with legacy.db() as con:
                job=legacy.get_job(con,jid,True)
            if target_id!=user.id:
                if target.role!='employee' or not job or not job.get('location_id') or job['location_id'] not in host.assigned_location_ids(target):
                    raise HTTPException(400, 'Vybraný zamestnanec nemá priradenú prevádzku zákazky')
            elif user.role!='admin' and job and job.get('location_id') and job['location_id'] not in host.assigned_location_ids(user):
                raise HTTPException(403, 'Prevádzka zákazky ti nie je priradená')
            payload['_record_user_id']=sync_identity(target)['id']
        path = '/api/' + endpoint + ('?' + request.url.query if request.url.query else '')
        try:
            return await run_in_threadpool(ResponseAdapter(request.method, path, payload, identity).run)
        except (ValueError, TypeError, sqlite3.IntegrityError):
            raise HTTPException(400, 'Neplatné hodnoty alebo konflikt záznamov')
