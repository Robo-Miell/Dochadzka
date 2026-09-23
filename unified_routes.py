from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from quality.integration import legacy, sync_identity


def register(host):
    app = host.app

    # Temporary, administrator-only import for the explicitly requested test dataset.
    @app.get('/admin/test-attendance-2025')
    def test_attendance_page():
        from fastapi.responses import HTMLResponse
        return HTMLResponse('''<!doctype html><html lang="sk"><meta charset="utf-8"><title>Testovacia dochádzka 2025</title>
        <link rel="stylesheet" href="/portal.css"><main><h1>Testovacia dochádzka 2025</h1>
        <p>TEST – Fiktívny zamestnanec. 250 pracovných dní, 06:00–14:00, 8 hodín denne, schválené.
        Dni sa rovnomerne rozdelia medzi existujúce prevádzky. Konto nebude aktívne.</p>
        <button id="import" class="primary">Vložiť schválenú testovaciu dochádzku</button><pre id="result"></pre>
        <a href="/admin">Späť do dochádzky</a><script>
        document.getElementById('import').onclick=async function(){this.disabled=true;const out=document.getElementById('result');out.textContent='Importujem…';try{const r=await fetch('/api/admin/test-attendance-2025',{method:'POST',headers:{Authorization:'Bearer '+(localStorage.getItem('dochadzka_token')||'')}});const d=await r.json();if(!r.ok)throw Error(d.detail||'Import zlyhal');out.textContent=JSON.stringify(d,null,2)}catch(e){out.textContent=e.message;this.disabled=false}};
        </script></main></html>''')

    @app.post('/api/admin/test-attendance-2025')
    def import_test_attendance(session=Depends(host.db), admin=Depends(host.admin_only)):
        from datetime import timedelta
        from collections import Counter
        from sqlalchemy import text
        if session.bind.dialect.name == 'postgresql':
            session.execute(text('SELECT pg_advisory_xact_lock(2025092301)'))
        marker = 'TEST-SEED-2025'
        note = 'TEST – fiktívna dochádzka 2025, nejde o skutočne odpracované hodiny'
        employee = session.scalar(select(host.User).where(host.User.personal_number == marker))
        inserted = 0
        if employee is None:
            if session.scalar(select(host.User.id).where(host.User.login == 'test-fiktivny-2025')):
                raise HTTPException(409, 'Testovací login už používa iný účet.')
            locations = session.scalars(select(host.Location).order_by(host.Location.name, host.Location.id)).all()
            if not locations:
                raise HTTPException(400, 'Nie sú vytvorené prevádzky.')
            employee = host.User(personal_number=marker, name='TEST – Fiktívny zamestnanec',
                login='test-fiktivny-2025', password_hash='!disabled-test-fixture',
                role='employee', active=False, location_id=locations[0].id, locations=locations)
            session.add(employee)
            session.flush()
            # Slovak non-working holidays in 2025; 1 Sep / 17 Nov were working days.
            holidays = {'01-01','01-06','04-18','04-21','05-01','05-08','07-05','08-29','09-15','11-01','12-24','12-25','12-26'}
            day = date(2025, 1, 1)
            while day.year == 2025:
                if day.weekday() < 5 and day.strftime('%m-%d') not in holidays:
                    session.add(host.Attendance(work_date=day, user_id=employee.id,
                        location_id=locations[inserted % len(locations)].id, type='Práca',
                        time_from='06:00', time_to='14:00', break_minutes=0, deduct_break=False,
                        km=0, billing_confirmed=False, note=note, status='approved'))
                    inserted += 1
                day += timedelta(days=1)
            session.flush()
        if employee.name != 'TEST – Fiktívny zamestnanec' or employee.active:
            raise HTTPException(409, 'Testovacie označenie už používa iný účet.')
        rows = session.scalars(select(host.Attendance).where(host.Attendance.user_id == employee.id)).all()
        if len(rows) != 250 or len({r.work_date for r in rows}) != 250 or any(
            r.work_date.year != 2025 or r.note != note or r.status != 'approved'
            or r.time_from != '06:00' or r.time_to != '14:00' or r.deduct_break
            or r.break_minutes != 0 for r in rows):
            raise HTTPException(409, 'Kontrola testovacej sady zlyhala; neboli potvrdené nové zmeny.')
        hours = sum(host.attendance_hours(r) for r in rows)
        distribution = Counter(r.location.name for r in rows)
        session.commit()
        return {'employee': employee.name, 'employee_id': employee.id, 'inserted': inserted,
            'records': len(rows), 'hours': hours, 'status': 'approved', 'locations': dict(distribution)}

    @app.get('/health')
    def health():
        return {'status': 'ok', 'application': 'MIELL Unified'}

    @app.get('/shared.js')
    @app.get('/portal.js')
    @app.get('/portal.css')
    def portal_asset(request: Request):
        return FileResponse(Path(host.static_dir) / request.url.path.lstrip('/'))

    @app.post('/api/auth/logout')
    def logout(user=Depends(host.get_current_user), session=Depends(host.db)):
        # Revoke the shared login in every module (and other active devices).
        user.token_version = int(user.token_version or 0) + 1
        session.commit()
        return {'ok': True}

    @app.get('/api/unified/summary')
    def summary(date_from: date = Query(None), date_to: date = Query(None),
                user=Depends(host.get_current_user), session=Depends(host.db)):
        today = datetime.now(ZoneInfo(host.REPORTING_TIMEZONE)).date()
        start, end = date_from or today, date_to or today
        if start > end:
            raise HTTPException(400, 'Dátum Od nemôže byť neskôr ako Do')
        people = session.scalars(select(host.User).order_by(host.User.name)).all() if user.role == 'admin' else [user]
        identities = {u.id: sync_identity(u) for u in people}
        rows = {u.id: dict(user_id=u.id, name=u.name, approved_hours=0, pending_hours=0,
                    attendance_records=0, checked=0, ok=0, nok=0, quality_hours=0,
                    ct_hours=0, operator_hours=0, quality_records=0, outside_norm=0) for u in people}
        stmt = select(host.Attendance).where(host.Attendance.work_date >= start, host.Attendance.work_date <= end)
        if user.role != 'admin':
            stmt = stmt.where(host.Attendance.user_id == user.id)
        pending = 0
        for a in session.scalars(stmt).all():
            item = rows.get(a.user_id)
            if item is None:
                continue
            item['attendance_records'] += 1
            if a.status == 'pending':
                pending += 1
            if a.type == 'Práca' and a.status in {'approved', 'pending'}:
                item[a.status+'_hours'] += host.attendance_hours(a)
        with legacy.db() as con:
            records = legacy.record_query(con, identities[user.id], {'date_from':[start.isoformat()], 'date_to':[end.isoformat()]})
        reverse = {identity['id']: uid for uid, identity in identities.items()}
        for r in records:
            item = rows.get(reverse.get(r['user_id']))
            if item is None:
                continue
            for target, source in [('checked','checked_items'),('ok','ok_items'),('nok','nok_items')]:
                item[target] += r[source]
            hours = (r.get('work_time_seconds') or 0)/3600
            item['quality_hours'] += hours
            item['ct_hours' if (r.get('job_snapshot_obj') or {}).get('norm_mode') == 'ct' else 'operator_hours'] += hours
            item['quality_records'] += 1
            item['outside_norm'] += int(r.get('norm_outside',False))
        totals = {key: round(sum(row[key] for row in rows.values()),2) for key in next(iter(rows.values())).keys() if key not in {'user_id','name'}}
        for row in rows.values():
            for key in ['approved_hours','pending_hours','quality_hours','ct_hours','operator_hours']:
                row[key] = round(row[key],2)
        return {'date_from':start.isoformat(), 'date_to':end.isoformat(), 'totals':totals, 'people':list(rows.values()), 'pending_records':pending}
