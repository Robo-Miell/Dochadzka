"""Routing regression: isolated storage, no startup jobs or external services."""
import os
import tempfile
from pathlib import Path

_data = tempfile.TemporaryDirectory(prefix='miell_portal_test_')
os.environ['MIELL_DATA_DIR'] = _data.name
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(_data.name) / 'attendance.db').as_posix()
os.environ['JWT_SECRET'] = 'portal-routing-test-only'
os.environ['ADMIN_PASSWORD'] = 'PortalTest123!'

from fastapi.testclient import TestClient
import main


def teardown_module():
    main.engine.dispose()
    # Legacy SQLite handlers can leave connections pending garbage collection.
    import gc
    gc.collect()
    _data.cleanup()


def test_portal_and_attendance_routes():
    client = TestClient(main.app)
    for path in ['/', '/?view=attendance', '/?view=overview']:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/html')
        assert 'id="loginPanel"' in response.text
        assert '/portal.js' in response.text
    assert client.get('/admin').headers['content-type'].startswith('text/html')
    script = client.get('/portal.js')
    assert script.status_code == 200
    assert "location.replace('/admin')" in script.text
    assert client.get('/api/me').status_code == 401


def test_scheduled_reporting_failure_and_overlap(monkeypatch):
    monkeypatch.setattr(main, 'REPORTING_JOB_SECRET', 'test-scheduler-secret')
    calls = []
    def failed(session):
        calls.append(True)
        return {'ok': False, 'errors': [{'error': 'Simulated delivery failure'}]}
    monkeypatch.setattr(main, '_run_due_reporting', failed)
    client = TestClient(main.app)
    url = '/api/reporting/run-due'
    headers = {'X-Reporting-Secret': 'test-scheduler-secret'}
    assert client.post(url).status_code == 401
    assert not calls
    response = client.post(url, headers=headers)
    assert response.status_code == 500 and response.json()['ok'] is False
    assert not main._reporting_run_lock.locked()
    with main._reporting_run_lock:
        response = client.post(url, headers=headers)
        assert response.status_code == 200 and response.json()['running'] is True
    assert len(calls) == 1
    def unexpected(session):
        raise RuntimeError('Unexpected failure')
    monkeypatch.setattr(main, '_run_due_reporting', unexpected)
    client = TestClient(main.app, raise_server_exceptions=False)
    assert client.post(url, headers=headers).status_code == 500
    assert not main._reporting_run_lock.locked()
    monkeypatch.setattr(main, '_run_due_reporting', lambda session: {'ok': True})
    assert client.post(url, headers=headers).json() == {'ok': True}


def test_attendance_pdf_slovak_glyphs():
    import io
    from datetime import date
    from types import SimpleNamespace
    from pypdf import PdfReader
    main.ensure_pdf_fonts()
    for name in ['MiellSans', 'MiellSansBold']:
        glyphs = main.pdfmetrics.getFont(name).face.charToGlyph
        assert all(glyphs.get(ord(c), 0) for c in 'áäčďéíĺľňóôŕšťúýžÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ')
    row = SimpleNamespace(work_date=date(2025,1,2),user=SimpleNamespace(personal_number='TEST',name='Ľubomír Šťastný'),
        location=SimpleNamespace(name='ZKW Topoľčany'),type='Práca',time_from='06:00',time_to='14:00',
        break_minutes=0,deduct_break=False,km=0,billing_confirmed=False,status='approved',note='Ľľ Ĺĺ Čč Ďď Ňň Ťť')
    data = main.build_admin_pdf([row],date(2025,1,1),date(2025,12,31),'Ľubomír Šťastný','ZKW Topoľčany')
    text = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
    assert 'ZKW Topoľčany' in text and 'Ľubomír Šťastný' in text
    out = Path('tmp/pdfs'); out.mkdir(parents=True,exist_ok=True)
    (out/'slovak-font-check.pdf').write_bytes(data)


