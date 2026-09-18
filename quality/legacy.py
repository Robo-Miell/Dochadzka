import os, sys, json, sqlite3, hashlib, hmac, secrets, re, mimetypes, urllib.parse, tempfile, zipfile, shutil, subprocess, socket, webbrowser, base64, html, copy
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from datetime import datetime, date as _Date
from zoneinfo import ZoneInfo
# Preserve namespace declarations referenced by Excel's mc:Ignorable attributes.
# ElementTree drops unused declarations and rewrites prefixes, corrupting XLSM.
from lxml import etree as ET

class date(_Date):
    @classmethod
    def today(cls):
        return datetime.now(ZoneInfo(os.getenv('REPORTING_TIMEZONE', 'Europe/Bratislava'))).date()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'reporting.db')
TEMPLATE_PATH = os.path.join(DATA_DIR, 'report_template.xlsm')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
LOGO_PATH = os.path.join(STATIC_DIR, 'logo.png')
HOST = '127.0.0.1'
DEFAULT_PORT = 8788
SESSIONS = {}
NS_MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def db():
    from .storage import database_url, Connection
    if database_url():
        return Connection()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    if isinstance(salt, str):
        salt = bytes.fromhex(salt)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return salt.hex(), digest.hex()


def verify_password(password, salt_hex, digest_hex):
    _, calc = hash_password(password, salt_hex)
    return hmac.compare_digest(calc, digest_hex)


