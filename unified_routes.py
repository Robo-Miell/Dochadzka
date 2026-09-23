from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from quality.integration import legacy, sync_identity


def register(host):
    app = host.app

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
