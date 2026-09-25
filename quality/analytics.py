"""Read-only job analytics; callers supply records scoped to the authenticated user."""
import io
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

import xlsxwriter
from reportlab.graphics.shapes import Drawing, Rect, Line, String, Circle
from reportlab.graphics import renderSVG
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def empty_row(day=None):
    return dict(date=day, checked=0, ok=0, nok=0, errors={})


def finish(row):
    row['rate'] = row['nok'] / row['checked'] * 100 if row['checked'] else None
    return row


def build(job, records, today, scope, location='', part_id=None):
    start = today - timedelta(days=29)
    # Retain historic part IDs and defect names from the saved record snapshots.
    parts = {int(p['id']): p['item_number'] for p in job.get('parts', [])}
    for r in records:
        if r.get('part_id'):
            parts[int(r['part_id'])] = (r.get('part_snapshot_obj') or {}).get('item_number') or str(r['part_id'])
    if part_id is not None and part_id not in parts:
        raise ValueError('Diel nepatrí k tejto zákazke.')
    rows = [r for r in records if not r.get('archived') and str(r['record_date'])[:10] <= today.isoformat()
            and (part_id is None or r.get('part_id') == part_id)]
    total, recent = empty_row(), empty_row()
    daily = {(start + timedelta(days=i)).isoformat(): empty_row((start + timedelta(days=i)).isoformat()) for i in range(30)}
    names = {str(e['name']) for e in job.get('errors', [])}
    month_counts = defaultdict(int)
    first = None
    for r in rows:
        day = str(r['record_date'])[:10]
        first = min(first, day) if first else day
        snapshot = {str(e['id']): str(e['name']) for e in (r.get('job_snapshot_obj') or {}).get('errors', [])}
        counts = defaultdict(int)
        for key, value in (r.get('error_counts_obj') or {}).items():
            name = snapshot.get(str(key), 'Chyba ' + str(key))
            names.add(name)
            counts[name] += int(value or 0)
        for target in [total] + ([recent, daily[day]] if day in daily else []):
            for name, source in [('checked', 'checked_items'), ('ok', 'ok_items'), ('nok', 'nok_items')]:
                target[name] += int(r.get(source) or 0)
            for name, value in counts.items():
                target['errors'][name] = target['errors'].get(name, 0) + value
        month_counts[day[:7]] += int(r.get('checked_items') or 0)
    ordered = sorted(names, key=lambda n: (-total['errors'].get(n, 0), n.casefold()))
    cumulative = []
    running = 0
    if first:
        cursor = date.fromisoformat(first).replace(day=1)
        while cursor <= today:
            key = cursor.strftime('%Y-%m')
            running += month_counts[key]
            cumulative.append({'date': key, 'checked': running})
            cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return dict(job_id=job['id'], order=job['order_number'], description=job.get('brief_description', ''),
                location=location, scope=scope, as_of=today.isoformat(), start=start.isoformat(), first=first,
                part_id=part_id, parts=[{'id': k, 'item_number': v} for k, v in sorted(parts.items())],
                part_label=parts.get(part_id, 'Všetky diely'), errors=ordered, total=finish(total),
                recent=finish(recent), days=[finish(daily[k]) for k in sorted(daily, reverse=True)], cumulative=cumulative)


def pareto(row):
    values = sorted(((k, v) for k, v in row['errors'].items() if v > 0), key=lambda x: (-x[1], x[0]))
    if len(values) > 8:
        values = values[:7] + [('Ostatné chyby', sum(v for _, v in values[7:]))]
    total, running, out = sum(v for _, v in values), 0, []
    for label, value in values:
        running += value
        out.append((label, value, running / total * 100))
    return out


def font():
    if 'MiellAnalytics' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('MiellAnalytics', str(Path(__file__).parent / 'fonts/LiberationSans-Regular.ttf')))
    return 'MiellAnalytics'


GREEN, BLUE, RED, GRID = map(colors.HexColor, ['#39992D', '#376C98', '#BA5237', '#DAE5DC'])


