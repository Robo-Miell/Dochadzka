"""Append-only scanner backups, isolated from CRM and attendance tables."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID
import io
import os
import secrets
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, select
from sqlalchemy.exc import IntegrityError
from jose import jwt, JWTError
import xlsxwriter

class Scan(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=20000)
    operator: str = Field(min_length=1, max_length=120)
    note: str = Field(default='', max_length=1000)
    at: datetime
    pallet: Optional[int] = Field(default=None, ge=1, le=1000000000)
    box: Optional[int] = Field(default=None, ge=1, le=16)
    piece: Optional[int] = Field(default=None, ge=1, le=20)
    position: Optional[int] = Field(default=None, ge=1, le=320)
    @field_validator('code', 'operator')
    @classmethod
    def nonempty(cls, value):
        if not value.strip(): raise ValueError('Prázdny údaj')
        return value
    @field_validator('at')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None: raise ValueError('Čas musí obsahovať časové pásmo')
        return value

class Batch(BaseModel):
    records: list[Scan] = Field(min_length=1, max_length=100)

def install(core):
    router = APIRouter(prefix='/scanner')
    metadata = MetaData()
    scans = Table('scanner_backups', metadata,
        Column('id', String(80), primary_key=True),
        Column('device', String(36), primary_key=True),
        Column('operator', String(120), nullable=False, index=True),
        Column('code', Text, nullable=False), Column('note', Text, nullable=False),
        Column('at', String(40), nullable=False, index=True),
        Column('received_at', String(40), nullable=False),
        Column('pallet', Integer), Column('box', Integer),
        Column('piece', Integer), Column('position', Integer))
    def durable():
        return core.engine.dialect.name == 'postgresql'
    @core.app.on_event('startup')
    def setup():
        metadata.create_all(core.engine)
    @router.get('/api/health')
    def health():
        with core.engine.connect() as con: con.execute(select(scans.c.id).limit(1))
        return {'status':'ok', 'durable':durable(), 'storage':core.engine.dialect.name, 'version':1}
    @router.post('/api/device')
    def device():
        identifier=str(UUID(bytes=secrets.token_bytes(16), version=4))
        token=jwt.encode({'sub':identifier,'aud':'scanner-backup','kind':'scanner-device'},core.JWT_SECRET,algorithm=core.JWT_ALG)
        return {'device':identifier,'token':token}
    def authenticated_device(authorization: str = Header(default='')):
        try:
            scheme,token=authorization.split(' ',1)
            if scheme.lower()!='bearer': raise ValueError()
            payload=jwt.decode(token,core.JWT_SECRET,algorithms=[core.JWT_ALG],audience='scanner-backup')
            if payload.get('kind')!='scanner-device':raise ValueError()
            return str(UUID(payload['sub']))
        except (JWTError,ValueError,KeyError):raise HTTPException(401,'Neplatná identita zariadenia')
    @router.post('/api/records')
    def receive(data: Batch, device: str=Depends(authenticated_device)):
        if os.getenv('RENDER') and not durable():
            raise HTTPException(503,'Server nemá pripojenú trvalú databázu; skeny zostávajú v mobile.')
        accepted=[]
        # Each acknowledged ID has its own committed transaction. Retries are safe.
        for row in data.records:
            values=row.model_dump(); values['at']=row.at.astimezone(timezone.utc).isoformat()
            values.update(device=device,received_at=datetime.now(timezone.utc).isoformat())
            if row.position is not None and (row.box!=(row.position-1)//20+1 or row.piece!=(row.position-1)%20+1):
                raise HTTPException(422,'Nesúhlasí poradie dielu a boxu')
            try:
                with core.engine.begin() as con: con.execute(scans.insert().values(**values))
            except IntegrityError:
                with core.engine.connect() as con:
                    existing=con.execute(select(scans).where(scans.c.id==row.id,scans.c.device==device)).mappings().first()
                if not existing or any(existing[key]!=values[key] for key in ('operator','code','note','at','pallet','box','piece','position')):
                    raise HTTPException(409,'ID záznamu už obsahuje odlišné dáta; pôvodná záloha zostala zachovaná.')
            accepted.append(row.id)
        return {'accepted':accepted,'durable':durable()}
    def filtered(operator='', pallet=None, since='', until=''):
        query=select(scans)
        if operator:query=query.where(scans.c.operator==operator)
        if pallet is not None:query=query.where(scans.c.pallet==pallet)
        if since:query=query.where(scans.c.at>=since+'T00:00:00')
        if until:query=query.where(scans.c.at<=until+'T23:59:59.999999+00:00')
        return query
    @router.get('/api/admin/records')
    def overview(operator: str='', pallet: Optional[int]=None, since: str='', until: str='',
                 offset: int=Query(0,ge=0), limit: int=Query(200,ge=1,le=1000), _=Depends(core.admin_only)):
        with core.engine.connect() as con:
            rows=con.execute(filtered(operator,pallet,since,until).order_by(scans.c.received_at.desc(),scans.c.id).offset(offset).limit(limit+1)).mappings().all()
        return {'records':[dict(r) for r in rows[:limit]],'more':len(rows)>limit}
    @router.get('/api/admin/export')
    def export(operator: str='', pallet: Optional[int]=None, since: str='', until: str='', _=Depends(core.admin_only)):
        output=io.BytesIO()
        book=xlsxwriter.Workbook(output,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
        sheet=book.add_worksheet('Skeny');header=book.add_format({'bold':True,'bg_color':'#DCEBDD'})
        fields=['operator','device','pallet','box','piece','position','code','at','note','received_at']
        sheet.write_row(0,0,['Používateľ','Zariadenie','Paleta','Box','Diel v boxe','Diel na palete','Kód','Čas skenu UTC','Poznámka','Prijaté UTC'],header)
        with core.engine.connect() as con:
            for i,row in enumerate(con.execute(filtered(operator,pallet,since,until).order_by(scans.c.received_at)).mappings(),1):
                sheet.write_row(i,0,[row[f] for f in fields])
        sheet.set_column(0,1,24);sheet.set_column(2,5,16);sheet.set_column(6,9,32);sheet.freeze_panes(1,0);sheet.autofilter(0,0,sheet.dim_rowmax or 0,9)
        book.close();output.seek(0)
        return StreamingResponse(output,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="skeny-server.xlsx"'})
    @router.get('/admin')
    def admin_page():return FileResponse(Path(__file__).with_name('scanner_admin.html'))
    core.app.include_router(router)
