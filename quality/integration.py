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
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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



def normalize_job_reporting_payload(payload, host):
    """Validate and normalize per-job automatic report settings."""
    enabled = bool(payload.get('reporting_enabled', False))
    recipients = host.normalize_reporting_recipients(payload.get('reporting_recipients', ''))
    report_time = host.validate_time(str(payload.get('reporting_time') or '08:00'), 'Čas reportu') or '08:00'
    raw_formats = payload.get('reporting_formats', 'pdf,xlsm')
    if isinstance(raw_formats, (list, tuple)):
        values = [str(x).strip().lower() for x in raw_formats if str(x).strip()]
    else:
        values = [x.strip().lower() for x in re.split(r'[,;\s]+', str(raw_formats or '')) if x.strip()]
    formats = []
    for value in values:
        if value not in {'pdf', 'xlsx', 'xlsm'}:
            raise HTTPException(400, 'Formát quality reportu môže byť PDF, XLSX alebo XLSM')
        if value not in formats:
            formats.append(value)
    if enabled and not recipients:
        raise HTTPException(400, 'Pri automatickom reportingu zadaj aspoň jedného príjemcu')
    if enabled and not formats:
        raise HTTPException(400, 'Pri automatickom reportingu vyber aspoň jeden formát')
    payload['reporting_enabled'] = enabled
    payload['reporting_recipients'] = recipients
    payload['reporting_time'] = report_time
    payload['reporting_formats'] = ','.join(formats)
    return payload


def _quality_report_period(today: date):
    report_date = today - timedelta(days=1)
    return report_date, f'daily:{report_date.isoformat()}'


def _read_and_cleanup_export(path):
    path = Path(path)
    payload = path.read_bytes()
    parent = path.parent
    path.unlink(missing_ok=True)
    if parent.name.startswith('miell_export_'):
        try:
            parent.rmdir()
        except OSError:
            shutil.rmtree(parent, ignore_errors=True)
    return payload


def _update_job_report_state(job_id, status, error='', period_key=None):
    with _lock, legacy.db() as con:
        if period_key is None:
            con.execute('UPDATE jobs SET reporting_last_sent_at=?,reporting_last_status=?,reporting_last_error=? WHERE id=?',
                        (datetime.utcnow().isoformat(timespec='seconds'), status, str(error or '')[:1500], job_id))
        else:
            con.execute('UPDATE jobs SET reporting_last_sent_at=?,reporting_last_status=?,reporting_last_error=?,reporting_last_period=? WHERE id=?',
                        (datetime.utcnow().isoformat(timespec='seconds'), status, str(error or '')[:1500], period_key, job_id))
        con.commit()


