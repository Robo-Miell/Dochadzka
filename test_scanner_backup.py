from types import SimpleNamespace
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool
from scanner_backup import install
import io
import zipfile

def test_backup_security_retry_and_export(monkeypatch):
    monkeypatch.delenv('RENDER',raising=False)
    app=FastAPI()
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    def admin(authorization: str=Header(default='')):
        if authorization!='Bearer admin-test': raise HTTPException(403,'admin only')
    core=SimpleNamespace(app=app,engine=engine,JWT_SECRET='scanner-test-secret-only',JWT_ALG='HS256',admin_only=admin)
    install(core)
    with TestClient(app) as client:
        assert client.get('/scanner/api/health').json()['durable'] is False
        assert inspect(engine).get_table_names()==['scanner_backups']
        a=client.post('/scanner/api/device').json();b=client.post('/scanner/api/device').json()
        auth={'Authorization':'Bearer '+a['token']};other={'Authorization':'Bearer '+b['token']};root={'Authorization':'Bearer admin-test'}
        row={'id':'sample-1','code':'0001234567890123456789','operator':'Operator A','note':'Paleta A','at':'2026-10-09T12:00:00+02:00','pallet':1,'box':1,'piece':1,'position':1}
        assert client.post('/scanner/api/records',json={'records':[row]}).status_code==401
        assert client.post('/scanner/api/records',headers=root,json={'records':[row]}).status_code==401
        assert client.post('/scanner/api/records',headers=auth,json={'records':[row]}).json()['accepted']==['sample-1']
        assert client.post('/scanner/api/records',headers=auth,json={'records':[row]}).status_code==200
        assert client.post('/scanner/api/records',headers=auth,json={'records':[{**row,'code':'changed'}]}).status_code==409
        assert client.get('/scanner/api/admin/records',headers=auth).status_code==403
        assert client.get('/scanner/api/admin/export').status_code==403
        assert client.post('/scanner/api/records',headers=other,json={'records':[{**row,'operator':'Operator B'}]}).status_code==200
        data=client.get('/scanner/api/admin/records',headers=root).json();assert len(data['records'])==2
        assert client.get('/scanner/api/admin/records?operator=Operator%20A',headers=root).json()['records'][0]['code']==row['code']
        assert len(client.get('/scanner/api/admin/records?operator=Operator%20A',headers=root).json()['records'])==1
        assert client.post('/scanner/api/records',headers=auth,json={'records':[{**row,'id':'bad','position':21}]}).status_code==422
        assert client.post('/scanner/api/records',headers=auth,json={'records':[{**row,'id':'bad','operator':' '}]}).status_code==422
        assert client.post('/scanner/api/records',headers=auth,json={'records':[{**row,'id':'formula','code':'=1+1'}]}).status_code==200
        file=client.get('/scanner/api/admin/export?operator=Operator%20A',headers=root)
        assert file.status_code==200
        with zipfile.ZipFile(io.BytesIO(file.content)) as z:
            assert b'<f>' not in z.read('xl/worksheets/sheet1.xml')
            assert row['code'].encode() in z.read('xl/sharedStrings.xml')
        monkeypatch.setenv('RENDER','true')
        assert client.post('/scanner/api/records',headers=auth,json={'records':[{**row,'id':'ephemeral'}]}).status_code==503
