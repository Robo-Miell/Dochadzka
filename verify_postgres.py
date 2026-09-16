"""Run only on an explicitly designated disposable Neon branch."""
import os
import uuid
from datetime import date
from urllib.parse import urlparse

assert os.getenv('MIELL_VERIFY_POSTGRES') == '1', 'Explicit test mode required'
assert urlparse(os.environ['DATABASE_URL']).hostname == 'ep-old-mud-b2p9795p-pooler.c-6.eu-central-1.aws.neon.tech', 'Disposable test branch required'

import main
from fastapi.testclient import TestClient
from sqlalchemy import text

# Compare all original columns and rows before/after startup and API checks.
with main.engine.connect() as con:
    tables = main.inspect(main.engine).get_table_names(schema='public')
    original = {}
    for table in tables:
        cols = [c['name'] for c in main.inspect(main.engine).get_columns(table, schema='public')]
        quote = main.engine.dialect.identifier_preparer.quote
        sql = 'SELECT ' + ','.join(quote(c) for c in cols) + ' FROM public.' + quote(table)
        original[sql] = sorted(map(repr, con.execute(text(sql)).fetchall()))

tag = uuid.uuid4().hex[:10]
with TestClient(main.app) as client:
    with main.SessionLocal() as session:
        admin = session.scalar(main.select(main.User).where(main.User.role == 'admin', main.User.active == True))
        assert admin is not None
        auth = {'Authorization': 'Bearer ' + main.token_for(admin)}
    def call(method, path, expected=200, **kwargs):
        r = getattr(client, method)(path, headers=auth, **kwargs)
        assert r.status_code == expected, (method, path, r.status_code, r.text[:500])
        return r
    loc = call('post', '/api/locations', json={'name':'PG verification '+tag}).json()
    emp = call('post', '/api/users', json={'personal_number':tag,'name':'Test PostgreSQL','login':tag,'password':uuid.uuid4().hex,'location_ids':[loc['id']]}).json()
    payload = {'location_id':loc['id'],'order_number':'PG-'+tag,'brief_description':'Percent 100% ? ľšč','norm_mode':'time','parts':[{'item_number':'A','part_name':'Ľavý','norm_per_hour':120}],'errors':['Škrabanec']}
    job = call('post','/quality/api/jobs',201,json=payload).json()['job']
    call('post','/quality/api/jobs',400,json=payload)
    assert call('get','/quality/api/jobs/'+str(job['id'])).json()['job']['brief_description']==payload['brief_description']
    choices=call('get','/quality/api/employees',params={'location_id':loc['id']}).json()['employees']
    assert [u['id'] for u in choices]==[emp['id']]
    data={'job_id':job['id'],'part_id':job['parts'][0]['id'],'employee_id':emp['id'],'checked_items':140,'ok_items':139,'nok_items':1,'error_counts':{str(job['errors'][0]['id']):1},'shift':'R','operator_time':'1:00','note':'Žltý 100% ?'}
    rid=call('post','/quality/api/records',201,json=data).json()['id']
    row=call('get',f'/quality/api/records/{rid}').json()['record']
    assert row['display_name']==emp['name']
    call('get','/quality/api/dashboard')
    call('get','/api/unified/summary')
    for ext in ['records-pdf','records-xlsx','daily-xlsm']:
        r=call('get','/quality/api/export/'+ext,params={'job_id':job['id'],'date':date.today().isoformat()})
        assert len(r.content)>100
    call('post',f'/quality/api/records/{rid}/archive',json={})
    call('post',f'/quality/api/records/{rid}/restore',json={})
    payload['brief_description']='Updated'
    call('put',f'/quality/api/jobs/{job["id"]}',json=payload)
    main.startup()
    assert call('get',f'/quality/api/records/{rid}').json()['record']['note']==data['note']
    call('delete',f'/quality/api/jobs/{job["id"]}',params={'force':1})
    call('delete',f'/api/users/{emp["id"]}')
    call('delete',f'/api/locations/{loc["id"]}')

with main.engine.connect() as con:
    for sql, before in original.items():
        assert sorted(map(repr,con.execute(text(sql)).fetchall()))==before, 'Original attendance data changed'
print('POSTGRES_VERIFIED: startup, original data preserved, jobs, duplicate handling, employee attribution, reports, archive, edit, restart and cleanup',flush=True)