def test_roles_and_operator_cannot_edit_records():
    with TestClient(main.app) as client:
        def auth(login, password):
            r = client.post('/api/auth/login', json=dict(login=login, password=password))
            assert r.status_code == 200, r.text
            return {'Authorization': 'Bearer ' + r.json()['access_token']}
        admin = auth('admin', 'PortalTest123!')
        loc = client.post('/api/locations', headers=admin, json={'name': 'Test location'}).json()['id']
        def create(name, role):
            return client.post('/api/users', headers=admin, json=dict(personal_number=name, name=name, login=name, password='TestUser123!', location_ids=[loc], role=role))
        assert create('invalid', 'owner').status_code == 422
        created = create('second-admin', 'admin')
        assert created.status_code == 200, created.text
        second = auth('second-admin', 'TestUser123!')
        assert client.get('/api/users', headers=second).status_code == 200
        operator = create('operator-test', 'employee')
        assert operator.status_code == 200
        op = auth('operator-test', 'TestUser123!')
        assert client.post('/api/users', headers=op, json=dict(personal_number='hack', name='hack', login='hack', password='TestUser123!', role='admin')).status_code == 403
        assert client.patch('/api/users/'+str(operator.json()['id']), headers=op, json={'role': 'admin'}).status_code == 403
        record = client.post('/api/attendance', headers=admin, json=dict(user_id=operator.json()['id'], work_date='2026-09-01', location_id=loc, type='Práca', time_from='08:00', time_to='16:00'))
        assert record.status_code == 200, record.text
        rid = record.json()['id']
        assert client.patch(f'/api/attendance/{rid}', headers=op, json={'note':'changed'}).status_code == 403
        assert client.delete(f'/api/attendance/{rid}', headers=op).status_code == 403
        assert client.patch('/quality/api/records/1', headers=op, json={}).status_code in (404,405)
        assert client.put('/quality/api/records/1', headers=op, json={}).status_code == 403
        own = client.get('/api/me', headers=admin).json()['id']
        assert client.patch(f'/api/users/{own}', headers=admin, json={'role':'employee'}).status_code == 409
        assert client.patch('/api/users/'+str(created.json()['id']), headers=admin, json={'role':'employee'}).status_code == 200
        assert client.get('/api/users', headers=second).status_code == 401


def test_quality_job_access_follows_assigned_locations():
    from quality import legacy
    with TestClient(main.app) as client:
        def auth(login, password):
            response = client.post('/api/auth/login', json={'login':login,'password':password})
            assert response.status_code == 200
            return {'Authorization':'Bearer '+response.json()['access_token']}
        admin = auth('admin','PortalTest123!')
        lids = [client.post('/api/locations',headers=admin,json={'name':f'Access site {i}'}).json()['id'] for i in range(3)]
        operator = client.post('/api/users',headers=admin,json=dict(personal_number='access-op',name='Access test',login='access-op',password='AccessTest123!',location_ids=lids[:2],role='employee'))
        assert operator.status_code == 200, operator.text
        op = auth('access-op','AccessTest123!')
        jobs = []
        for i,lid in enumerate(lids):
            response = client.post('/quality/api/jobs',headers=admin,json=dict(order_number=f'ACCESS-{i}',brief_description='Access test',location_id=lid,norm_mode='ct',norm_ct_seconds=1,parts=[{'item_number':f'PART-{i}'}]))
            assert response.status_code == 201, response.text
            jobs.append(response.json()['job'])
        def ids(headers, suffix=''):
            return {j['id'] for j in client.get('/quality/api/jobs'+suffix,headers=headers).json()['jobs']}
        assert ids(op)=={jobs[0]['id'],jobs[1]['id']}
        assert ids(op,'?all=1')==ids(op)
        assert {j['id'] for j in jobs} <= ids(admin,'?all=1')
        def submit(job, headers=op):
            return client.post('/quality/api/records',headers=headers,json=dict(job_id=job['id'],part_id=job['parts'][0]['id'],checked_items=1,ok_items=1,nok_items=0,reworked_ok=0,reworked_nok=0,shift='R'))
        assert submit(jobs[0]).status_code == 201
        assert submit(jobs[0],admin).status_code == 201
        analytics_url=f"/quality/api/jobs/{jobs[0]['id']}/analytics"
        mine=client.get(analytics_url,headers=op)
        assert mine.status_code==200,mine.text
        assert mine.json()['total']['checked']==1
        assert client.get(analytics_url,headers=admin).json()['total']['checked']==2
        assert client.get(analytics_url).status_code==401
        assert client.get(f"/quality/api/jobs/{jobs[2]['id']}/analytics",headers=op).status_code==403
        assert client.get(analytics_url+'?part_id=999999',headers=op).status_code==400
        from pypdf import PdfReader
        import io,zipfile
        pdf=client.get(f"/quality/api/export/pdf?analytics=1&job_id={jobs[0]['id']}",headers=op)
        assert pdf.status_code==200,pdf.text if pdf.status_code!=200 else ''
        assert 'Iba moje záznamy' in ''.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        xlsx=client.get(f"/quality/api/export/xlsx?analytics=1&job_id={jobs[0]['id']}",headers=op)
        assert xlsx.status_code==200
        assert zipfile.is_zipfile(io.BytesIO(xlsx.content))
        assert submit(jobs[2]).status_code == 403
        with legacy.db() as con:
            con.execute('UPDATE jobs SET location_id=NULL WHERE id=?',(jobs[1]['id'],))
            con.commit()
        con.close()
        assert ids(op)=={jobs[0]['id']}
        assert submit(jobs[1]).status_code == 403
        # Revoking an assignment also blocks a form that was already opened.
        response=client.patch('/api/users/'+str(operator.json()['id']),headers=admin,json={'location_ids':[lids[2]]})
        assert response.status_code==200,response.text
        op=auth('access-op','AccessTest123!')
        assert ids(op)=={jobs[2]['id']}
        assert submit(jobs[0],op).status_code==403
        assert client.post(f"/quality/api/jobs/{jobs[2]['id']}/archive",headers=admin,json={}).status_code==200
        assert ids(op,'?all=1')==set()
        assert submit(jobs[2],op).status_code==400