def table_columns(con, name):
    return {r['name'] for r in con.execute(f'PRAGMA table_info({name})')}


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = db()
    con.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','operator')),
        password_salt TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        brief_description TEXT NOT NULL,
        norm_enabled INTEGER NOT NULL DEFAULT 1,
        norm_time TEXT,
        norm_mode TEXT NOT NULL DEFAULT 'ct',
        norm_ct_seconds REAL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        reporting_enabled INTEGER NOT NULL DEFAULT 0,
        reporting_recipients TEXT NOT NULL DEFAULT '',
        reporting_time TEXT NOT NULL DEFAULT '08:00',
        reporting_formats TEXT NOT NULL DEFAULT 'pdf,xlsm',
        reporting_last_sent_at TEXT,
        reporting_last_status TEXT NOT NULL DEFAULT '',
        reporting_last_error TEXT NOT NULL DEFAULT '',
        reporting_last_period TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS job_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        item_number TEXT NOT NULL,
        part_name TEXT,
        norm_per_hour REAL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS job_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        part_id INTEGER,
        user_id INTEGER NOT NULL,
        record_date TEXT NOT NULL,
        delivery_note TEXT,
        checked_items INTEGER NOT NULL,
        ok_items INTEGER NOT NULL,
        nok_items INTEGER NOT NULL,
        reworked_ok INTEGER NOT NULL DEFAULT 0,
        reworked_nok INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        job_snapshot TEXT NOT NULL,
        part_snapshot TEXT,
        error_counts TEXT NOT NULL DEFAULT '{}',
        shift TEXT NOT NULL DEFAULT 'R',
        work_time_seconds INTEGER NOT NULL DEFAULT 0,
        norm_seconds_per_item REAL,
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id),
        FOREIGN KEY(part_id) REFERENCES job_parts(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    ''')
    # Lightweight migration from V1 if an old reporting.db is copied into V2.
    jcols = table_columns(con, 'jobs')
    if 'norm_enabled' not in jcols:
        con.execute('ALTER TABLE jobs ADD COLUMN norm_enabled INTEGER NOT NULL DEFAULT 0')
    if 'norm_time' not in jcols:
        con.execute('ALTER TABLE jobs ADD COLUMN norm_time TEXT')
    if 'norm_mode' not in jcols:
        con.execute("ALTER TABLE jobs ADD COLUMN norm_mode TEXT NOT NULL DEFAULT 'ct'")
    if 'norm_ct_seconds' not in jcols:
        con.execute('ALTER TABLE jobs ADD COLUMN norm_ct_seconds REAL')
    for col, ddl in [
        ('reporting_enabled', 'ALTER TABLE jobs ADD COLUMN reporting_enabled INTEGER NOT NULL DEFAULT 0'),
        ('reporting_recipients', "ALTER TABLE jobs ADD COLUMN reporting_recipients TEXT NOT NULL DEFAULT ''"),
        ('reporting_time', "ALTER TABLE jobs ADD COLUMN reporting_time TEXT NOT NULL DEFAULT '08:00'"),
        ('reporting_formats', "ALTER TABLE jobs ADD COLUMN reporting_formats TEXT NOT NULL DEFAULT 'pdf,xlsm'"),
        ('reporting_last_sent_at', 'ALTER TABLE jobs ADD COLUMN reporting_last_sent_at TEXT'),
        ('reporting_last_status', "ALTER TABLE jobs ADD COLUMN reporting_last_status TEXT NOT NULL DEFAULT ''"),
        ('reporting_last_error', "ALTER TABLE jobs ADD COLUMN reporting_last_error TEXT NOT NULL DEFAULT ''"),
        ('reporting_last_period', "ALTER TABLE jobs ADD COLUMN reporting_last_period TEXT NOT NULL DEFAULT ''"),
    ]:
        if col not in jcols:
            con.execute(ddl)
    # V2.3: OFF is no longer a selectable norm mode. Legacy OFF jobs become operator-time jobs.
    con.execute("UPDATE jobs SET norm_mode='time', norm_enabled=1 WHERE norm_mode IS NULL OR norm_mode='' OR norm_mode='off'")
    rcols = table_columns(con, 'records')
    for col, ddl in [
        ('part_id', 'ALTER TABLE records ADD COLUMN part_id INTEGER'),
        ('part_snapshot', 'ALTER TABLE records ADD COLUMN part_snapshot TEXT'),
        ('error_counts', "ALTER TABLE records ADD COLUMN error_counts TEXT NOT NULL DEFAULT '{}'"),
        ('shift', "ALTER TABLE records ADD COLUMN shift TEXT NOT NULL DEFAULT 'R'"),
        ('work_time_seconds', 'ALTER TABLE records ADD COLUMN work_time_seconds INTEGER NOT NULL DEFAULT 0'),
        ('norm_seconds_per_item', 'ALTER TABLE records ADD COLUMN norm_seconds_per_item REAL'),
    ]:
        if col not in rcols:
            con.execute(ddl)
    pcols = table_columns(con, 'job_parts')
    if 'norm_per_hour' not in pcols:
        con.execute('ALTER TABLE job_parts ADD COLUMN norm_per_hour REAL')
    rcols = table_columns(con, 'records')
    if 'archived' not in rcols:
        con.execute('ALTER TABLE records ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')

    now = datetime.now().isoformat(timespec='seconds')
    # Migrate V1 job parts/errors if old columns exist.
    jcols = table_columns(con, 'jobs')
    if 'item_number' in jcols:
        for j in con.execute('SELECT * FROM jobs').fetchall():
            if not con.execute('SELECT 1 FROM job_parts WHERE job_id=?', (j['id'],)).fetchone() and (j['item_number'] or j['part_name']):
                con.execute('INSERT INTO job_parts(job_id,item_number,part_name,norm_per_hour,sort_order,active) VALUES(?,?,?,?,?,1)',
                            (j['id'], j['item_number'] or '', j['part_name'] or '', None, 0))
            if not con.execute('SELECT 1 FROM job_errors WHERE job_id=?', (j['id'],)).fetchone():
                for idx, col in enumerate(['error1','error2','error3','error4']):
                    if col in jcols and j[col]:
                        con.execute('INSERT INTO job_errors(job_id,name,sort_order,active) VALUES(?,?,?,1)', (j['id'], j[col], idx))
            if 'norm' in jcols and j['norm'] and not j['norm_time']:
                # V1 free-text norm cannot reliably become a time. Leave norm disabled.
                con.execute('UPDATE jobs SET norm_enabled=0 WHERE id=?', (j['id'],))
    con.commit(); con.close()


def dictrow(r):
    return {k: r[k] for k in r.keys()}


def get_job(con, job_id, include_inactive=True):
    where = 'id=?' if include_inactive else 'id=? AND active=1'
    r = con.execute(f'SELECT * FROM jobs WHERE {where}', (job_id,)).fetchone()
    if not r: return None
    j = dictrow(r)
    j['parts'] = [dictrow(x) for x in con.execute('SELECT * FROM job_parts WHERE job_id=? AND active=1 ORDER BY sort_order,id', (job_id,)).fetchall()]
    j['errors'] = [dictrow(x) for x in con.execute('SELECT * FROM job_errors WHERE job_id=? AND active=1 ORDER BY sort_order,id', (job_id,)).fetchall()]
    return j


def list_jobs(con, include_inactive=False):
    rs = con.execute('SELECT * FROM jobs ' + ('' if include_inactive else 'WHERE active=1 ') + 'ORDER BY active DESC, order_number').fetchall()
    return [get_job(con, r['id'], True) for r in rs]


def require_int(data, key, default=0):
    try: v = int(data.get(key, default))
    except Exception: raise ValueError(f'{key} musí byť celé číslo.')
    if v < 0: raise ValueError(f'{key} nemôže byť záporné.')
    return v


def validate_time_text(value):
    if not value: return ''
    # Working time is a duration, not a clock time. Accept H:MM as well as HH:MM
    # (for example 0:05, 1:30, 08:00). Hours may exceed 23 for long aggregated entries.
    if not re.fullmatch(r'\d{1,3}:[0-5]\d', value):
        raise ValueError('Čas musí byť zadaný vo formáte H:MM alebo HH:MM (napr. 0:30 alebo 01:30).')
    return value


def duration_to_seconds(value):
    value = validate_time_text(str(value or '').strip())
    if not value:
        return 0
    h, m = map(int, value.split(':'))
    return h * 3600 + m * 60


def seconds_to_hms(seconds):
    seconds = max(0, int(round(seconds or 0)))
    h, rem = divmod(seconds, 3600); m, sec = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{sec:02d}'


def norm_label(job):
    mode = job.get('norm_mode') or 'ct'
    if mode == 'ct':
        v = float(job.get('norm_ct_seconds') or 0)
        return f'CT {v:g} s/ks' if v > 0 else 'CT'
    if mode == 'time':
        return 'Čas zadáva OP / Operator time'
    return '—'


def calc_norm_fields(job, checked, operator_time_text=''):
    mode = job.get('norm_mode') or 'ct'
    if mode == 'ct':
        ct = float(job.get('norm_ct_seconds') or 0)
        if ct <= 0:
            raise ValueError('Pri norme CT musí byť zadaný čas cyklu v sekundách na kus.')
        return int(round(checked * ct)), ct
    if mode == 'time':
        work_seconds = duration_to_seconds(operator_time_text)
        if checked <= 0:
            raise ValueError('Pri norme podľa času musí byť Checked väčšie ako 0.')
        if work_seconds <= 0:
            raise ValueError('Zadaj čas práce / Working time.')
        return work_seconds, work_seconds / checked
    return 0, None


def parse_job_reporting(data):
    enabled = 1 if data.get('reporting_enabled') else 0
    recipients = str(data.get('reporting_recipients') or '').strip()
    report_time = str(data.get('reporting_time') or '08:00').strip()
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', report_time):
        raise ValueError('Čas automatického reportu musí byť vo formáte HH:MM.')
    raw_formats = data.get('reporting_formats') or 'pdf,xlsm'
    if isinstance(raw_formats, (list, tuple)):
        formats = [str(x).strip().lower() for x in raw_formats if str(x).strip()]
    else:
        formats = [x.strip().lower() for x in re.split(r'[,;\s]+', str(raw_formats)) if x.strip()]
    clean_formats=[]
    for fmt in formats:
        if fmt not in ('pdf','xlsx','xlsm'):
            raise ValueError('Formát automatického reportu môže byť PDF, XLSX alebo XLSM.')
        if fmt not in clean_formats:
            clean_formats.append(fmt)
    if enabled and not recipients:
        raise ValueError('Pri automatickom reportingu zadaj aspoň jedného príjemcu.')
    if enabled and not clean_formats:
        raise ValueError('Pri automatickom reportingu vyber aspoň jeden formát.')
    return enabled, recipients, report_time, ','.join(clean_formats)


def parse_job_norm(data):
    mode=str(data.get('norm_mode','ct') or 'ct').strip().lower()
    if mode not in ('ct','time'):
        raise ValueError('Vyber typ normy CT alebo Čas zadáva OP.')
    ct=None
    if mode=='ct':
        try: ct=float(data.get('norm_ct_seconds',0) or 0)
        except: raise ValueError('CT musí byť číslo v sekundách na kus.')
        if ct<=0: raise ValueError('CT musí byť väčšie ako 0 sekúnd na kus.')
    return mode,ct


def query_values(q, key):
    vals=[]
    for raw in q.get(key,[]):
        vals.extend([x.strip() for x in str(raw).split(',') if x.strip()])
    return vals


def enrich_record(d):
    try: p=d.get('part_snapshot_obj') or json.loads(d.get('part_snapshot') or '{}')
    except: p={}
    try: js=d.get('job_snapshot_obj') or json.loads(d.get('job_snapshot') or '{}')
    except: js={}
    # Hourly target applies only to jobs where the operator enters actual working time.
    is_time_mode=(js.get('norm_mode') or '')=='time'
    target=float(p.get('norm_per_hour') or 0) if is_time_mode else 0
    work=float(d.get('work_time_seconds') or 0)
    checked=float(d.get('checked_items') or 0)
    actual=(checked*3600/work) if is_time_mode and work>0 else None
    deviation=((actual-target)/target*100) if target>0 and actual is not None else None
    d['norm_target_per_hour']=target if target>0 else None
    d['actual_per_hour']=round(actual,2) if actual is not None else None
    d['norm_deviation_pct']=round(deviation,2) if deviation is not None else None
    # Red warning starts only when the result is outside the +/-10% tolerance band.
    d['norm_outside']=bool(deviation is not None and abs(deviation)>10.0)
    return d


def record_query(con, user, q):
    sql = '''SELECT r.*, u.display_name,COALESCE(u.central_login,u.username) AS username,u.role AS user_role,j.order_number,j.active AS job_active
             FROM records r JOIN users u ON u.id=r.user_id JOIN jobs j ON j.id=r.job_id WHERE 1=1'''
    args=[]
    if user['role'] != 'admin':
        sql += ' AND r.user_id=?'; args.append(user['id'])
    else:
        opvals=query_values(q,'operator_id')
        if opvals:
            placeholders=','.join('?' for _ in opvals); sql += f' AND r.user_id IN ({placeholders})'; args.extend([int(x) for x in opvals])
    jobvals=query_values(q,'job_id')
    if jobvals:
        placeholders=','.join('?' for _ in jobvals); sql += f' AND r.job_id IN ({placeholders})'; args.extend([int(x) for x in jobvals])
    partvals=query_values(q,'part_id')
    if partvals:
        placeholders=','.join('?' for _ in partvals); sql += f' AND r.part_id IN ({placeholders})'; args.extend([int(x) for x in partvals])
    if q.get('date'):
        sql += ' AND r.record_date=?'; args.append(q['date'][0])
    if q.get('date_from'):
        sql += ' AND r.record_date>=?'; args.append(q['date_from'][0])
    if q.get('date_to'):
        sql += ' AND r.record_date<=?'; args.append(q['date_to'][0])
    shifts=[x.upper() for x in query_values(q,'shift') if x.upper() in ('R','P','N')]
    if shifts:
        placeholders=','.join('?' for _ in shifts); sql += f' AND r.shift IN ({placeholders})'; args.extend(shifts)
    status=(q.get('record_status',['active'])[0] or 'active').lower()
    if status=='active': sql += ' AND COALESCE(r.archived,0)=0'
    elif status=='archived': sql += ' AND COALESCE(r.archived,0)=1'
    sql += ' ORDER BY r.record_date DESC,r.id DESC'
    out=[]
    for r in con.execute(sql,args).fetchall():
        d=dictrow(r)
        try: d['job_snapshot_obj']=json.loads(d.get('job_snapshot') or '{}')
        except: d['job_snapshot_obj']={}
        try: d['part_snapshot_obj']=json.loads(d.get('part_snapshot') or '{}')
        except: d['part_snapshot_obj']={}
        try: d['error_counts_obj']=json.loads(d.get('error_counts') or '{}')
        except: d['error_counts_obj']={}
        out.append(enrich_record(d))
    return out


def record_by_id(con, rid):
    r=con.execute('''SELECT r.*,u.display_name,COALESCE(u.central_login,u.username) AS username,u.role AS user_role,j.order_number
                     FROM records r JOIN users u ON u.id=r.user_id JOIN jobs j ON j.id=r.job_id WHERE r.id=?''',(rid,)).fetchone()
    if not r: return None
    d=dictrow(r)
    for src,dst in [('job_snapshot','job_snapshot_obj'),('part_snapshot','part_snapshot_obj'),('error_counts','error_counts_obj')]:
        try: d[dst]=json.loads(d.get(src) or ('{}' if src!='error_counts' else '{}'))
        except: d[dst]={}
    return enrich_record(d)


def prepare_record(con, data, user, allow_inactive_job=False):
    jid=int(data.get('job_id',0)); pid=int(data.get('part_id',0)); job=get_job(con,jid,True if allow_inactive_job else False)
    if not job: raise ValueError('Vyber platnú zákazku.')
    part=next((p for p in job['parts'] if p['id']==pid),None)
    if not part: raise ValueError('Vyber číslo dielu.')
    checked=require_int(data,'checked_items'); ok=require_int(data,'ok_items'); nok=require_int(data,'nok_items'); rwok=require_int(data,'reworked_ok'); rwnok=require_int(data,'reworked_nok')
    if ok+nok!=checked: raise ValueError(f'OK + NOK musí byť rovné Checked ({ok+nok} ≠ {checked}).')
    if rwok+rwnok>nok: raise ValueError('Reworked OK + Reworked NOK nemôže byť viac ako NOK.')
    counts_raw=data.get('error_counts') or {}; valid_ids={str(e['id']) for e in job['errors']}; counts={}
    for k,v in counts_raw.items():
        if str(k) in valid_ids:
            try: iv=int(v or 0)
            except: iv=0
            if iv<0: raise ValueError('Počet chýb nemôže byť záporný.')
            counts[str(k)]=iv
    err_sum=sum(counts.values())
    if err_sum!=nok: raise ValueError(f'Súčet druhov chýb musí byť rovný NOK ({err_sum} ≠ {nok}).')
    if nok>0 and not job['errors']: raise ValueError('Pri NOK musí mať zákazka definovaný aspoň jeden druh chyby.')
    shift=str(data.get('shift','')).strip().upper()
    if shift not in ('R','P','N'): raise ValueError('Vyber zmenu R / P / N.')
    rec_date=date.today().isoformat() if user['role']!='admin' else (str(data.get('record_date','')).strip() or date.today().isoformat())
    date.fromisoformat(rec_date)
    work_time_seconds,norm_seconds=calc_norm_fields(job,checked,str(data.get('operator_time','')).strip())
    snapshot={'order_number':job['order_number'],'brief_description':job['brief_description'],'norm_mode':job.get('norm_mode') or 'ct','norm_ct_seconds':job.get('norm_ct_seconds'),'errors':job['errors']}
    return {
        'job':job,'part':part,'jid':jid,'pid':pid,'record_date':rec_date,'shift':shift,
        'delivery_note':str(data.get('delivery_note','')).strip(),'checked':checked,'ok':ok,'nok':nok,'rwok':rwok,'rwnok':rwnok,
        'note':str(data.get('note','')).strip(),'counts':counts,'work_time_seconds':work_time_seconds,'norm_seconds':norm_seconds,
        'job_snapshot':json.dumps(snapshot,ensure_ascii=False),'part_snapshot':json.dumps({'id':part['id'],'item_number':part['item_number'],'part_name':part['part_name'],'norm_per_hour':part.get('norm_per_hour')},ensure_ascii=False)
    }


def col_num(ref):
    letters = re.match(r'([A-Z]+)', ref).group(1); n=0
    for c in letters: n=n*26+ord(c)-64
    return n


def set_xlsm_cell(root, ref, value, numeric=False):
    ns={'m':NS_MAIN}; row_num=int(re.search(r'(\d+)$',ref).group(1)); sheet_data=root.find('m:sheetData',ns)
    row=sheet_data.find(f"m:row[@r='{row_num}']",ns)
    if row is None: row=ET.SubElement(sheet_data,f'{{{NS_MAIN}}}row',{'r':str(row_num)})
    cell=row.find(f"m:c[@r='{ref}']",ns)
    if cell is None:
        cell=ET.Element(f'{{{NS_MAIN}}}c',{'r':ref}); inserted=False
        for i,existing in enumerate(list(row)):
            if existing.tag.endswith('c') and col_num(existing.attrib['r'])>col_num(ref): row.insert(i,cell);inserted=True;break
        if not inserted: row.append(cell)
    for child in list(cell):
        if child.tag.endswith(('v','is','f')): cell.remove(child)
    value='' if value is None else value
    if numeric:
        cell.attrib.pop('t',None); v=ET.SubElement(cell,f'{{{NS_MAIN}}}v'); v.text=str(int(value))
    else:
        cell.set('t','inlineStr'); isel=ET.SubElement(cell,f'{{{NS_MAIN}}}is'); t=ET.SubElement(isel,f'{{{NS_MAIN}}}t'); t.text=str(value)


def report_errors(job, records):
    # Keep current definitions first, then add historical definitions from record snapshots.
    out=[]; seen=set()
    for e in job.get('errors',[]):
        key=str(e.get('id'))
        if key not in seen: out.append(e); seen.add(key)
    for r in records:
        snap=r.get('job_snapshot_obj') or {}
        for e in snap.get('errors',[]) or []:
            key=str(e.get('id'))
            if key not in seen: out.append(e); seen.add(key)
    return out


def daily_template_export(job, records):
    if not os.path.exists(TEMPLATE_PATH): raise FileNotFoundError('Chýba report_template.xlsm')
    if len(records)>15: raise ValueError('Šablóna denného hlásenia má max. 15 riadkov. Zúž dátum/operátora.')
    tmpdir=tempfile.mkdtemp(prefix='miell_xlsm_')
    try:
        with zipfile.ZipFile(TEMPLATE_PATH,'r') as zin: zin.extractall(tmpdir)
        sheet_path=os.path.join(tmpdir,'xl','worksheets','sheet1.xml'); tree=ET.parse(sheet_path); root=tree.getroot()
        report_date=records[0]['record_date'] if records else date.today().isoformat(); date_label=datetime.strptime(report_date,'%Y-%m-%d').strftime('%d.%m.%Y')
        errors=report_errors(job, records)[:4]
        shifts={str(r.get('shift') or '').upper() for r in records}
        shift_text='R.  '+('X' if 'R' in shifts else '')+'      P.  '+('X' if 'P' in shifts else '')+'      N.  '+('X' if 'N' in shifts else '')
        set_xlsm_cell(root,'H2',job['order_number']); set_xlsm_cell(root,'N2',date_label); set_xlsm_cell(root,'O2',shift_text); set_xlsm_cell(root,'C3',job['brief_description'])
        set_xlsm_cell(root,'C5',norm_label(job) if (job.get('norm_mode') or 'off')!='off' else '')
        for ref, idx in [('I4',0),('I5',1),('N4',2),('N5',3)]: set_xlsm_cell(root,ref,errors[idx]['name'] if idx<len(errors) else '')
        for rr in range(8,23):
            for cc in ['A','C','D','E','F','G','H','I','J','K','L','M','N']: set_xlsm_cell(root,f'{cc}{rr}','')
        for idx,r in enumerate(records):
            rr=8+idx; part=r.get('part_snapshot_obj') or {}; ec=r.get('error_counts_obj') or {}
            set_xlsm_cell(root,f'A{rr}',part.get('item_number','')); set_xlsm_cell(root,f'C{rr}',part.get('part_name','')); set_xlsm_cell(root,f'D{rr}',r.get('delivery_note',''))
            for col,key in [('E','checked_items'),('F','ok_items'),('G','nok_items'),('H','reworked_ok'),('I','reworked_nok')]: set_xlsm_cell(root,f'{col}{rr}',r[key],True)
            for i,col in enumerate(['J','K','L','M']):
                cnt=ec.get(str(errors[i]['id']),0) if i<len(errors) else 0; set_xlsm_cell(root,f'{col}{rr}',cnt,True)
            extra=[]
            for er in report_errors(job, records)[4:]:
                val=int(ec.get(str(er['id']),0) or 0)
                if val: extra.append(f"{er['name']}: {val}")
            note=r.get('note','') or ''
            prefix=f"Shift: {r.get('shift','')}"
            note=prefix + ((' | '+note) if note else '')
            if extra: note=(note+' | ' if note else '')+'Other errors: '+', '.join(extra)
            set_xlsm_cell(root,f'N{rr}',note)
        workers={}
        for r in records:
            key=(r['user_id'],r['display_name'],r['username'],r.get('shift') or '')
            if key not in workers: workers[key]={'checked':0,'work':0}
            workers[key]['checked']+=int(r['checked_items']); workers[key]['work']+=int(r.get('work_time_seconds') or 0)
        for rr in range(25,34):
            for cc in ['A','D','E','G','I']: set_xlsm_cell(root,f'{cc}{rr}','')
        for i,((uid,name,username,shift),vals) in enumerate(list(workers.items())[:9]):
            rr=25+i; checked_sum=vals['checked']; work_sum=vals['work']
            norm_seconds=(work_sum/checked_sum) if checked_sum and work_sum else (float(job.get('norm_ct_seconds') or 0) if (job.get('norm_mode') or 'ct')=='ct' else 0)
            set_xlsm_cell(root,f'A{rr}',f'{name} ({shift})' if shift else name); set_xlsm_cell(root,f'D{rr}',username); set_xlsm_cell(root,f'E{rr}',seconds_to_hms(work_sum) if work_sum else '')
            set_xlsm_cell(root,f'G{rr}',checked_sum,True); set_xlsm_cell(root,f'I{rr}',f'{norm_seconds:.2f} s/ks' if norm_seconds else '')
        # Preserve every original template style and add only warning variants.
        styles_path=os.path.join(tmpdir,'xl','styles.xml')
        styles_tree=ET.parse(styles_path); styles_root=styles_tree.getroot()
        fills=styles_root.find(f'{{{NS_MAIN}}}fills'); xfs=styles_root.find(f'{{{NS_MAIN}}}cellXfs')
        if fills is not None and xfs is not None and any(r.get('norm_outside') for r in records):
            fill_id=len(fills)
            fill=ET.SubElement(fills,f'{{{NS_MAIN}}}fill')
            pattern=ET.SubElement(fill,f'{{{NS_MAIN}}}patternFill',{'patternType':'solid'})
            ET.SubElement(pattern,f'{{{NS_MAIN}}}fgColor',{'rgb':'FFFEE2E2'})
            ET.SubElement(pattern,f'{{{NS_MAIN}}}bgColor',{'indexed':'64'})
            fills.set('count',str(len(fills)))
            variants={}
            for idx,r in enumerate(records):
                if not r.get('norm_outside'): continue
                for cell in root.findall(f'.//{{{NS_MAIN}}}row[@r="{8+idx}"]/{{{NS_MAIN}}}c'):
                    old=int(cell.get('s','0'))
                    if old not in variants:
                        variant=copy.deepcopy(xfs[old]); variant.set('fillId',str(fill_id)); variant.set('applyFill','1')
                        variants[old]=len(xfs); xfs.append(variant)
                    cell.set('s',str(variants[old]))
            xfs.set('count',str(len(xfs)))
            styles_tree.write(styles_path,encoding='utf-8',xml_declaration=True)
        tree.write(sheet_path,encoding='utf-8',xml_declaration=True)
        out=os.path.join(tempfile.mkdtemp(prefix='miell_export_'),f"MIELL_Daily_Report_{safe(job['order_number'])}_{report_date}.xlsm")
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as zout:
            for rootdir,dirs,files in os.walk(tmpdir):
                for fn in files:
                    full=os.path.join(rootdir,fn); zout.write(full,os.path.relpath(full,tmpdir))
        return out
    finally: shutil.rmtree(tmpdir,ignore_errors=True)


def xlsx_col(n):
    s=''
    while n: n,rem=divmod(n-1,26); s=chr(65+rem)+s
    return s


def xml_escape(v): return html.escape('' if v is None else str(v), quote=False)


def make_summary_xlsx(job, records):
    errors=report_errors(job, records)
    headers=['Date','Shift','Order number','Item number','Part name','Delivery note','Checked items','OK','NOK','Reworked OK','Reworked NOK','Working time','Norm s/item','Target pcs/hour','Actual pcs/hour','Deviation %']+[e['name'] for e in errors]+['Note','Operator']
    rows=[]
    for r in records:
        p=r.get('part_snapshot_obj') or {}; ec=r.get('error_counts_obj') or {}
        norm_val=round(float(r.get('norm_seconds_per_item') or 0),2) if r.get('norm_seconds_per_item') is not None else ''
        rows.append([r['record_date'],r.get('shift',''),job['order_number'],p.get('item_number',''),p.get('part_name',''),r.get('delivery_note',''),r['checked_items'],r['ok_items'],r['nok_items'],r['reworked_ok'],r['reworked_nok'],seconds_to_hms(r.get('work_time_seconds') or 0) if r.get('work_time_seconds') else '',norm_val,r.get('norm_target_per_hour') or '',r.get('actual_per_hour') or '',r.get('norm_deviation_pct') if r.get('norm_deviation_pct') is not None else '']+[int(ec.get(str(e['id']),0) or 0) for e in errors]+[r.get('note',''),r.get('display_name','')])
    checked=sum(int(r['checked_items']) for r in records); ok=sum(int(r['ok_items']) for r in records); nok=sum(int(r['nok_items']) for r in records); rwok=sum(int(r['reworked_ok']) for r in records); rwnok=sum(int(r['reworked_nok']) for r in records)
    info=[['MIELL Quality - Job report'],['Order number',job['order_number']],['Brief description',job['brief_description']],['Norm',norm_label(job)],['Checked',checked,'OK',ok,'NOK',nok,'Reworked OK',rwok,'Reworked NOK',rwnok],[]]
    return simple_xlsx(info, headers, rows, f"MIELL_Job_Report_{safe(job['order_number'])}_{date.today().isoformat()}.xlsx")


def simple_xlsx(info, headers, rows, filename):
    def cell(ref,val,style=0):
        if isinstance(val,(int,float)) and not isinstance(val,bool): return f'<c r="{ref}" s="{style}"><v>{val}</v></c>'
        return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{xml_escape(val)}</t></is></c>'
    sheet_rows=[]; rr=1
    for row in info:
        cells=''.join(cell(f'{xlsx_col(i+1)}{rr}',v,1 if rr==1 else 0) for i,v in enumerate(row)); sheet_rows.append(f'<row r="{rr}">{cells}</row>'); rr+=1
    cells=''.join(cell(f'{xlsx_col(i+1)}{rr}',v,2) for i,v in enumerate(headers)); sheet_rows.append(f'<row r="{rr}">{cells}</row>'); rr+=1
    for row in rows:
        cells=''.join(cell(f'{xlsx_col(i+1)}{rr}',v,0) for i,v in enumerate(row)); sheet_rows.append(f'<row r="{rr}">{cells}</row>'); rr+=1
    widths=[]
    for i,h in enumerate(headers,1):
        w=14
        if h in ('Brief description','Note'): w=28
        elif h in ('Part name','Operator'): w=20
        widths.append(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>')
    sheet=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{NS_MAIN}"><cols>{''.join(widths)}</cols><sheetData>{''.join(sheet_rows)}</sheetData></worksheet>'''
    styles='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="3"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="16"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/><color rgb="FFFFFFFF"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF2FAC66"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs></styleSheet>'''
    workbook=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{NS_MAIN}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    rels='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    rootrels='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
    content='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'''
    out=os.path.join(tempfile.gettempdir(),filename)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',content); z.writestr('_rels/.rels',rootrels); z.writestr('xl/workbook.xml',workbook); z.writestr('xl/_rels/workbook.xml.rels',rels); z.writestr('xl/worksheets/sheet1.xml',sheet); z.writestr('xl/styles.xml',styles)
    return out


def mixed_report_errors(records):
    out=[]; seen=set()
    for r in records:
        snap=r.get('job_snapshot_obj') or {}
        for e in snap.get('errors',[]) or []:
            key=str(e.get('id'))
            if key and key not in seen:
                seen.add(key); out.append({'id':key,'name':e.get('name') or f'Error {key}'})
    return out


def make_records_xlsx(records):
    errors=mixed_report_errors(records)
    headers=['Date','Shift','Order number','Item number','Part name','Delivery note','Checked','OK','NOK','Reworked OK','Reworked NOK','Working time','Norm s/item','Target pcs/hour','Actual pcs/hour','Deviation %']+[e['name'] for e in errors]+['Operator','Note','Status']
    rows=[]
    for r in records:
        p=r.get('part_snapshot_obj') or {}; ec=r.get('error_counts_obj') or {}
        rows.append([r['record_date'],r.get('shift',''),r.get('order_number',''),p.get('item_number',''),p.get('part_name',''),r.get('delivery_note',''),r.get('checked_items',0),r.get('ok_items',0),r.get('nok_items',0),r.get('reworked_ok',0),r.get('reworked_nok',0),seconds_to_hms(r.get('work_time_seconds') or 0) if r.get('work_time_seconds') else '',round(float(r.get('norm_seconds_per_item') or 0),2) if r.get('norm_seconds_per_item') is not None else '',r.get('norm_target_per_hour') or '',r.get('actual_per_hour') or '',r.get('norm_deviation_pct') if r.get('norm_deviation_pct') is not None else '']+[int(ec.get(str(e['id']),0) or 0) for e in errors]+[r.get('display_name',''),r.get('note',''),'Archived' if r.get('archived') else 'Active'])
    info=[['MIELL Quality - Records report'],['Generated',datetime.now().strftime('%d.%m.%Y %H:%M')],['Records',len(records)],[]]
    return simple_xlsx(info,headers,rows,f"MIELL_Records_Report_{date.today().isoformat()}.xlsx")


def safe(v): return re.sub(r'[^A-Za-z0-9_.-]+','_',str(v))[:80]


def logo_data_uri():
    try:
        return 'data:image/png;base64,'+base64.b64encode(open(LOGO_PATH,'rb').read()).decode('ascii')
    except: return ''


def report_html(job, records, title_scope=''):
    errors=report_errors(job, records); checked=sum(int(r['checked_items']) for r in records); ok=sum(int(r['ok_items']) for r in records); nok=sum(int(r['nok_items']) for r in records); rwok=sum(int(r['reworked_ok']) for r in records); rwnok=sum(int(r['reworked_nok']) for r in records)
    dates=sorted({r['record_date'] for r in records}); date_label=(dates[0] if len(dates)==1 else (f'{dates[0]} - {dates[-1]}' if dates else date.today().isoformat()))
    shifts='/'.join(x for x in ['R','P','N'] if any((r.get('shift') or '')==x for r in records)) or '-'
    th_errors=''.join(f'<th>{html.escape(e["name"])}</th>' for e in errors)
    body=[]
    for r in records:
        p=r.get('part_snapshot_obj') or {}; ec=r.get('error_counts_obj') or {}
        errcells=''.join(f'<td>{int(ec.get(str(e["id"]),0) or 0)}</td>' for e in errors)
        normv=f'{float(r.get("norm_seconds_per_item") or 0):.2f}' if r.get('norm_seconds_per_item') is not None else ''
        target=f'{float(r.get("norm_target_per_hour")):.2f}' if r.get('norm_target_per_hour') is not None else ''
        actual=f'{float(r.get("actual_per_hour")):.2f}' if r.get('actual_per_hour') is not None else ''
        deviation=f'{float(r.get("norm_deviation_pct")):+.2f}%' if r.get('norm_deviation_pct') is not None else ''
        rowcls=' class="outside"' if r.get('norm_outside') else ''
        body.append(f'''<tr{rowcls}><td>{html.escape(r['record_date'])}</td><td><b>{html.escape(r.get('shift',''))}</b></td><td>{html.escape(p.get('item_number',''))}</td><td>{html.escape(p.get('part_name',''))}</td><td>{html.escape(r.get('delivery_note','') or '')}</td><td>{r['checked_items']}</td><td>{r['ok_items']}</td><td>{r['nok_items']}</td><td>{r['reworked_ok']}</td><td>{r['reworked_nok']}</td><td>{html.escape(seconds_to_hms(r.get('work_time_seconds') or 0) if r.get('work_time_seconds') else '')}</td><td>{normv}</td><td>{target}</td><td>{actual}</td><td>{deviation}</td>{errcells}<td>{html.escape(r.get('note','') or '')}</td><td>{html.escape(r.get('display_name',''))}</td></tr>''')
    workers={}
    for r in records:
        key=(r['display_name'],r.get('shift') or '')
        if key not in workers: workers[key]={'checked':0,'work':0}
        workers[key]['checked']+=int(r['checked_items']); workers[key]['work']+=int(r.get('work_time_seconds') or 0)
    worker_rows=[]
    for (name,shift),v in workers.items():
        normsec=(v['work']/v['checked']) if v['checked'] and v['work'] else (float(job.get('norm_ct_seconds') or 0) if (job.get('norm_mode') or 'ct')=='ct' else 0)
        worker_rows.append(f'<tr><td>{html.escape(name)} ({html.escape(shift)})</td><td>{html.escape(seconds_to_hms(v["work"]) if v["work"] else "-")}</td><td>{v["checked"]}</td><td>{normsec:.2f} s/ks</td></tr>')
    worker_rows=''.join(worker_rows) or '<tr><td colspan="4">-</td></tr>'
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>MIELL Daily Report</title><style>@page{{size:A4 landscape;margin:7mm}}*{{box-sizing:border-box}}body{{font-family:Arial,sans-serif;color:#111;margin:0;font-size:9px}}.toolbar{{position:fixed;right:8px;top:8px}}.toolbar button{{padding:8px 12px}}.logo{{width:150px;height:auto}}h1{{margin:0;font-size:22px}}.top{{display:grid;grid-template-columns:180px 1fr 280px;align-items:center;border:1px solid #444;background:#d0d0d0;padding:8px}}.meta{{display:grid;grid-template-columns:170px 1fr 150px 1fr;border-left:1px solid #444;border-right:1px solid #444}}.meta div{{border-bottom:1px solid #444;padding:6px}}.label{{font-weight:bold;background:#dedede}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #555;padding:4px;text-align:center}}th{{background:#d0d0d0}}tr.outside td{{background:#ffd9d9;color:#8b1d1d}}td.note{{text-align:left}}.kpis{{display:flex;gap:10px;margin:8px 0}}.kpi{{border:1px solid #777;padding:6px 10px;min-width:100px}}.kpi b{{font-size:15px}}.workers{{width:65%;margin-top:8px}}.scope{{font-size:9px;color:#444}}@media print{{.toolbar{{display:none}}}}</style></head><body><div class="toolbar"><button onclick="window.print()">Print / Save as PDF</button></div><div class="top"><img class="logo" src="{logo_data_uri()}"><div><h1>Denné hlásenie / Daily report</h1><div class="scope">{html.escape(title_scope)}</div></div><div><b>Číslo objednávky / Order number:</b> {html.escape(job['order_number'])}<br><b>Dátum / Date:</b> {html.escape(date_label)}<br><b>Zmena / Shift:</b> {html.escape(shifts)}</div></div><div class="meta"><div class="label">Krátky popis úlohy / Brief description</div><div>{html.escape(job['brief_description'])}</div><div class="label">Norma / Norm</div><div>{html.escape(norm_label(job))}</div></div><div class="kpis"><div class="kpi">Checked<br><b>{checked}</b></div><div class="kpi">OK<br><b>{ok}</b></div><div class="kpi">NOK<br><b>{nok}</b></div><div class="kpi">Reworked OK<br><b>{rwok}</b></div><div class="kpi">Reworked NOK<br><b>{rwnok}</b></div><div class="kpi">NOK rate<br><b>{(nok/checked*100 if checked else 0):.2f}%</b></div></div><table><thead><tr><th>Date</th><th>Shift</th><th>Číslo dielu / Item number</th><th>Názov dielu / Part name</th><th>Delivery note</th><th>Checked</th><th>OK</th><th>NOK</th><th>R.OK</th><th>R.NOK</th><th>Working time</th><th>Norm s/item</th><th>Target/h</th><th>Actual/h</th><th>Deviation</th>{th_errors}<th>Note</th><th>Worker</th></tr></thead><tbody>{''.join(body) if body else '<tr><td colspan="99">No records</td></tr>'}</tbody></table><table class="workers"><thead><tr><th>Prácu vykonal / Worker</th><th>Pracovný čas / Working time</th><th>Počet kusov / Checked items</th><th>Norma / Norm</th></tr></thead><tbody>{worker_rows}</tbody></table><script>window.addEventListener("load",()=>setTimeout(()=>window.print(),350));</script></body></html>'''


def records_report_html(records, title_scope='Filtered records / Filtrované záznamy'):
    errors=mixed_report_errors(records); body=[]; checked=ok=nok=0
    th_errors=''.join(f'<th>{html.escape(e["name"])}</th>' for e in errors)
    for r in records:
        p=r.get('part_snapshot_obj') or {}; ec=r.get('error_counts_obj') or {}; checked+=int(r.get('checked_items') or 0); ok+=int(r.get('ok_items') or 0); nok+=int(r.get('nok_items') or 0)
        cls=' class="outside"' if r.get('norm_outside') else ''
        target=f'{float(r["norm_target_per_hour"]):.2f}' if r.get('norm_target_per_hour') is not None else ''
        actual=f'{float(r["actual_per_hour"]):.2f}' if r.get('actual_per_hour') is not None else ''
        dev=f'{float(r["norm_deviation_pct"]):+.2f}%' if r.get('norm_deviation_pct') is not None else ''
        errcells=''.join(f'<td>{int(ec.get(str(e["id"]),0) or 0)}</td>' for e in errors)
        body.append(f'''<tr{cls}><td>{html.escape(r.get('record_date',''))}</td><td>{html.escape(r.get('shift',''))}</td><td>{html.escape(r.get('order_number',''))}</td><td>{html.escape(p.get('item_number',''))}</td><td>{html.escape(p.get('part_name',''))}</td><td>{html.escape(r.get('delivery_note','') or '')}</td><td>{r.get('checked_items',0)}</td><td>{r.get('ok_items',0)}</td><td>{r.get('nok_items',0)}</td><td>{r.get('reworked_ok',0)}</td><td>{r.get('reworked_nok',0)}</td><td>{html.escape(seconds_to_hms(r.get('work_time_seconds') or 0) if r.get('work_time_seconds') else '')}</td><td>{target}</td><td>{actual}</td><td>{dev}</td>{errcells}<td>{html.escape(r.get('display_name',''))}</td><td>{html.escape(r.get('note','') or '')}</td></tr>''')
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>MIELL Records Report</title><style>@page{{size:A4 landscape;margin:7mm}}body{{font-family:Arial,sans-serif;font-size:8px;color:#111}}.top{{display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid #4cb82f;padding-bottom:8px}}.logo{{width:155px}}h1{{font-size:20px;margin:0}}.kpis{{display:flex;gap:10px;margin:10px 0}}.kpi{{border:1px solid #aaa;padding:6px 10px}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #777;padding:3px}}th{{background:#ddd}}tr.outside td{{background:#ffd9d9;color:#8b1d1d}}.toolbar{{position:fixed;right:8px;top:8px}}@media print{{.toolbar{{display:none}}}}</style></head><body><div class="toolbar"><button onclick="window.print()">Print / Save as PDF</button></div><div class="top"><img class="logo" src="{logo_data_uri()}"><div><h1>Záznamy / Records report</h1><div>{html.escape(title_scope)}</div></div></div><div class="kpis"><div class="kpi">Records: <b>{len(records)}</b></div><div class="kpi">Checked: <b>{checked}</b></div><div class="kpi">OK: <b>{ok}</b></div><div class="kpi">NOK: <b>{nok}</b></div></div><table><thead><tr><th>Date</th><th>Shift</th><th>Order</th><th>Item</th><th>Part</th><th>Delivery note</th><th>Checked</th><th>OK</th><th>NOK</th><th>R.OK</th><th>R.NOK</th><th>Time</th><th>Target/h</th><th>Actual/h</th><th>Deviation</th>{th_errors}<th>Operator</th><th>Note</th></tr></thead><tbody>{''.join(body) if body else '<tr><td colspan="99">No records</td></tr>'}</tbody></table><script>window.addEventListener("load",()=>setTimeout(()=>window.print(),350));</script></body></html>'''


def make_records_pdf(records, scope='Filtered records / Filtrované záznamy'):
    browser=find_browser()
    if not browser: raise RuntimeError('Nenašiel sa Microsoft Edge/Chrome pre automatický PDF export.')
    td=tempfile.mkdtemp(prefix='miell_records_pdf_'); html_path=os.path.join(td,'report.html'); out=os.path.join(tempfile.gettempdir(),f"MIELL_Records_Report_{date.today().isoformat()}.pdf")
    with open(html_path,'w',encoding='utf-8') as f: f.write(records_report_html(records,scope))
    url='file:///'+html_path.replace('\\','/').lstrip('/') if os.name=='nt' else 'file://'+html_path
    cmd=[browser,'--headless=new','--disable-gpu','--no-pdf-header-footer',f'--print-to-pdf={out}',url]
    try:
        cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40)
        if cp.returncode!=0 or not os.path.exists(out) or os.path.getsize(out)<1000: raise RuntimeError('PDF export zlyhal.')
        return out
    finally: shutil.rmtree(td,ignore_errors=True)


def find_browser():
    candidates=[]
    if os.name=='nt':
        pf=os.environ.get('ProgramFiles','C:\\Program Files'); pfx=os.environ.get('ProgramFiles(x86)','C:\\Program Files (x86)'); local=os.environ.get('LOCALAPPDATA','')
        candidates += [os.path.join(pfx,'Microsoft','Edge','Application','msedge.exe'),os.path.join(pf,'Microsoft','Edge','Application','msedge.exe'),os.path.join(local,'Microsoft','Edge','Application','msedge.exe'),os.path.join(pf,'Google','Chrome','Application','chrome.exe'),os.path.join(pfx,'Google','Chrome','Application','chrome.exe')]
    else:
        for name in ['chromium','chromium-browser','google-chrome','microsoft-edge']:
            p=shutil.which(name)
            if p: candidates.append(p)
    return next((p for p in candidates if p and os.path.exists(p)),None)


def make_pdf(job, records, scope=''):
    browser=find_browser()
    if not browser: raise RuntimeError('Nenašiel sa Microsoft Edge/Chrome pre automatický PDF export.')
    td=tempfile.mkdtemp(prefix='miell_pdf_'); html_path=os.path.join(td,'report.html'); out=os.path.join(tempfile.gettempdir(),f"MIELL_Report_{safe(job['order_number'])}_{date.today().isoformat()}.pdf")
    with open(html_path,'w',encoding='utf-8') as f: f.write(report_html(job,records,scope))
    url='file:///'+html_path.replace('\\','/').lstrip('/') if os.name=='nt' else 'file://'+html_path
    cmd=[browser,'--headless=new','--disable-gpu','--no-pdf-header-footer',f'--print-to-pdf={out}',url]
    try:
        cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40)
        if cp.returncode!=0 or not os.path.exists(out) or os.path.getsize(out)<1000:
            raise RuntimeError('PDF export zlyhal. Použi tlačidlo Print / Save as PDF.')
        return out
    finally: shutil.rmtree(td,ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    server_version='MIELLReporting/2.4'
    def log_message(self,fmt,*args): sys.stdout.write('[%s] %s\n'%(self.log_date_time_string(),fmt%args))
    def _body(self):
        n=int(self.headers.get('Content-Length',0) or 0); raw=self.rfile.read(n) if n else b'{}'
        try:return json.loads(raw.decode('utf-8'))
        except:return {}
    def _json(self,obj,status=200,headers=None):
        data=json.dumps(obj,ensure_ascii=False).encode('utf-8'); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(data)))
        if headers:
            for k,v in headers.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)
    def _file(self,path,ctype=None,download=None):
        if not os.path.exists(path): return self.send_error(404)
        data=open(path,'rb').read(); self.send_response(200); self.send_header('Content-Type',ctype or mimetypes.guess_type(path)[0] or 'application/octet-stream'); self.send_header('Content-Length',str(len(data)))
        if download: self.send_header('Content-Disposition',f'attachment; filename="{download}"')
        self.end_headers(); self.wfile.write(data)
    def _session(self):
        c=SimpleCookie(self.headers.get('Cookie','')); sid=c.get('miell_session'); return SESSIONS.get(sid.value) if sid else None
    def _auth(self,admin=False):
        u=self._session()
        if not u: self._json({'error':'Nie ste prihlásený.'},401); return None
        if admin and u['role']!='admin': self._json({'error':'Táto funkcia je iba pre administrátora.'},403); return None
        return u
    def _pathq(self):
        p=urllib.parse.urlparse(self.path); return p.path,urllib.parse.parse_qs(p.query)
    def _records_for_export(self,user,q,job_id):
        qq=dict(q); qq['job_id']=[str(job_id)]; con=db(); recs=record_query(con,user,qq); job=get_job(con,job_id,True); con.close(); return job,recs

    def do_GET(self):
        path,q=self._pathq()
        if path=='/api/me': return self._json({'user':self._session()})
        if path=='/api/jobs':
            u=self._auth();
            if not u:return
            con=db(); jobs=list_jobs(con,include_inactive=(u['role']=='admin' and q.get('all',['0'])[0]=='1')); con.close(); return self._json({'jobs':jobs})
        m=re.fullmatch(r'/api/jobs/(\d+)',path)
        if m:
            u=self._auth();
            if not u:return
            con=db(); job=get_job(con,int(m.group(1)),True); con.close(); return self._json({'job':job}) if job else self._json({'error':'Zákazka neexistuje.'},404)
        if path=='/api/users':
            u=self._auth(admin=True);
            if not u:return
            con=db(); rows=[dictrow(r) for r in con.execute('SELECT id,username,display_name,role,active,created_at FROM users ORDER BY role,display_name')]; con.close(); return self._json({'users':rows})
        if path=='/api/records':
            u=self._auth();
            if not u:return
            con=db(); rows=record_query(con,u,q); con.close(); return self._json({'records':rows})
        m=re.fullmatch(r'/api/records/(\d+)',path)
        if m:
            u=self._auth(admin=True);
            if not u:return
            con=db(); row=record_by_id(con,int(m.group(1))); con.close()
            return self._json({'record':row}) if row else self._json({'error':'Záznam neexistuje.'},404)
        if path=='/api/dashboard':
            u=self._auth(admin=True);
            if not u:return
            con=db(); today=date.today().isoformat(); row=con.execute('SELECT COALESCE(SUM(checked_items),0) checked,COALESCE(SUM(ok_items),0) ok,COALESCE(SUM(nok_items),0) nok,COALESCE(SUM(reworked_ok),0) rwok,COALESCE(SUM(reworked_nok),0) rwnok,COUNT(*) records FROM records WHERE record_date=? AND COALESCE(archived,0)=0',(today,)).fetchone(); active=list_jobs(con,False); jobcards=[]
            for j in active:
                jr=con.execute('SELECT COALESCE(SUM(checked_items),0) checked,COALESCE(SUM(ok_items),0) ok,COALESCE(SUM(nok_items),0) nok,COUNT(*) records FROM records WHERE job_id=? AND record_date=? AND COALESCE(archived,0)=0',(j['id'],today)).fetchone(); x=dictrow(jr); x.update({'id':j['id'],'order_number':j['order_number'],'brief_description':j['brief_description'],'parts':j['parts'],'norm_mode':j.get('norm_mode'),'norm_ct_seconds':j.get('norm_ct_seconds')}); x['nok_rate']=round((x['nok']/x['checked']*100) if x['checked'] else 0,2); jobcards.append(x)
            con.close(); d=dictrow(row); d['active_jobs']=len(active); d['jobs']=jobcards; return self._json(d)
        m=re.fullmatch(r'/api/jobs/(\d+)/summary',path)
        if m:
            u=self._auth(admin=True);
            if not u:return
            jid=int(m.group(1)); qq=dict(q); qq['job_id']=[str(jid)]; con=db(); job=get_job(con,jid,True); rows=record_query(con,u,qq); con.close()
            if not job:return self._json({'error':'Zákazka neexistuje.'},404)
            totals={k:sum(int(r[k]) for r in rows) for k in ['checked_items','ok_items','nok_items','reworked_ok','reworked_nok']}; totals['record_count']=len(rows); totals['nok_rate']=round((totals['nok_items']/totals['checked_items']*100) if totals['checked_items'] else 0,2)
            return self._json({'job':job,'records':rows,'totals':totals})
        if path=='/api/export/records-xlsx':
            u=self._auth(admin=True)
            if not u:return
            try:
                con=db(); recs=record_query(con,u,q); con.close(); out=make_records_xlsx(recs); return self._file(out,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',os.path.basename(out))
            except Exception as e:return self._json({'error':str(e)},400)
        if path=='/api/export/records-pdf':
            u=self._auth(admin=True)
            if not u:return
            try:
                con=db(); recs=record_query(con,u,q); con.close(); out=make_records_pdf(recs); return self._file(out,'application/pdf',os.path.basename(out))
            except Exception as e:return self._json({'error':str(e),'fallback':'/report/records-print?'+urllib.parse.urlencode({k:','.join(v) for k,v in q.items()})},400)
        if path=='/report/records-print':
            u=self._auth(admin=True)
            if not u:return
            con=db(); recs=record_query(con,u,q); con.close(); raw=records_report_html(recs).encode('utf-8'); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); return self.wfile.write(raw)
        if path=='/api/export/daily-xlsm':
            u=self._auth();
            if not u:return
            try:
                jid=int(q.get('job_id',['0'])[0]); dt=q.get('date',[''])[0]; qq={'date':[dt]}; job,recs=self._records_for_export(u,qq,jid)
                if not job:raise ValueError('Zákazka neexistuje.')
                out=daily_template_export(job,recs); return self._file(out,'application/vnd.ms-excel',os.path.basename(out))
            except Exception as e:return self._json({'error':str(e)},400)
        if path=='/api/export/xlsx':
            u=self._auth(admin=True);
            if not u:return
            try:
                jid=int(q.get('job_id',['0'])[0]); job,recs=self._records_for_export(u,q,jid)
                if not job:raise ValueError('Zákazka neexistuje.')
                out=make_summary_xlsx(job,recs); return self._file(out,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',os.path.basename(out))
            except Exception as e:return self._json({'error':str(e)},400)
        if path=='/api/export/pdf':
            u=self._auth();
            if not u:return
            try:
                jid=int(q.get('job_id',['0'])[0]); job,recs=self._records_for_export(u,q,jid)
                if not job:raise ValueError('Zákazka neexistuje.')
                scope='My records / Moje záznamy' if u['role']!='admin' else 'All records / Všetky záznamy'
                out=make_pdf(job,recs,scope); return self._file(out,'application/pdf',os.path.basename(out))
            except Exception as e:return self._json({'error':str(e),'fallback':f'/report/print?{urllib.parse.urlencode({k:v[0] for k,v in q.items()})}'},400)
        if path=='/report/print':
            u=self._auth();
            if not u:return
            try:
                jid=int(q.get('job_id',['0'])[0]); job,recs=self._records_for_export(u,q,jid)
                if not job:raise ValueError('Zákazka neexistuje.')
                raw=report_html(job,recs,'My records / Moje záznamy' if u['role']!='admin' else 'All records / Všetky záznamy').encode('utf-8'); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); return self.wfile.write(raw)
            except Exception as e:return self._json({'error':str(e)},400)
        if path.startswith('/api/'): return self._json({'error':'API endpoint neexistuje.'},404)
        # static
        rel='index.html' if path in ('/','') else path.lstrip('/'); full=os.path.abspath(os.path.join(STATIC_DIR,rel))
        if not full.startswith(os.path.abspath(STATIC_DIR)): return self.send_error(403)
        return self._file(full)

    def do_POST(self):
        path,q=self._pathq(); data=self._body()
        if path=='/api/login':
            con=db(); r=con.execute('SELECT * FROM users WHERE username=? AND active=1',(str(data.get('username','')).strip(),)).fetchone(); con.close()
            if not r or not verify_password(str(data.get('password','')),r['password_salt'],r['password_hash']): return self._json({'error':'Nesprávne prihlasovacie údaje.'},401)
            sid=secrets.token_urlsafe(32); user={k:r[k] for k in ['id','username','display_name','role']}; SESSIONS[sid]=user; return self._json({'user':user},headers={'Set-Cookie':f'miell_session={sid}; HttpOnly; SameSite=Lax; Path=/'})
        if path=='/api/logout':
            c=SimpleCookie(self.headers.get('Cookie','')); sid=c.get('miell_session');
            if sid: SESSIONS.pop(sid.value,None)
            return self._json({'ok':True},headers={'Set-Cookie':'miell_session=; Max-Age=0; Path=/'})
        if path=='/api/change-password':
            u=self._auth()
            if not u:return
            try:
                current=str(data.get('current_password',''))
                new_password=str(data.get('new_password',''))
                confirm=str(data.get('confirm_password',''))
                if not current: raise ValueError('Zadaj aktuálne heslo.')
                if len(new_password)<6: raise ValueError('Nové heslo musí mať minimálne 6 znakov.')
                if new_password!=confirm: raise ValueError('Nové heslá sa nezhodujú.')
                if current==new_password: raise ValueError('Nové heslo musí byť odlišné od aktuálneho hesla.')
                con=db(); r=con.execute('SELECT password_salt,password_hash FROM users WHERE id=? AND active=1',(u['id'],)).fetchone()
                if not r or not verify_password(current,r['password_salt'],r['password_hash']):
                    con.close(); raise ValueError('Aktuálne heslo nie je správne.')
                salt,ph=hash_password(new_password); con.execute('UPDATE users SET password_salt=?,password_hash=? WHERE id=?',(salt,ph,u['id'])); con.commit(); con.close()
                # Keep the current session active, invalidate any other sessions for this account.
                c=SimpleCookie(self.headers.get('Cookie','')); sid_cookie=c.get('miell_session'); current_sid=sid_cookie.value if sid_cookie else None
                for sid,sess in list(SESSIONS.items()):
                    if sess.get('id')==u['id'] and sid!=current_sid: SESSIONS.pop(sid,None)
                return self._json({'ok':True})
            except Exception as e:
                try: con.close()
                except: pass
                return self._json({'error':str(e)},400)
        m=re.fullmatch(r'/api/records/(\d+)/(archive|restore)',path)
        if m:
            u=self._auth(admin=True)
            if not u:return
            rid=int(m.group(1)); archived=1 if m.group(2)=='archive' else 0; con=db(); con.execute('UPDATE records SET archived=? WHERE id=?',(archived,rid)); con.commit(); con.close(); return self._json({'ok':True,'archived':bool(archived)})
        m=re.fullmatch(r'/api/jobs/(\d+)/(archive|restore)',path)
        if m:
            u=self._auth(admin=True)
            if not u:return
            jid=int(m.group(1)); active=0 if m.group(2)=='archive' else 1; con=db(); con.execute('UPDATE jobs SET active=?,updated_at=? WHERE id=?',(active,datetime.now().isoformat(timespec='seconds'),jid)); con.commit(); con.close(); return self._json({'ok':True,'active':bool(active)})
        if path=='/api/jobs':
            u=self._auth(admin=True);
            if not u:return
            try:
                order=str(data.get('order_number','')).strip(); brief=str(data.get('brief_description','')).strip()
                if not order or not brief:raise ValueError('Order number a Brief description sú povinné.')
                norm_mode,norm_ct_seconds=parse_job_norm(data); norm_enabled=1; norm_time=''
                parts=data.get('parts') or []; errors=data.get('errors') or []
                parts=[{'item_number':str(x.get('item_number','')).strip(),'part_name':str(x.get('part_name','')).strip(),'norm_per_hour':float(x.get('norm_per_hour') or 0) if str(x.get('norm_per_hour') or '').strip() else None} for x in parts if str(x.get('item_number','')).strip() or str(x.get('part_name','')).strip()]
                if not parts:raise ValueError('Pridaj aspoň jedno číslo dielu.')
                if any(not x['item_number'] for x in parts):raise ValueError('Každý diel musí mať číslo dielu.')
                if any((x.get('norm_per_hour') is not None and x.get('norm_per_hour') <= 0) for x in parts): raise ValueError('Norma ks/h musí byť väčšia ako 0.')
                if norm_mode!='time':
                    for p in parts: p['norm_per_hour']=None
                errors=[str(x).strip() for x in errors if str(x).strip()]
                report_enabled,report_recipients,report_time,report_formats=parse_job_reporting(data)
                now=datetime.now().isoformat(timespec='seconds'); con=db(); cur=con.execute('INSERT INTO jobs(order_number,brief_description,norm_enabled,norm_time,norm_mode,norm_ct_seconds,active,created_at,updated_at,location_id,reporting_enabled,reporting_recipients,reporting_time,reporting_formats) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(order,brief,norm_enabled,norm_time,norm_mode,norm_ct_seconds,1 if data.get('active',True) else 0,now,now,data.get('location_id'),report_enabled,report_recipients,report_time,report_formats)); jid=cur.lastrowid
                for i,p in enumerate(parts): con.execute('INSERT INTO job_parts(job_id,item_number,part_name,norm_per_hour,sort_order,active) VALUES(?,?,?,?,?,1)',(jid,p['item_number'],p['part_name'],p.get('norm_per_hour'),i))
                for i,e in enumerate(errors): con.execute('INSERT INTO job_errors(job_id,name,sort_order,active) VALUES(?,?,?,1)',(jid,e,i))
                con.commit(); job=get_job(con,jid,True); con.close(); return self._json({'job':job},201)
            except sqlite3.IntegrityError:return self._json({'error':'Číslo objednávky už existuje.'},400)
            except Exception as e:return self._json({'error':str(e)},400)
        if path=='/api/users':
            u=self._auth(admin=True);
            if not u:return
            try:
                username=str(data.get('username','')).strip(); display=str(data.get('display_name','')).strip(); role=data.get('role','operator'); password=str(data.get('password',''))
                if not username or not display or role not in ('admin','operator') or len(password)<6:raise ValueError('Vyplň meno, username, rolu a heslo min. 6 znakov.')
                salt,ph=hash_password(password); con=db(); con.execute('INSERT INTO users(username,display_name,role,password_salt,password_hash,active,created_at) VALUES(?,?,?,?,?,?,?)',(username,display,role,salt,ph,1 if data.get('active',True) else 0,datetime.now().isoformat(timespec='seconds'))); con.commit(); con.close(); return self._json({'ok':True},201)
            except sqlite3.IntegrityError:return self._json({'error':'Username už existuje.'},400)
            except Exception as e:return self._json({'error':str(e)},400)
        if path=='/api/records':
            u=self._auth();
            if not u:return
            try:
                con=db(); v=prepare_record(con,data,u,False)
                cur=con.execute('''INSERT INTO records(job_id,part_id,user_id,record_date,delivery_note,checked_items,ok_items,nok_items,reworked_ok,reworked_nok,note,job_snapshot,part_snapshot,error_counts,shift,work_time_seconds,norm_seconds_per_item,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (v['jid'],v['pid'],data.get('_record_user_id',u['id']),v['record_date'],v['delivery_note'],v['checked'],v['ok'],v['nok'],v['rwok'],v['rwnok'],v['note'],v['job_snapshot'],v['part_snapshot'],json.dumps(v['counts']),v['shift'],v['work_time_seconds'],v['norm_seconds'],datetime.now().isoformat(timespec='seconds')))
                con.commit(); rid=cur.lastrowid; con.close(); return self._json({'ok':True,'id':rid,'norm_seconds_per_item':v['norm_seconds'],'work_time_seconds':v['work_time_seconds']},201)
            except Exception as e:
                try: con.close()
                except: pass
                return self._json({'error':str(e)},400)
        return self._json({'error':'Endpoint neexistuje.'},404)

    def do_PUT(self):
        path,q=self._pathq(); data=self._body(); u=self._auth(admin=True)
        if not u:return
        m=re.fullmatch(r'/api/jobs/(\d+)',path)
        if m:
            try:
                jid=int(m.group(1)); order=str(data.get('order_number','')).strip(); brief=str(data.get('brief_description','')).strip()
                if not order or not brief:raise ValueError('Order number a Brief description sú povinné.')
                norm_mode,norm_ct_seconds=parse_job_norm(data); norm_enabled=1; norm_time=''
                parts=[{'item_number':str(x.get('item_number','')).strip(),'part_name':str(x.get('part_name','')).strip(),'norm_per_hour':float(x.get('norm_per_hour') or 0) if str(x.get('norm_per_hour') or '').strip() else None} for x in (data.get('parts') or []) if str(x.get('item_number','')).strip() or str(x.get('part_name','')).strip()]
                if not parts or any(not x['item_number'] for x in parts):raise ValueError('Pridaj aspoň jedno platné číslo dielu.')
                if any((x.get('norm_per_hour') is not None and x.get('norm_per_hour') <= 0) for x in parts): raise ValueError('Norma ks/h musí byť väčšia ako 0.')
                if norm_mode!='time':
                    for p in parts: p['norm_per_hour']=None
                errors=[str(x).strip() for x in (data.get('errors') or []) if str(x).strip()]
                report_enabled,report_recipients,report_time,report_formats=parse_job_reporting(data)
                con=db(); con.execute('UPDATE jobs SET order_number=?,brief_description=?,norm_enabled=?,norm_time=?,norm_mode=?,norm_ct_seconds=?,active=?,updated_at=?,location_id=?,reporting_enabled=?,reporting_recipients=?,reporting_time=?,reporting_formats=? WHERE id=?',(order,brief,norm_enabled,norm_time,norm_mode,norm_ct_seconds,1 if data.get('active',True) else 0,datetime.now().isoformat(timespec='seconds'),data.get('location_id'),report_enabled,report_recipients,report_time,report_formats,jid))
                # Do not delete definitions referenced by historical records. Reuse matching IDs and deactivate removed definitions.
                old_parts=con.execute('SELECT * FROM job_parts WHERE job_id=?',(jid,)).fetchall(); part_by_num={x['item_number']:x for x in old_parts}
                con.execute('UPDATE job_parts SET active=0 WHERE job_id=?',(jid,))
                for i,p in enumerate(parts):
                    oldp=part_by_num.get(p['item_number'])
                    if oldp: con.execute('UPDATE job_parts SET part_name=?,norm_per_hour=?,sort_order=?,active=1 WHERE id=?',(p['part_name'],p.get('norm_per_hour'),i,oldp['id']))
                    else: con.execute('INSERT INTO job_parts(job_id,item_number,part_name,norm_per_hour,sort_order,active) VALUES(?,?,?,?,?,1)',(jid,p['item_number'],p['part_name'],p.get('norm_per_hour'),i))
                old_errors=con.execute('SELECT * FROM job_errors WHERE job_id=?',(jid,)).fetchall(); err_by_name={x['name']:x for x in old_errors}
                con.execute('UPDATE job_errors SET active=0 WHERE job_id=?',(jid,))
                for i,e in enumerate(errors):
                    olde=err_by_name.get(e)
                    if olde: con.execute('UPDATE job_errors SET sort_order=?,active=1 WHERE id=?',(i,olde['id']))
                    else: con.execute('INSERT INTO job_errors(job_id,name,sort_order,active) VALUES(?,?,?,1)',(jid,e,i))
                con.commit(); job=get_job(con,jid,True); con.close(); return self._json({'job':job})
            except sqlite3.IntegrityError:return self._json({'error':'Číslo objednávky už existuje.'},400)
            except Exception as e:return self._json({'error':str(e)},400)
        m=re.fullmatch(r'/api/users/(\d+)',path)
        if m:
            try:
                uid=int(m.group(1)); display=str(data.get('display_name','')).strip(); role=data.get('role','operator'); password=str(data.get('password','')); active=1 if data.get('active',True) else 0
                if not display or role not in ('admin','operator'):raise ValueError('Meno a rola sú povinné.')
                con=db(); con.execute('UPDATE users SET display_name=?,role=?,active=? WHERE id=?',(display,role,active,uid))
                if password:
                    if len(password)<6:raise ValueError('Heslo musí mať min. 6 znakov.')
                    salt,ph=hash_password(password); con.execute('UPDATE users SET password_salt=?,password_hash=? WHERE id=?',(salt,ph,uid))
                con.commit(); con.close(); return self._json({'ok':True})
            except Exception as e:return self._json({'error':str(e)},400)
        m=re.fullmatch(r'/api/records/(\d+)',path)
        if m:
            try:
                rid=int(m.group(1)); con=db(); existing=record_by_id(con,rid)
                if not existing: con.close(); raise ValueError('Záznam neexistuje.')
                v=prepare_record(con,data,u,True)
                con.execute('''UPDATE records SET job_id=?,part_id=?,record_date=?,delivery_note=?,checked_items=?,ok_items=?,nok_items=?,reworked_ok=?,reworked_nok=?,note=?,job_snapshot=?,part_snapshot=?,error_counts=?,shift=?,work_time_seconds=?,norm_seconds_per_item=? WHERE id=?''',
                    (v['jid'],v['pid'],v['record_date'],v['delivery_note'],v['checked'],v['ok'],v['nok'],v['rwok'],v['rwnok'],v['note'],v['job_snapshot'],v['part_snapshot'],json.dumps(v['counts']),v['shift'],v['work_time_seconds'],v['norm_seconds'],rid))
                con.commit(); con.close(); return self._json({'ok':True,'id':rid,'norm_seconds_per_item':v['norm_seconds'],'work_time_seconds':v['work_time_seconds']})
            except Exception as e:
                try: con.close()
                except: pass
                return self._json({'error':str(e)},400)
        return self._json({'error':'Endpoint neexistuje.'},404)

    def do_DELETE(self):
        path,q=self._pathq(); u=self._auth(admin=True)
        if not u:return
        m=re.fullmatch(r'/api/records/(\d+)',path)
        if m:
            rid=int(m.group(1)); con=db(); con.execute('DELETE FROM records WHERE id=?',(rid,)); con.commit(); con.close(); return self._json({'ok':True})
        m=re.fullmatch(r'/api/jobs/(\d+)',path)
        if m:
            jid=int(m.group(1)); force=(q.get('force',['0'])[0]=='1'); con=db(); used=con.execute('SELECT COUNT(*) c FROM records WHERE job_id=?',(jid,)).fetchone()['c']
            if used and not force:
                con.close(); return self._json({'error':'Zákazka obsahuje záznamy. Najprv ju archivuj, alebo potvrď trvalé vymazanie vrátane všetkých záznamov.'},409)
            if force:
                con.execute('DELETE FROM records WHERE job_id=?',(jid,))
            con.execute('DELETE FROM jobs WHERE id=?',(jid,)); con.commit(); con.close(); return self._json({'ok':True,'deleted_records':used if force else 0})
        return self._json({'error':'Endpoint neexistuje.'},404)


def choose_port():
    for p in range(DEFAULT_PORT,DEFAULT_PORT+20):
        s=socket.socket();
        try:s.bind((HOST,p));s.close();return p
        except OSError:s.close()
    raise RuntimeError('Nenašiel sa voľný lokálny port.')


def main():
    init_db(); port=choose_port(); server=ThreadingHTTPServer((HOST,port),Handler); url=f'http://{HOST}:{port}/'
    print('\nMIELL Quality Reporting V2.4'); print('Open:',url); print('Admin: admin / Admin123!'); print('Operator: operator / Operator123!'); print('Close with CTRL+C.\n')
    try:
        import threading; threading.Timer(1.0,lambda:webbrowser.open(url)).start(); server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
