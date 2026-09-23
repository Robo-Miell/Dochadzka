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
    for text in ['skraba','000456','00123','POZNAMKA']:
        rows = legacy.record_query(con,op,{'search':[text]})
        assert [r['id'] for r in rows] == [1]
    assert legacy.record_query(con,op,{'search':['skraba'],'shift':['N']}) == []
    assert legacy.record_query(con,op,{'search':["' OR 1=1 --"]}) == []
    con.close()


def test_seed_is_admin_only_atomic_and_idempotent():
    with TestClient(main.app) as client:
        assert client.post('/api/admin/test-attendance-2025').status_code == 401
        token = client.post('/api/auth/login',json={'login':'admin','password':'PortalTest123!'}).json()['access_token']
        headers = {'Authorization':'Bearer '+token}
        for name in ['Seed A','Seed B','Seed C']:
            assert client.post('/api/locations',headers=headers,json={'name':name}).status_code == 200
        result = client.post('/api/admin/test-attendance-2025',headers=headers)
        assert result.status_code == 200, result.text
        data = result.json()
        assert data['inserted'] == data['records'] == 250
        assert data['hours'] == 2000
        counts = list(data['locations'].values())
        assert max(counts)-min(counts) <= 1
        again = client.post('/api/admin/test-attendance-2025',headers=headers).json()
        assert again['inserted'] == 0 and again['records'] == 250
        with main.SessionLocal() as session:
            assert session.get(main.User,data['employee_id']).active is False
