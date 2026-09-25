import io
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from quality import analytics


def record(day, checked=100, nok=3, part=1, name='Škrabanec', archived=0):
    return dict(record_date=day, checked_items=checked, ok_items=checked-nok, nok_items=nok,
                part_id=part, archived=archived, part_snapshot_obj={'item_number':'Diel '+str(part)},
                job_snapshot_obj={'errors':[{'id':1,'name':name}]},error_counts_obj={'1':nok})


JOB=dict(id=1,order_number='DEMO-COAVIS',brief_description='Kontrola dielov',parts=[{'id':1,'item_number':'Diel 1'}],errors=[{'id':1,'name':'Škrabanec'}])


def test_boundaries_totals_zero_days_and_historic_errors():
    records=[record('2026-08-26',50,2),record('2026-08-27',100,5,name='Starý názov'),record('2026-09-25',200,10),record('2026-09-26',500,20),record('2026-09-01',800,30,archived=1)]
    d=analytics.build(JOB,records,date(2026,9,25),'Test')
    assert d['total']['checked']==350 and d['total']['nok']==17
    assert d['recent']['checked']==300 and d['recent']['nok']==15
    assert d['total']['rate']==17/350*100
    assert len(d['days'])==30 and d['days'][0]['date']=='2026-09-25' and d['days'][-1]['date']=='2026-08-27'
    assert d['days'][1]['rate'] is None
    assert 'Starý názov' in d['errors']
    assert d['cumulative'][-1]['checked']==350
    assert analytics.pareto(d['total'])[-1][2]==100
    assert analytics.build(JOB,records,date(2026,9,25),'Test',part_id=1)['total']==d['total']
    empty=analytics.build(JOB,[],date(2026,3,1),'Test')
    assert empty['start']=='2026-01-31' and empty['total']['rate'] is None


def test_exports_and_sample():
    from pypdf import PdfReader
    records=[]
    for i in range(30):
        day=date(2026,8,27)+timedelta(days=i)
        if day.weekday()<5:
            r=record(day.isoformat(),1200+i*10,20)
            r['job_snapshot_obj']['errors']=[{'id':j,'name':n} for j,n in enumerate(['Škrabanec','Otrep','Deformácia','Nečistota'],1)]
            r['error_counts_obj']={'1':10,'2':5,'3':3,'4':2}
            records.append(r)
    records.append(record('2026-01-03',150000,4000))
    d=analytics.build(JOB,records,date(2026,9,25),'Celá zákazka / administrátor','ZKW Topoľčany')
    payload=analytics.export_pdf(d)
    reader=PdfReader(io.BytesIO(payload))
    text=''.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)==3
    assert 'Topoľčany' in text and 'Škrabanec' in text and 'Súčet 30 dní' in text
    xlsx=analytics.export_xlsx(d)
    with zipfile.ZipFile(io.BytesIO(xlsx)) as z:
        assert len([n for n in z.namelist() if n.startswith('xl/charts/chart') and n.endswith('.xml')])==5
        for name in z.namelist():
            if name.endswith('.xml'): ET.fromstring(z.read(name))
    for svg in analytics.svg_charts(d).values():ET.fromstring(svg)
    out=Path('tmp/analytics');out.mkdir(parents=True,exist_ok=True)
    (out/'sample.pdf').write_bytes(payload);(out/'sample.xlsx').write_bytes(xlsx)
    # Wide and empty reports must still render with all defect names retained in tables.
    wide=dict(d,errors=['Veľmi dlhý názov chyby '+str(i) for i in range(13)])
    assert len(PdfReader(io.BytesIO(analytics.export_pdf(wide))).pages)>=6
    empty=analytics.build(JOB,[],date(2026,9,25),'Iba moje záznamy')
    assert analytics.export_pdf(empty).startswith(b'%PDF')