def send_quality_job_report(host, job_id, report_date, *, scheduled=False, period_key=None):
    """Build and send the previous-day quality report for one job."""
    with _lock, legacy.db() as con:
        job = legacy.get_job(con, int(job_id), True)
        if not job:
            raise HTTPException(404, 'Zákazka neexistuje')
        recipients_text = host.normalize_reporting_recipients(job.get('reporting_recipients') or '')
        recipients = [x.strip() for x in recipients_text.split(',') if x.strip()]
        if not recipients:
            raise HTTPException(400, 'Pri zákazke nie sú nastavení príjemcovia reportu')
        formats = [x.strip().lower() for x in str(job.get('reporting_formats') or '').split(',') if x.strip()]
        formats = [x for x in formats if x in {'pdf', 'xlsx', 'xlsm'}]
        if not formats:
            raise HTTPException(400, 'Pri zákazke nie je vybraný formát reportu')
        records = legacy.record_query(
            con,
            {'id': 0, 'role': 'admin'},
            {'job_id': [str(job_id)], 'date': [report_date.isoformat()], 'record_status': ['active']},
        )

    if not records:
        _update_job_report_state(
            int(job_id),
            'skipped',
            'Bez údajov za predchádzajúci deň – report neodoslaný.',
            period_key if scheduled else None,
        )
        return {
            'ok': True,
            'sent': False,
            'skipped': True,
            'reason': 'no_data',
            'job_id': int(job_id),
            'order_number': job['order_number'],
            'date': report_date.isoformat(),
            'recipients': recipients,
            'formats': formats,
            'rows': 0,
        }

    attachments = []
    safe_order = legacy.safe(job.get('order_number') or f'job_{job_id}')
    try:
        if 'pdf' in formats:
            payload = _read_and_cleanup_export(
                legacy.make_pdf(job, records, f'Automatic daily report / {report_date.isoformat()}')
            )
            attachments.append((
                f'Quality_Report_{safe_order}_{report_date.isoformat()}.pdf',
                payload,
                'application',
                'pdf',
            ))
        if 'xlsx' in formats:
            payload = _read_and_cleanup_export(legacy.make_summary_xlsx(job, records))
            attachments.append((
                f'Quality_Report_{safe_order}_{report_date.isoformat()}.xlsx',
                payload,
                'application',
                'vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            ))
        if 'xlsm' in formats:
            payload = _read_and_cleanup_export(legacy.daily_template_export(job, records))
            attachments.append((
                f'Quality_Daily_Report_{safe_order}_{report_date.isoformat()}.xlsm',
                payload,
                'application',
                'vnd.ms-excel.sheet.macroEnabled.12',
            ))

        subject = f"Quality Report – {job['order_number']} – {report_date.isoformat()}"
        content = (
            "Hello,\n\n"
            f"please find attached the quality report for order {job['order_number']} "
            f"for {report_date.isoformat()}.\n\n"
            "This e-mail was sent automatically by the MIELL Quality Reporting system."
        )
        host.microsoft_graph_send_email(subject, content, recipients, attachments)
    except Exception as exc:
        _update_job_report_state(int(job_id), 'error', str(exc), None)
        raise

    _update_job_report_state(int(job_id), 'sent', '', period_key if scheduled else None)
    return {
        'ok': True,
        'sent': True,
        'skipped': False,
        'job_id': int(job_id),
        'order_number': job['order_number'],
        'date': report_date.isoformat(),
        'recipients': recipients,
        'formats': formats,
        'rows': len(records),
    }


def run_due_quality_reports(host, now_local):
    """Run all due per-job quality reports. Called by the shared scheduler endpoint."""
    report_date, period_key = _quality_report_period(now_local.date())
    with _lock, legacy.db() as con:
        jobs = [dict(r) for r in con.execute(
            'SELECT id,order_number,reporting_time,reporting_last_period FROM jobs WHERE active=1 AND COALESCE(reporting_enabled,0)=1 ORDER BY id'
        ).fetchall()]

    sent, skipped, errors = [], [], []
    for job in jobs:
        try:
            hh, mm = map(int, str(job.get('reporting_time') or '08:00').split(':'))
        except Exception:
            errors.append({'job_id': job['id'], 'order_number': job['order_number'], 'error': 'Neplatný čas reportingu'})
            continue
        if (now_local.hour, now_local.minute) < (hh, mm):
            continue
        if job.get('reporting_last_period') == period_key:
            continue
        try:
            result = send_quality_job_report(
                host,
                int(job['id']),
                report_date,
                scheduled=True,
                period_key=period_key,
            )
            (skipped if result.get('skipped') else sent).append(result)
        except Exception as exc:
            errors.append({'job_id': job['id'], 'order_number': job['order_number'], 'error': str(exc)})
    return {'sent': sent, 'skipped': skipped, 'errors': errors}


def register(host):
    app = host.app

    @app.get('/quality/')
    def quality_page():
        return FileResponse(Path(legacy.STATIC_DIR) / 'index.html')

    @app.get('/quality/{asset}')
    def quality_asset(asset: str):
        if asset not in {'app.css', 'app.js', 'logo.png', 'shell.css', 'scanner.js'}:
            raise HTTPException(404)
        return FileResponse(Path(legacy.STATIC_DIR) / asset)

    @app.api_route('/quality/api/{endpoint:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def quality_api(endpoint: str, request: Request, user=Depends(host.get_current_user), session=Depends(host.db)):
        analytics_match = re.fullmatch(r'jobs/(\d+)/analytics', endpoint)
        analytics_export = endpoint in {'export/pdf', 'export/xlsx'} and request.query_params.get('analytics') == '1'
        if request.method == 'GET' and (analytics_match or analytics_export):
            from . import analytics
            try:
                jid = int(analytics_match.group(1) if analytics_match else request.query_params.get('job_id', '0'))
                part_id = int(request.query_params['part_id']) if request.query_params.get('part_id') else None
            except ValueError:
                raise HTTPException(400, 'Neplatná zákazka alebo diel')
            identity = sync_identity(user)
            today = datetime.now(ZoneInfo(host.REPORTING_TIMEZONE)).date()
            def prepare():
                con = legacy.db()
                try:
                    job = legacy.get_job(con, jid, True)
                    if not job: raise HTTPException(404, 'Zákazka neexistuje')
                    records = legacy.record_query(con, identity, {'job_id':[str(jid)], 'date_to':[today.isoformat()], 'record_status':['active']})
                finally:
                    con.close()
                return job, records
            job, records = await run_in_threadpool(prepare)
            if user.role != 'admin' and job.get('location_id') not in host.assigned_location_ids(user) and not records:
                raise HTTPException(403, 'K zákazke nemáš prístup')
            location = session.get(host.Location, job['location_id']) if job.get('location_id') else None
            scope = 'Celá zákazka / administrátor' if user.role == 'admin' else 'Iba moje záznamy / '+user.name
            try:
                data = await run_in_threadpool(analytics.build, job, records, today, scope, location.name if location else '', part_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            if analytics_export:
                pdf = endpoint == 'export/pdf'
                content = await run_in_threadpool(analytics.export_pdf if pdf else analytics.export_xlsx, data)
                ext = 'pdf' if pdf else 'xlsx'
                return Response(content, media_type='application/pdf' if pdf else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition':f'attachment; filename="MIELL_Analytics_{jid}_{today}.{ext}"'})
            data['charts'] = await run_in_threadpool(analytics.svg_charts, data)
            return data
        if endpoint == 'me' and request.method == 'GET':
            return {'user': sync_identity(user)}
        if endpoint == 'locations' and request.method == 'GET':
            return {'locations': host.locations(session=session, user=user)}
        if endpoint == 'jobs' and request.method == 'GET' and user.role != 'admin':
            allowed_locations = set(host.assigned_location_ids(user))
            with legacy.db() as con:
                jobs = legacy.list_jobs(con, include_inactive=False)
            return {'jobs': [job for job in jobs
                             if job.get('location_id') and job['location_id'] in allowed_locations]}
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
        report_match = re.fullmatch(r'jobs/(\d+)/report/send-now', endpoint)
        if report_match and request.method == 'POST':
            if user.role != 'admin':
                raise HTTPException(403, 'Len pre administrátora')
            report_date, _ = _quality_report_period(datetime.now(ZoneInfo(host.REPORTING_TIMEZONE)).date())
            return await run_in_threadpool(send_quality_job_report, host, int(report_match.group(1)), report_date)
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
            normalize_job_reporting_payload(payload, host)
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
            elif user.role!='admin' and (not job or not job.get('location_id') or job['location_id'] not in host.assigned_location_ids(user)):
                raise HTTPException(403, 'Prevádzka zákazky ti nie je priradená')
            payload['_record_user_id']=sync_identity(target)['id']
        path = '/api/' + endpoint + ('?' + request.url.query if request.url.query else '')
        try:
            return await run_in_threadpool(ResponseAdapter(request.method, path, payload, identity).run)
        except (ValueError, TypeError, sqlite3.IntegrityError):
            raise HTTPException(400, 'Neplatné hodnoty alebo konflikt záznamov')
