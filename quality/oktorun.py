"""Persisted OKtoRUN gate and retryable notification outbox."""
import json
import uuid
from pathlib import Path
from datetime import datetime
from fastapi import HTTPException
from . import legacy
from .storage import database_url

QUESTIONS=json.loads((Path(__file__).with_name('oktorun_questions.json')).read_text(encoding='utf-8'))
REVISION='MQSK-FR-8.5-09 Rev-02'

def initialize():
    with legacy.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS oktorun_state (user_id INTEGER PRIMARY KEY,job_id INTEGER NOT NULL,scope TEXT NOT NULL,generation TEXT NOT NULL,approval_id TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS oktorun_checks (id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,job_id INTEGER NOT NULL,generation TEXT NOT NULL,created_at TEXT NOT NULL,actor TEXT NOT NULL,job_label TEXT NOT NULL,questions TEXT NOT NULL,answers TEXT NOT NULL,passed INTEGER NOT NULL,notice_sent_at TEXT,notice_error TEXT)')
        con.execute('CREATE INDEX IF NOT EXISTS oktorun_checks_job ON oktorun_checks(job_id)')
        if 'oktorun_id' not in legacy.table_columns(con,'records'):
            con.execute('ALTER TABLE records ADD COLUMN oktorun_id TEXT')

def lock_state(con,uid):
    if not database_url() and not con.in_transaction:con.execute('BEGIN IMMEDIATE')
    return con.execute('SELECT * FROM oktorun_state WHERE user_id=?'+(' FOR UPDATE' if database_url() else ''),(uid,)).fetchone()

def start(identity,jid,scope):
    with legacy.db() as con:
        # Insert first so simultaneous first requests also serialize on the user row.
        con.execute('INSERT INTO oktorun_state(user_id,job_id,scope,generation) VALUES(?,?,?,?) ON CONFLICT(user_id) DO NOTHING',(identity['id'],jid,scope,str(uuid.uuid4())))
        state=lock_state(con,identity['id'])
        if state['job_id']!=jid or state['scope']!=scope:
            con.execute('UPDATE oktorun_state SET job_id=?,scope=?,generation=?,approval_id=NULL WHERE user_id=?',(jid,scope,str(uuid.uuid4()),identity['id']))
            state=lock_state(con,identity['id'])
        return {'generation':state['generation'],'approved':bool(state['approval_id']),'questions':QUESTIONS,'revision':REVISION}

def submit(identity,jid,scope,payload):
    answers=payload.get('answers')
    if not isinstance(answers,dict) or set(answers)!={q['id'] for q in QUESTIONS} or any(type(v) is not bool for v in answers.values()):
        raise HTTPException(400,'Odpovedz ÁNO alebo NIE na všetkých 13 otázok.')
    with legacy.db() as con:
        state=lock_state(con,identity['id'])
        if not state or state['job_id']!=jid or state['scope']!=scope or state['generation']!=payload.get('generation'):
            raise HTTPException(409,'Zákazka sa zmenila. Otvor formulár OKtoRUN znova.')
        if state['approval_id']:
            return {'passed':True,'id':state['approval_id']}
        # Retry of the same failed form is idempotent. A deliberate new attempt gets a new generation.
        prior=con.execute('SELECT id,passed FROM oktorun_checks WHERE user_id=? AND generation=?',(identity['id'],state['generation'])).fetchone()
        if prior:return {'passed':bool(prior['passed']),'id':prior['id']}
        jidrow=legacy.get_job(con,jid,True)
        checkid=str(uuid.uuid4());passed=all(answers.values())
        con.execute('INSERT INTO oktorun_checks(id,user_id,job_id,generation,created_at,actor,job_label,questions,answers,passed) VALUES(?,?,?,?,?,?,?,?,?,?)',(checkid,identity['id'],jid,state['generation'],datetime.utcnow().isoformat()+'Z',json.dumps(identity,ensure_ascii=False),jidrow['order_number'],json.dumps({'revision':REVISION,'items':QUESTIONS},ensure_ascii=False),json.dumps(answers),int(passed)))
        con.execute('UPDATE oktorun_state SET approval_id=? WHERE user_id=?',(checkid if passed else None,identity['id']))
        return {'passed':passed,'id':checkid}

def retry(identity,jid,scope,generation):
    with legacy.db() as con:
        state=lock_state(con,identity['id'])
        if not state or state['job_id']!=jid or state['scope']!=scope or state['generation']!=generation:
            raise HTTPException(409,'Zákazka sa zmenila. Vyber ju znova.')
        con.execute('UPDATE oktorun_state SET generation=?,approval_id=NULL WHERE user_id=?',(str(uuid.uuid4()),identity['id']))
    return start(identity,jid,scope)

def require_approval(con,identity,jid):
    state=lock_state(con,identity['id'])
    if not state or state['job_id']!=jid or state['scope']!=identity.get('_oktorun_scope') or not state['approval_id']:
        raise ValueError('Pred zadaním výsledkov vyplň OKtoRUN pre túto zákazku. Pri odpovedi NIE kontaktuj nadriadeného.')
    return state['approval_id']

def send_due(host,lock,check_id=None):
    sent,errors=[],[]
    with legacy.db() as con:
        ids=[r[0] for r in con.execute('SELECT id FROM oktorun_checks WHERE passed=0 AND notice_sent_at IS NULL'+(' AND id=?' if check_id else ''),(check_id,) if check_id else ()).fetchall()]
    for cid in ids:
        try:
            with lock,legacy.db() as con:
                if not database_url():con.execute('BEGIN IMMEDIATE')
                row=con.execute('SELECT * FROM oktorun_checks WHERE id=?'+(' FOR UPDATE' if database_url() else ''),(cid,)).fetchone()
                if not row or row['notice_sent_at']:continue
                job=legacy.get_job(con,row['job_id'],True)
                with host.SessionLocal() as session:
                    manager=session.get(host.User,job.get('project_manager_id')) if job and job.get('project_manager_id') else None
                    if not manager or not manager.active or manager.role!='admin' or not manager.email:
                        raise ValueError('Zákazka nemá aktívneho Project Managera s e-mailom. Doplň ho v nastavení zákazky.')
                    recipient=manager.email
                actor=json.loads(row['actor']);answers=json.loads(row['answers']);qs=json.loads(row['questions'])['items']
                no='\n'.join(q['id']+'. '+q['text'] for q in qs if not answers[q['id']])
                body=f"Operátor: {actor['display_name']} ({actor['username']})\nZákazka: {row['job_label']}\nČas (UTC): {row['created_at']}\n\nOKtoRUN nevyhovuje. Zadávanie výsledkov bolo zablokované a operátor bol vyzvaný kontaktovať nadriadeného.\n\nOdpovede NIE:\n{no}"
                host.microsoft_graph_send_email(f"MIELL OKtoRUN - NIE - {row['job_label']}",body,[recipient],[])
                con.execute('UPDATE oktorun_checks SET notice_sent_at=?,notice_error=NULL WHERE id=?',(datetime.utcnow().isoformat()+'Z',cid));sent.append(cid)
        except Exception as exc:
            with legacy.db() as con:con.execute('UPDATE oktorun_checks SET notice_error=? WHERE id=?',(str(exc)[:1000],cid))
            errors.append({'module':'oktorun','check_id':cid,'error':str(exc)})
    return {'sent':sent,'errors':errors}
