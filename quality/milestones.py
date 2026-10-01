"""Job completion warnings and retryable project-manager notifications."""
from datetime import date
from fastapi import HTTPException
from . import legacy
from .storage import database_url


def validate(payload, previous, host, session):
    merged = {**previous, **payload}
    for key in ('project_manager_id', 'piece_limit'):
        value = merged.get(key)
        if value in (None, ''):
            value = None
        elif isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0 or int(value) > 2147483647:
            raise HTTPException(400, 'Limit kusov a Project Manager musia byť platné kladné celé čísla')
        else:
            value = int(value)
        payload[key] = value
    end = merged.get('end_date') or None
    try:
        if end and date.fromisoformat(end).isoformat() != end:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(400, 'Neplatný dátum ukončenia')
    payload['end_date'] = end
    manager = session.get(host.User, payload['project_manager_id']) if payload['project_manager_id'] else None
    if payload['project_manager_id'] and (not manager or not manager.active or manager.role != 'admin'):
        raise HTTPException(400, 'Project Manager musí byť aktívny administrátor')
    if payload['piece_limit'] or end:
        if not manager or not manager.email:
            raise HTTPException(400, 'Pre upozornenia vyber Project Managera s e-mailom v Dochádzke → Zamestnanci')


def progress(job, today):
    checked = int(job.get('checked_total') or 0)
    limit = job.get('piece_limit')
    days = (date.fromisoformat(job['end_date']) - today).days if job.get('end_date') else None
    messages = []
    if limit and checked * 10 >= limit * 9:
        messages.append(f"Skontrolovaných {checked} z {limit} ks. Zostáva skontrolovať {max(0,limit-checked)} ks." + (' Limit bol dosiahnutý alebo prekročený.' if checked >= limit else ''))
    if days is not None and days <= 7:
        messages.append(f"Termín ukončenia: {job['end_date']}. " + (f'Zostáva {days} dní.' if days > 0 else 'Zákazka končí dnes.' if days == 0 else f'Termín uplynul pred {-days} dňami.'))
    return {'checked_total':checked,'piece_limit':limit,'remaining':max(0,limit-checked) if limit else None,'end_date':job.get('end_date'),'days_remaining':days,'messages':messages}


def send_due(host, today, lock):
    sent, errors = [], []
    with lock, legacy.db() as con:
        ids = [r[0] for r in con.execute('SELECT id FROM jobs WHERE active=1 AND project_manager_id IS NOT NULL AND (piece_limit IS NOT NULL OR end_date IS NOT NULL)').fetchall()]
    for jid in ids:
        try:
            with lock, legacy.db() as con:
                # Serialize scheduler workers until delivery is recorded.
                if database_url():
                    con.execute('SELECT id FROM jobs WHERE id=? FOR UPDATE',(jid,)).fetchone()
                else:
                    con.execute('BEGIN IMMEDIATE')
                job = legacy.get_job(con,jid,True)
                if not job or not job['active']:
                    continue
                info = progress(job,today)
                due = []
                if job.get('piece_limit') and info['checked_total'] * 10 >= job['piece_limit'] * 9:
                    due.append(('quantity_notice_key',f"{job['project_manager_id']}:{job['piece_limit']}",'90 % limitu kusov',f"Skontrolovaných: {info['checked_total']} ks. Limit: {job['piece_limit']} ks. Zostáva: {info['remaining']} ks."))
                if info['days_remaining'] is not None and info['days_remaining'] <= 7:
                    due.append(('date_notice_key',f"{job['project_manager_id']}:{job['end_date']}",'Blížiaci sa termín ukončenia',f"Dátum ukončenia: {job['end_date']}. " + ('Termín už uplynul.' if info['days_remaining'] < 0 else f"Zostáva {info['days_remaining']} dní.")))
                due = [item for item in due if job.get(item[0]) != item[1]]
                if not due:
                    continue
                with host.SessionLocal() as session:
                    manager = session.get(host.User,job['project_manager_id'])
                    if not manager or not manager.active or manager.role != 'admin' or not manager.email:
                        raise ValueError('Project Manager nemá platný aktívny admin účet s e-mailom')
                    recipient = manager.email
                titles = ' / '.join(item[2] for item in due)
                body = '\n\n'.join(item[3] for item in due)
                host.microsoft_graph_send_email(f"MIELL – {job['order_number']} – {titles}",f"Zákazka: {job['order_number']}\n{job['brief_description']}\n\n{body}\n\nPodrobnosti nájdeš v module Kvalita → Zákazky.",[recipient],[])
                for column, key, _, _ in due:
                    con.execute(f'UPDATE jobs SET {column}=? WHERE id=?',(key,jid))
                    sent.append({'job_id':jid,'kind':column})
        except Exception as exc:
            errors.append({'job_id':jid,'module':'quality_milestone','error':str(exc)})
    return {'sent':sent,'errors':errors}