def test_quality_search_respects_owner_and_filters():
    from quality import legacy
    import sqlite3
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript('''
    CREATE TABLE users(id INTEGER, display_name TEXT, central_login TEXT, username TEXT, role TEXT);
    CREATE TABLE jobs(id INTEGER, order_number TEXT, active INTEGER);
    CREATE TABLE records(id INTEGER, user_id INTEGER, job_id INTEGER, part_id INTEGER,
      record_date TEXT, shift TEXT, archived INTEGER, job_snapshot TEXT, part_snapshot TEXT,
      error_counts TEXT, delivery_note TEXT, note TEXT, checked_items INTEGER, ok_items INTEGER,
      nok_items INTEGER, reworked_ok INTEGER, reworked_nok INTEGER, work_time_seconds INTEGER,
      norm_seconds_per_item REAL);
    INSERT INTO users VALUES(1,'Jozef',NULL,'jozef','operator'),(2,'Other',NULL,'other','operator');
    INSERT INTO jobs VALUES(1,'JOB-A',1);
    ''')
    import json
    for rid, uid in [(1,1),(2,2)]:
        con.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
          (rid,uid,1,1,'2026-09-23','R',0,json.dumps({'errors':[{'id':1,'name':'Škrabanec'}]}),
           json.dumps({'item_number':'00123','part_name':'Diel'}),'{"1":3}','DL-000456','Poznámka',10,7,3,0,0,3600,None))
    op = {'role':'operator','id':1}
    detail_filters = {'job_id':['1'], 'date_from':['2026-09-01'], 'date_to':['2026-09-24'], 'operator_id':['2']}
    assert [r['id'] for r in legacy.record_query(con,op,detail_filters)] == [1]
    assert legacy.record_query(con,op,{'job_id':['2']}) == []
    for text in ['skraba','000456','00123','POZNAMKA']:
        rows = legacy.record_query(con,op,{'search':[text]})
        assert [r['id'] for r in rows] == [1]
    assert legacy.record_query(con,op,{'search':['skraba'],'shift':['N']}) == []
    assert legacy.record_query(con,op,{'search':["' OR 1=1 --"]}) == []
    con.close()
