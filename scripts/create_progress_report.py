"""Render the reviewed Markdown supervisor report with ReportLab.

Requires reportlab in the document-authoring Python environment, not the API venv.
"""
import argparse
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, PageBreak,
                               PageTemplate, Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
INK = colors.HexColor('#1b2d42')
MUTED = colors.HexColor('#66778b')
ACCENT = colors.HexColor('#16785e')
LINE = colors.HexColor('#dce5ec')


def fonts():
    choices = [(Path('C:/Windows/Fonts/arial.ttf'), Path('C:/Windows/Fonts/arialbd.ttf')),
               (Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))]
    for regular, bold in choices:
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont('Report', str(regular)))
            pdfmetrics.registerFont(TTFont('ReportBold', str(bold)))
            pdfmetrics.registerFontFamily('Report', normal='Report', bold='ReportBold', italic='Report', boldItalic='ReportBold')
            return
    raise RuntimeError('Install Arial or DejaVu Sans before rendering this report')


def inline(value):
    value = escape(value)
    return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', value)


def render(source, destination):
    fonts()
    width = A4[0] - 96
    styles = {
        'title': ParagraphStyle('ReportTitle', fontName='ReportBold', fontSize=28, leading=33, textColor=INK, spaceAfter=12),
        'h1': ParagraphStyle('ReportH1', fontName='ReportBold', fontSize=18, leading=23, textColor=INK, spaceAfter=16, keepWithNext=True),
        'h2': ParagraphStyle('ReportH2', fontName='ReportBold', fontSize=11.7, leading=16, textColor=ACCENT, spaceBefore=12, spaceAfter=6, keepWithNext=True),
        'body': ParagraphStyle('ReportBody', fontName='Report', fontSize=10.3, leading=14.8, textColor=INK, spaceAfter=9),
        'bullet': ParagraphStyle('ReportBullet', fontName='Report', fontSize=10.1, leading=14.5, textColor=INK, leftIndent=11, firstLineIndent=-9, spaceAfter=6),
        'cell': ParagraphStyle('ReportCell', fontName='Report', fontSize=9.1, leading=12.7, textColor=INK),
        'head': ParagraphStyle('ReportTableHead', fontName='ReportBold', fontSize=9.1, leading=12.7, textColor=colors.white),
        'caption': ParagraphStyle('ReportCaption', fontName='Report', fontSize=8.7, leading=12.2, textColor=MUTED, spaceAfter=10),
    }
    blocks = source.read_text(encoding='utf-8').split('<!-- pagebreak -->')
    flow = []
    for page_index, block in enumerate(blocks):
        if page_index:
            flow.append(PageBreak())
        lines = block.strip().splitlines()
        i = 0
        caption = False
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            if line.startswith('|'):
                rows = []
                while i < len(lines) and lines[i].strip().startswith('|'):
                    cells = [cell.strip() for cell in lines[i].strip().strip('|').split('|')]
                    if not all(re.fullmatch(r':?-+:?', cell.replace(' ', '')) for cell in cells):
                        rows.append(cells)
                    i += 1
                columns = len(rows[0])
                widths = ([width * .32, width * .68] if columns == 2 else
                          [width * .28, width * .16, width * .56] if rows[0][0] == 'Check group' else
                          [width * .60, width * .20, width * .20] if rows[0][0] == 'Stored record' else
                          [width * .34, width * .33, width * .33])
                body = [[Paragraph(inline(cell), styles['head' if row_index == 0 else 'cell'])
                         for cell in row] for row_index, row in enumerate(rows)]
                table = Table(body, colWidths=widths, repeatRows=1, hAlign='LEFT')
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), INK),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f3f7f8'), colors.white]),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
                    ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('LINEBELOW', (0, 0), (-1, -1), .4, LINE),
                ]))
                flow.extend([table, Spacer(1, 9)])
                continue
            match = re.fullmatch(r'!\[(.*?)\]\((.*?)\)', line)
            if match:
                image_path = (source.parent / match[2]).resolve()
                image_width, image_height = ImageReader(str(image_path)).getSize()
                image = Image(str(image_path), width=336, height=image_height * 336 / image_width)
                image.hAlign = 'CENTER'
                flow.extend([image, Spacer(1, 8)])
                caption = True
                i += 1
                continue
            if line.startswith('# '):
                flow.append(Paragraph(inline(line[2:]), styles['title']))
            elif line.startswith('## '):
                flow.append(Paragraph(inline(line[3:]), styles['h1']))
            elif line.startswith('### '):
                flow.append(Paragraph(inline(line[4:]), styles['h2']))
            elif line.startswith('> '):
                callout = Table([[Paragraph(inline(line[2:]), styles['body'])]], colWidths=[width])
                callout.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eaf4ef')),
                    ('BOX', (0, 0), (-1, -1), .6, colors.HexColor('#c7dfd3')),
                    ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                    ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
                flow.extend([callout, Spacer(1, 10)])
            elif line.startswith('- ') or re.match(r'^\d+\. ', line):
                marker, text = ('- ', line[2:]) if line.startswith('- ') else ('', line)
                flow.append(Paragraph(inline(marker + text), styles['bullet']))
            else:
                paragraph = [line]
                while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r'^(#|\||>|- |!\[|\d+\. )', lines[i + 1].strip()):
                    i += 1
                    paragraph.append(lines[i].strip())
                flow.append(Paragraph(inline(' '.join(paragraph)), styles['caption' if caption else 'body']))
                caption = False
            i += 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = BaseDocTemplate(str(destination), pagesize=A4, leftMargin=48, rightMargin=48,
        topMargin=57, bottomMargin=57, title='DevOps auto-deployment - supervisor progress report',
        author='DevOps auto-deployment project', subject='Completed work, evidence and remaining milestones', allowSplitting=1)
    def decorate(page_canvas, doc):
        # Draw decorations in the normal page lifecycle. Replaying cached canvas
        # states can lose dynamic TrueType font subsets on individual pages.
        page_canvas.saveState()
        page_width, page_height = A4
        page_canvas.setFillColor(ACCENT)
        page_canvas.rect(0, page_height - 8, page_width, 8, fill=1, stroke=0)
        page_canvas.setFont('ReportBold', 8.5)
        page_canvas.setFillColor(INK)
        page_canvas.drawString(48, page_height - 31, 'DEVOPS AUTO-DEPLOYMENT')
        page_canvas.setFont('Report', 8)
        page_canvas.setFillColor(MUTED)
        page_canvas.drawRightString(page_width - 48, page_height - 31, 'LOCAL PROTOTYPE | SUPERVISOR REVIEW')
        page_canvas.setStrokeColor(LINE)
        page_canvas.line(48, 42, page_width - 48, 42)
        page_canvas.setFont('Report', 8)
        page_canvas.drawString(48, 27, '24 October 2026 | Progress and evidence checkpoint')
        page_canvas.drawRightString(page_width - 48, 27, f'{doc.page} / {len(blocks)}')
        page_canvas.restoreState()
    document.addPageTemplates(PageTemplate('report', [Frame(48, 57, width, A4[1] - 114, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=decorate))
    document.build(flow)
    if document.page != len(blocks):
        raise RuntimeError('Report overflowed its planned pages; review and adjust the layout')
    print(str(destination.resolve()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'docs/reports/supervisor-progress-report-2026-10-24.md')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/pdf/DevOps_Project_Progress_Report_2026-10-24.pdf')
    args = parser.parse_args()
    render(args.source, args.output)
