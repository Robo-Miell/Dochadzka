"""Transactional attendance audit; no public write/delete endpoints."""
import json
import uuid
from datetime import datetime
from sqlalchemy import Table, Column, String, Text, Integer, event, select
from sqlalchemy.orm import object_session
from fastapi import Depends, Query


def install(host):
    from fastapi.responses import FileResponse
    from pathlib import Path
    @host.app.get('/history.js')
    def history_script():return FileResponse(Path(__file__).parent / 'history.js')
    table = Table('attendance_audit',host.Base.metadata,
        Column('id',String(36),primary_key=True),Column('record_id',Integer,index=True,nullable=False),
        Column('at',String(40),nullable=False),Column('actor',Text,nullable=False),
        Column('action',String(20),nullable=False),Column('before_data',Text,nullable=False),Column('after_data',Text,nullable=False))
    def write(connection, obj, action, before, after):
        before=json.loads(json.dumps(before,default=str));after=json.loads(json.dumps(after,default=str))
        if before==after:return
        session=object_session(obj)
        actor=session.info.get('audit_actor',{'id':None,'name':'Systém','login':''}) if session else {'id':None,'name':'Systém','login':''}
        connection.execute(table.insert().values(id=str(uuid.uuid4()),record_id=obj.id,at=datetime.utcnow().isoformat()+'Z',actor=json.dumps(actor,ensure_ascii=False),action=action,before_data=json.dumps(before,ensure_ascii=False),after_data=json.dumps(after,ensure_ascii=False)))
    def snapshot(obj):return {c.name:getattr(obj,c.name) for c in host.Attendance.__table__.columns}
    @event.listens_for(host.Attendance,'after_insert')
    def created(mapper,connection,obj):write(connection,obj,'create',{},snapshot(obj))
    @event.listens_for(host.Attendance,'before_update')
    def updated(mapper,connection,obj):
        before=connection.execute(select(host.Attendance.__table__).where(host.Attendance.id==obj.id)).mappings().first()
        if before:write(connection,obj,'update',dict(before),snapshot(obj))
    @event.listens_for(host.Attendance,'before_delete')
    def deleted(mapper,connection,obj):write(connection,obj,'delete',snapshot(obj),{})
    @host.app.get('/api/attendance-history')
    def history(record_id:int=Query(None),session=Depends(host.db),user=Depends(host.admin_only)):
        stmt=select(table)
        if record_id is not None:stmt=stmt.where(table.c.record_id==record_id)
        rows=session.execute(stmt.order_by(table.c.at.desc()).limit(500)).mappings().all()
        return {'history':[{'id':r['id'],'record_id':r['record_id'],'at':r['at'],'actor':json.loads(r['actor']),'action':r['action'],'before':json.loads(r['before_data']),'after':json.loads(r['after_data'])} for r in rows]}