def chart(data, kind, width=740, height=205):
    """Shared vector charts for PDF and the application; native Excel charts below."""
    f = font()
    d = Drawing(width, height)
    left, right, bottom, top = 55, width - 48, 64 if kind.startswith('pareto') else 36, height - 26
    def label(x, y, text, size=8, anchor='start', color=colors.HexColor('#526B5D')):
        d.add(String(x, y, str(text), fontName=f, fontSize=size, textAnchor=anchor, fillColor=color))
    if kind.startswith('pareto'):
        values = pareto(data['total'] if kind == 'pareto_total' else data['recent'])
        series = [v[1] for v in values]
        labels = [v[0] for v in values]
    elif kind == 'cumulative':
        values = data['cumulative']; series = [v['checked'] for v in values]; labels = [v['date'] for v in values]
    else:
        values = list(reversed(data['days']))
        series = [v['checked'] if kind == 'volume' else v['rate'] for v in values]
        labels = [v['date'][8:10]+'.'+v['date'][5:7]+'.' for v in values]
    maximum = max([v for v in series if v is not None] + [1]) * 1.18
    y = lambda v: bottom + (top-bottom) * v / maximum
    label(left, height-12, 'NOK / %' if kind == 'rate' else 'Počet / ks')
    for i in range(5):
        value = maximum*i/4; yy=y(value)
        d.add(Line(left, yy, right, yy, strokeColor=GRID, strokeWidth=.5))
        label(left-6, yy-3, f'{value:,.1f}' if kind == 'rate' else f'{value:,.0f}', anchor='end')
    if not series or not any(v for v in series if v is not None):
        label((left+right)/2, (top+bottom)/2, 'Bez údajov / bez chýb', 11, 'middle')
        return d
    step = (right-left)/len(series)
    xs = [left+step*(i+.5) for i in range(len(series))]
    if kind.startswith('pareto') or kind == 'volume':
        for i, value in enumerate(series):
            d.add(Rect(xs[i]-step*.3, bottom, step*.6, y(value)-bottom, fillColor=GREEN, strokeColor=None))
            if kind.startswith('pareto'):
                label(xs[i], y(value)+5, value, anchor='middle')
    else:
        for i in range(1, len(series)):
            if series[i] is not None and series[i-1] is not None:
                d.add(Line(xs[i-1], y(series[i-1]), xs[i], y(series[i]), strokeColor=RED if kind=='rate' else GREEN, strokeWidth=1.7))
        for i, value in enumerate(series):
            if value is not None:
                d.add(Circle(xs[i], y(value), 1.8, fillColor=RED if kind=='rate' else GREEN, strokeColor=None))
    if kind.startswith('pareto'):
        py = lambda p: bottom+(top-bottom)*p/100
        d.add(Line(left, py(80), right, py(80), strokeColor=BLUE, strokeDashArray=[3,3], strokeWidth=.7))
        for i in [0,50,100]: label(right+5, py(i)-3, str(i)+'%')
        for i, v in enumerate(values):
            if i: d.add(Line(xs[i-1], py(values[i-1][2]), xs[i], py(v[2]), strokeColor=BLUE, strokeWidth=1.5))
            d.add(Circle(xs[i], py(v[2]), 2, fillColor=BLUE, strokeColor=None))
    tick_ids = range(len(labels)) if kind.startswith('pareto') else sorted(set([0,len(labels)//3,2*len(labels)//3,len(labels)-1]))
    for i in tick_ids:
        text = labels[i]
        if kind.startswith('pareto'):
            # Up to three wrapped lines, with numbered full names in the accompanying table.
            text = str(i+1)+'. '+text
            words, lines, line = text.split(), [], ''
            for word in words:
                if line and pdfmetrics.stringWidth(line+' '+word, f, 8)>step-6:
                    lines.append(line); line=word
                else: line=(line+' '+word).strip()
            lines.append(line)
            for n, line in enumerate(lines[:3]):
                while pdfmetrics.stringWidth(line, f, 8)>step-5: line=line[:-2]+'…'
                label(xs[i],bottom-13-n*10,line,anchor='middle')
        else: label(xs[i], bottom-15, text, anchor='middle')
    return d


def svg_charts(data):
    return {key: renderSVG.drawToString(chart(data, key)) for key in ['pareto_total','pareto_recent','volume','rate','cumulative']}


def export_pdf(data):
    f=font(); out=io.BytesIO()
    body=ParagraphStyle('analytics-body',fontName=f,fontSize=8,leading=10)
    heading=ParagraphStyle('analytics-heading',fontName=f,fontSize=17,leading=22,spaceAfter=8)
    p=lambda v: Paragraph(escape(str(v)),body)
    story=[]
    def title(text):
        story.extend([Paragraph('MIELL Quality - '+escape(text),heading),p(data['order']+' | '+data['location']+' | '+data['part_label']),p(data['scope']+' | Stav k '+data['as_of']),Spacer(1,8)])
    # Split wide defect tables into legible column groups, repeating all daily totals.
    groups=[data['errors'][i:i+4] for i in range(0,len(data['errors']),4)] or [[]]
    for group_index, names in enumerate(groups):
        if story: story.append(PageBreak())
        title('Výsledky kontroly'+(f' ({group_index+1}/{len(groups)})' if len(groups)>1 else ''))
        story.extend([p('TOTAL: od začiatku zákazky ('+(data['first'] or 'bez záznamov')+'). Denné riadky: '+data['start']+' - '+data['as_of']+'.'),Spacer(1,7)])
        headers=['Dátum','Checked','OK','NOK','NOK rate']+names
        rows=[['TOTAL',data['total']]]+[[r['date'],r] for r in data['days']]+[['Súčet 30 dní',data['recent']]]
        cells=[[p(x) for x in headers]]
        for label,r in rows:
            cells.append([p(label),r['checked'],r['ok'],r['nok'],'—' if r['rate'] is None else f"{r['rate']:.2f} %"]+[r['errors'].get(n,0) for n in names])
        widths=[84,65,65,60,65]+[(790-339)/max(1,len(names))]*len(names)
        table=Table(cells,colWidths=widths,repeatRows=1)
        table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),f),('FONTSIZE',(0,0),(-1,-1),8),('ALIGN',(1,1),(-1,-1),'RIGHT'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BACKGROUND',(0,0),(-1,0),GRID),('BACKGROUND',(0,1),(-1,1),colors.HexColor('#E5F2E0')),('BACKGROUND',(0,-1),(-1,-1),GRID),('LINEBELOW',(0,0),(-1,-1),.3,GRID),('TOPPADDING',(0,0),(-1,-1),1),('BOTTOMPADDING',(0,0),(-1,-1),1)]))
        story.append(table)
    story.append(PageBreak());title('Pareto chýb')
    story.append(p('Zelené stĺpce: počet chýb. Modrá krivka: kumulovaný podiel chýb. Prerušovaná čiara: 80 %.'))
    for key,label in [('pareto_total','TOTAL - od začiatku'),('pareto_recent','Posledných 30 dní')]:
        story.extend([p(label),chart(data,key,height=205)])
    story.append(PageBreak());title('Vývoj výsledkov')
    for key,label in [('volume','Denný počet Checked - 30 dní'),('rate','Denný NOK rate - 30 dní'),('cumulative','Kumulovaný Checked - konce mesiacov, aktuálny mesiac k dátumu reportu')]:
        story.extend([p(label),chart(data,key,height=135)])
    def footer(canvas,doc):
        canvas.setFont(f,8);canvas.drawString(25,15,'MIELL Quality | Bez archivovaných záznamov');canvas.drawRightString(815,15,str(doc.page))
    SimpleDocTemplate(out,pagesize=landscape(A4),leftMargin=25,rightMargin=25,topMargin=22,bottomMargin=26).build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()


def export_xlsx(data):
    out=io.BytesIO()
    with xlsxwriter.Workbook(out,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False}) as book:
        sheet=book.add_worksheet('Výsledky');charts=book.add_worksheet('Grafy');raw=book.add_worksheet('Dáta grafov')
        head=book.add_format({'bold':True,'bg_color':'#E5F2E0','text_wrap':True});percent=book.add_format({'num_format':'0.00%'});totalpct=book.add_format({'bold':True,'bg_color':'#E5F2E0','num_format':'0.00%'})
        for i,text in enumerate([data['order']+' - '+data['location'],data['part_label'],data['scope'],'TOTAL od '+(data['first'] or 'bez záznamov')+'; 30 dní '+data['start']+' - '+data['as_of']]):sheet.write(i,0,text)
        sheet.write_row(5,0,['Dátum','Checked','OK','NOK','NOK rate']+data['errors'],head)
        rows=[('TOTAL',data['total'])]+[(r['date'],r) for r in data['days']]+[('Súčet 30 dní',data['recent'])]
        for i,(label,r) in enumerate(rows,6):
            style=head if i in (6,37) else None
            sheet.write_row(i,0,[label,r['checked'],r['ok'],r['nok']],style)
            if r['rate'] is None:sheet.write(i,4,'—',style)
            else:sheet.write_number(i,4,r['rate']/100,totalpct if style else percent)
            sheet.write_row(i,5,[r['errors'].get(n,0) for n in data['errors']],style)
        sheet.set_column(0,0,18);sheet.set_column(1,4,14);sheet.set_column(5,5+len(data['errors']),20);sheet.freeze_panes(7,1)
        charts.write(0,0,data['order']+' | '+data['scope']);charts.write(1,0,data['part_label']+' | '+data['as_of'])
        for n,key in enumerate(['total','recent']):
            vals=pareto(data[key]);col=n*4
            raw.write_row(0,col,['Chyba','Počet','Kumulovaný podiel','Hranica 80 %'])
            for i,(name,value,cum) in enumerate(vals,1):raw.write_row(i,col,[name,value,cum/100,.8])
            if vals:
                c=book.add_chart({'type':'column'});c.add_series({'name':'Počet chýb','categories':['Dáta grafov',1,col,len(vals),col],'values':['Dáta grafov',1,col+1,len(vals),col+1],'fill':{'color':'#39992D'}})
                line=book.add_chart({'type':'line'});line.add_series({'name':'Kumulovaný podiel','categories':['Dáta grafov',1,col,len(vals),col],'values':['Dáta grafov',1,col+2,len(vals),col+2],'y2_axis':True,'line':{'color':'#376C98'}})
                line.add_series({'name':'80 %','categories':['Dáta grafov',1,col,len(vals),col],'values':['Dáta grafov',1,col+3,len(vals),col+3],'y2_axis':True,'line':{'color':'#376C98','dash_type':'dash'}})
                c.combine(line);c.set_y2_axis({'min':0,'max':1,'num_format':'0%'});c.set_title({'name':'Pareto '+('TOTAL' if n==0 else '30 dní')});charts.insert_chart(3+n*17,0,c)
        raw.write_row(0,9,['Dátum','Checked','NOK %'])
        for i,r in enumerate(reversed(data['days']),1):raw.write_row(i,9,[r['date'],r['checked'],None if r['rate'] is None else r['rate']/100])
        for n,(label,col,typ) in enumerate([('Denný Checked',10,'column'),('Denný NOK %',11,'line')]):
            c=book.add_chart({'type':typ});c.add_series({'name':label,'categories':['Dáta grafov',1,9,30,9],'values':['Dáta grafov',1,col,30,col]});c.set_title({'name':label});c.show_blanks_as('gap')
            if col==11:c.set_y_axis({'num_format':'0.00%'})
            charts.insert_chart(37+n*17,0,c)
        raw.write_row(0,13,['Mesiac','Kumulovaný Checked'])
        for i,r in enumerate(data['cumulative'],1):raw.write_row(i,13,[r['date'],r['checked']])
        if data['cumulative']:
            n=len(data['cumulative']);c=book.add_chart({'type':'line'});c.add_series({'name':'Kumulovaný Checked','categories':['Dáta grafov',1,13,n,13],'values':['Dáta grafov',1,14,n,14]});c.set_title({'name':'Kumulovaný Checked'});charts.insert_chart(71,0,c)
    return out.getvalue()
