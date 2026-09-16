"""Portable, concurrency-safe PDF/XLSX exports; original XLSM layout is retained."""
import os
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def export_path(filename):
    return str(Path(tempfile.mkdtemp(prefix='miell_export_')) / filename)


def simple_xlsx(info, headers, rows, filename):
    out = export_path(filename)
    with xlsxwriter.Workbook(out, {'strings_to_formulas': False, 'strings_to_urls': False}) as book:
        sheet = book.add_worksheet('Report')
        head = book.add_format({'bold': True, 'bg_color': '#247A49', 'font_color': '#FFFFFF', 'text_wrap': True})
        warning = book.add_format({'bg_color': '#FEE2E2', 'font_color': '#991B1B', 'text_wrap': True})
        normal = book.add_format({'text_wrap': True})
        sheet.set_column(0, len(headers)-1, 17)
        for i, row in enumerate(info):
            sheet.write_row(i, 0, row)
        start = len(info)
        sheet.write_row(start, 0, headers, head)
        deviation = headers.index('Deviation %') if 'Deviation %' in headers else None
        for i, row in enumerate(rows, start+1):
            flag = deviation is not None and isinstance(row[deviation], (float, int)) and abs(row[deviation]) > 10
            sheet.write_row(i, 0, row, warning if flag else normal)
        sheet.freeze_panes(start+1, 0)
        sheet.autofilter(start, 0, start+len(rows), len(headers)-1)
    return out


def pdf_report(legacy, records, job=None, scope=''):
    out = export_path('MIELL_Quality_Report.pdf')
    font = 'Helvetica'
    font_path = Path(__file__).parent / 'fonts' / 'LiberationSans-Regular.ttf'
    if font_path.exists():
        if 'MiellQuality' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('MiellQuality', str(font_path)))
        font = 'MiellQuality'
    style = ParagraphStyle('body', fontName=font, fontSize=8, leading=11)
    title = ParagraphStyle('title', parent=style, fontSize=16, leading=21, spaceAfter=12)
    p = lambda value: Paragraph(escape(str(value if value is not None else '')), style)
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=25, bottomMargin=28)
    story = [Paragraph('MIELL Quality — ' + escape(job['order_number'] if job else 'Records report'), title)]
    story += [p(scope), p(f'Records: {len(records)} | Checked: {sum(r["checked_items"] for r in records)} | OK: {sum(r["ok_items"] for r in records)} | NOK: {sum(r["nok_items"] for r in records)}'), Spacer(1, 12)]
    headers = ['Date / Shift', 'Order / Item', 'Operator', 'Checked', 'OK', 'NOK', 'R.OK / R.NOK', 'Time', 'Target/h', 'Actual/h', 'Deviation']
    data = [[p(x) for x in headers]]
    commands = [('BACKGROUND', (0,0), (-1,0), colors.HexColor('#DCEDE2')), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('LINEBELOW', (0,0), (-1,-1), .3, colors.HexColor('#D1D5DB')), ('TOPPADDING', (0,0), (-1,-1), 7), ('BOTTOMPADDING', (0,0), (-1,-1), 7)]
    for r in records:
        part = r.get('part_snapshot_obj') or {}
        values = [r['record_date']+' / '+r.get('shift',''), r.get('order_number','')+' / '+part.get('item_number',''), r.get('display_name',''), r['checked_items'], r['ok_items'], r['nok_items'], f"{r['reworked_ok']} / {r['reworked_nok']}", legacy.seconds_to_hms(r.get('work_time_seconds',0)), r.get('norm_target_per_hour') or '—', r.get('actual_per_hour') if r.get('actual_per_hour') is not None else '—', f"{r['norm_deviation_pct']:.2f}%" if r.get('norm_deviation_pct') is not None else '—']
        row_index = len(data)
        data.append([p(v) for v in values])
        counts = r.get('error_counts_obj') or {}
        errors = (r.get('job_snapshot_obj') or {}).get('errors', [])
        detail = ' | '.join(filter(None, [part.get('part_name',''), 'Delivery: '+str(r.get('delivery_note') or '—'), 'Errors: '+', '.join(f"{e['name']}: {counts.get(str(e['id']), 0)}" for e in errors), 'Note: '+str(r.get('note') or '—'), 'Archived' if r.get('archived') else '']))
        data.append([p(detail)] + ['']*10)
        commands += [('SPAN', (0,row_index+1), (-1,row_index+1))]
        if r.get('norm_outside'):
            commands.append(('BACKGROUND', (0,row_index), (-1,row_index+1), colors.HexColor('#FEE2E2')))
    if not records:
        data.append([p('No records for the selected filters.')] + ['']*10)
        commands.append(('SPAN',(0,1),(-1,1)))
    widths = [66,137,100,46,37,37,61,56,53,53,48]
    table = LongTable(data, colWidths=widths, repeatRows=1, hAlign='LEFT', splitInRow=1)
    table.setStyle(TableStyle(commands))
    story.append(table)
    def footer(canvas, document):
        canvas.setFont(font, 8)
        canvas.drawString(24, 13, 'MIELL • Quality reporting')
        canvas.drawRightString(817, 13, str(document.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out


def install_exports(legacy):
    legacy.simple_xlsx = simple_xlsx
    legacy.make_pdf = lambda job, records, scope='': pdf_report(legacy, records, job, scope)
    legacy.make_records_pdf = lambda records, scope='Filtered records': pdf_report(legacy, records, scope=scope)
