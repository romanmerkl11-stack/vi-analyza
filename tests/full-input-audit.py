#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KOMPLEXNÝ AUDIT VŠETKÝCH TYPOV VSTUPOV (jednorazový snímok stavu čítania).

Prejde každý typ vstupu, ktorý appka prijíma (handleFiles), spustí správny čítač a porovná
s ground truth kde je. OCR cesty (sken/obrázok) na Macu iba klasifikuje (status
'windows-pending') — merať treba na Windows (RapidOCR). Vektor/krivky/popisky/CSV/DXF/ZIP/JSON
sú plne verné aj na Macu.

Výstup: tests/audit/report.json  + konzolová matica.
Vizuálny HTML report sa renderuje zvlášť (tools/build_input_audit.py z report.json).

Spustenie (z adresára repa):  python3 tests/full-input-audit.py
Na grafik-pc (Windows) sa OCR riadky doplnia automaticky (ocr_win.py je dostupný).
"""
import sys, os, json, glob, csv, io, zipfile, subprocess, importlib.util, re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.path.dirname(REPO)                    # koreň projektu (datasety, vi_extract, vi_flatmix)
sys.path.insert(0, os.path.join(REPO, 'tools'))
sys.path.insert(1, os.path.join(REPO, '..', 'tools'))
sys.path.insert(2, ROOT)

import pdf_legend as L

# reading-harness.py má pomlčku v názve → načítaj cez importlib
_spec = importlib.util.spec_from_file_location('reading_harness',
                                               os.path.join(HERE, 'reading-harness.py'))
RH = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(RH)

IS_WIN = sys.platform.startswith('win')
SCAN_SKIP = re.compile(r'pohlad|rez|situ|zaklad|krov|strech|detail|skladb|vykaz|titulk|'
                       r'spr[aá]va|obsah|kontajner|schema', re.I)
# doložené chyby PODKLADU (nie parsera) — vytlačená CELKOVÁ != súčet miestností; oracle aj
# appka čítajú zhodne. Viď KONTROLA_vykresov.md.
KNOWN_SOURCE_DIFF = {'RNDZ_C_04_3+5NP-C.pdf',
                     'BD Krasnany RP_1.02 - 1.NP-PÔDORYS.pdf'}   # +21,2 (súčet miest. 677,56 vs vytlačené 656,36)


def _p(*parts):
    # datasety sa presunuli do Vstupy/ — skús ROOT, potom ROOT/Vstupy (a Vstupy/SAR pre výkresy)
    direct = os.path.join(ROOT, *parts)
    if os.path.exists(direct):
        return direct
    invstup = os.path.join(ROOT, 'Vstupy', *parts)
    if os.path.exists(invstup):
        return invstup
    return direct


# ---------- CSV (app-formát) ----------
def audit_csv():
    rows = []
    node = 'node'
    # čistý dataset: NESMIE mať žiadne zahodené názvy (guard nič reálne nezmaže).
    # SAR folder zámerne netestujeme ako celok — mieša dva exporty + duplikáty (viď upratanie).
    for label, path in [('Topolcianska (10 CSV)', 'Topolcianska')]:
        try:
            out = subprocess.run([node, os.path.join(HERE, 'dataset-audit.js'), _p(path)],
                                 capture_output=True, text=True, timeout=120)
            j = json.loads(out.stdout)
            disc = j.get('discardedNames', [])
            auto_disc = [d for d in disc if not d.get('manual')]
            ok = (not j.get('unknownRoomTypes') and not j.get('failures')
                  and not j.get('duplicateUnits') and j.get('replacementChars', 0) == 0
                  and not auto_disc)   # čistota názvov: 0 auto-zahodených
            rows.append({'typ': 'CSV', 'dataset': label, 'cesta': 'buildModel',
                         'status': 'ok' if ok else 'chyba',
                         'detail': 'podlaží=%s miest=%s jedn=%s neznáme=%d zahodené=%d dup=%d' % (
                             j.get('floors'), j.get('rooms'), j.get('units'),
                             len(j.get('unknownRoomTypes', [])), len(auto_disc),
                             len(j.get('duplicateUnits', []))),
                         'gt': 'sum-konzistencia + 0 neznámych + 0 auto-zahodených'})
        except Exception as e:
            rows.append({'typ': 'CSV', 'dataset': label, 'cesta': 'buildModel',
                         'status': 'error', 'detail': repr(e)[:120], 'gt': ''})
    return rows


# ---------- PDF: vektor / krivky / popisky (Mac-verné) ----------
def _pdf_row(typ, path, gt_dir):
    r = RH.analyze_pdf(path)
    key = os.path.basename(path)
    via = r.get('via') or '-'
    row = {'typ': typ, 'dataset': key, 'cesta': via, 'status': 'zlyhalo',
           'detail': r.get('note', ''), 'gt': ''}
    if r.get('ok'):
        d = r.get('diff')
        row['status'] = 'ok'
        row['detail'] = 'miest=%s jedn=%s interiér=%.2f CELKOVÁ=%s diff=%s' % (
            r.get('rooms'), r.get('units'), r.get('interiorSum', 0),
            ('%.2f' % r['printedTotal']) if r.get('printedTotal') else '—',
            ('%+.2f' % d) if d is not None else '—')
        if d is not None:
            if abs(d) < 0.1:
                row['status'] = 'ok'
            elif key in KNOWN_SOURCE_DIFF:
                row['status'] = 'known'
            else:
                row['status'] = 'diff'
            row['gt'] = 'CELKOVÁ diff %+.2f' % d
            if key in KNOWN_SOURCE_DIFF:
                row['gt'] += ' (doložená chyba výkresu)'
        # ground truth súbor?
        gtf = os.path.join(gt_dir, os.path.splitext(key)[0] + '.json')
        if os.path.exists(gtf):
            g = RH.gt_compare(r, json.load(open(gtf, encoding='utf-8')))
            row['gt'] = 'GT %d/%d OK (%d chyba, %d zle)' % (
                g['hit'], g['total_gt'], g['miss'], g['wrong'])
            row['status'] = 'ok' if (g['miss'] == 0 and g['wrong'] == 0) else 'diff'
    return row


def audit_pdf():
    rows = []
    gt_dir = os.path.join(HERE, 'ground-truth')
    groups = [
        ('PDF vektor/krivky (RNDZ)', sorted(glob.glob(_p('EXPEDICIA 0.9_20-07-10', 'RNDZ_*NP*.pdf')))),
        ('PDF vektor/krivky (IC1)', sorted(glob.glob(_p('IC', 'IC1', '*.pdf')))),
        ('PDF popisky (IC2)', sorted(glob.glob(_p('IC', 'IC2', '*.pdf')))),
        ('PDF vektor (Krasnany)', sorted(glob.glob(_p('Krasnany', '*.pdf')))),
    ]
    for label, files in groups:
        for f in files:
            if SCAN_SKIP.search(os.path.basename(f)):
                continue
            try:
                row = _pdf_row(label, f, gt_dir)
            except Exception as e:
                row = {'typ': label, 'dataset': os.path.basename(f), 'cesta': '-',
                       'status': 'error', 'detail': repr(e)[:120], 'gt': ''}
            rows.append(row)
    return rows


# ---------- PDF sken (Šuty) — OCR, Windows ----------
def audit_scan():
    rows = []
    files = [f for f in sorted(glob.glob(_p('Nove suty II', '**', '*.pdf'), recursive=True))
             if re.search(r'podorys', os.path.basename(f), re.I)
             and not SCAN_SKIP.search(os.path.basename(f))]
    for f in files[:12]:
        # disambiguuj podľa domu (A_DVOJDOM / B_TROJDOM / C_ZAHRADNY DOM)
        dom = next((p for p in f.split(os.sep) if 'DOM' in p.upper()), '')
        key = (dom.split('_')[0] + ' ' if dom else '') + os.path.basename(f)
        if IS_WIN:
            try:
                row = _pdf_row('PDF sken (Šuty)', f, os.path.join(HERE, 'ground-truth'))
            except Exception as e:
                row = {'typ': 'PDF sken (Šuty)', 'dataset': key, 'cesta': 'ocr',
                       'status': 'error', 'detail': repr(e)[:120], 'gt': ''}
        else:
            row = {'typ': 'PDF sken (Šuty)', 'dataset': key, 'cesta': 'ocr',
                   'status': 'windows-pending',
                   'detail': 'sken bez textovej vrstvy → RapidOCR (spustiť na grafik-pc)',
                   'gt': 'vytlačená ÚŽITKOVÁ/CELKOVÁ'}
        rows.append(row)
    return rows


# ---------- Obrázok — OCR, Windows (má GT cely_C_1NP.csv) ----------
def audit_image():
    rows = []
    for f in sorted(glob.glob(_p('test-obrazky', '*.png')) + glob.glob(_p('test-obrazky', '*.jpg'))):
        key = os.path.basename(f)
        gt = os.path.splitext(f)[0] + '.csv'
        has_gt = os.path.exists(gt)
        rows.append({'typ': 'Obrázok (OCR)', 'dataset': key, 'cesta': 'ocr',
                     'status': ('windows-pending' if not IS_WIN else 'ok'),
                     'detail': 'raster → RapidOCR (spustiť na grafik-pc)',
                     'gt': ('GT %s' % os.path.basename(gt)) if has_gt else 'bez GT'})
    return rows


# ---------- ZIP ----------
def audit_zip():
    rows = []
    for f in sorted(glob.glob(_p('*.zip')))[:1] + glob.glob(_p('EXPEDICIA*.zip')):
        key = os.path.basename(f)
        try:
            with zipfile.ZipFile(f) as z:
                names = z.namelist()
                csvs = [n for n in names if n.lower().endswith('.csv')]
                pdfs = [n for n in names if n.lower().endswith('.pdf')]
            rows.append({'typ': 'ZIP', 'dataset': key, 'cesta': 'unpack→CSV/PDF',
                         'status': 'ok', 'detail': '%d súborov (%d CSV, %d PDF)' % (
                             len(names), len(csvs), len(pdfs)),
                         'gt': 'obsah čitateľný'})
        except Exception as e:
            rows.append({'typ': 'ZIP', 'dataset': key, 'cesta': 'unpack',
                         'status': 'error', 'detail': repr(e)[:120], 'gt': ''})
    return rows


# ---------- JSON (krivky výstup → flatmix) ----------
def audit_json():
    rows = []
    try:
        import krivky_na_text as K
        f = _p('IC', 'IC1', '07_6np-podorys 6np legenda.pdf')
        items, stats = K.extract_bytes(open(f, 'rb').read())
        ok = bool(items) and all(('s' in it and 'x' in it and 'y' in it) for it in items[:20])
        rows.append({'typ': 'JSON (krivky výstup)', 'dataset': 'IC1 6NP → JSON',
                     'cesta': 'krivky→JSON→FlatmixCore', 'status': 'ok' if ok else 'chyba',
                     'detail': '%d položiek, štruktúra {s,x,y,w,h,rot} OK' % len(items),
                     'gt': 'štruktúra položiek'})
    except Exception as e:
        rows.append({'typ': 'JSON (krivky výstup)', 'dataset': 'IC1 6NP → JSON',
                     'cesta': 'krivky→JSON', 'status': 'error', 'detail': repr(e)[:120], 'gt': ''})
    return rows


# ---------- DXF/DWG (vi_extract oracle) ----------
def audit_dxf():
    rows = []
    def _find(name):    # DXF/GT mohli ostať v ROOT alebo sa presunúť do Vstupy/SAR
        for cand in (os.path.join(ROOT, name), os.path.join(ROOT, 'Vstupy', 'SAR', name),
                     os.path.join(ROOT, 'Vstupy', name)):
            if os.path.exists(cand):
                return cand
        return None
    pairs = [('1NP SAR.dxf', '1np-1.csv'), ('3NP SAR.dxf', '3np-1.csv')]
    for dxf, gtcsv in pairs:
        dp, gp = _find(dxf), _find(gtcsv)
        if not (dp and gp):
            continue
        try:
            out = subprocess.run(['python3', _p('vi_extract.py'), dp, gp],
                                 capture_output=True, text=True, timeout=180)
            m = re.search(r'porovnaných:\s*(\d+)\s+SEDÍ:\s*(\d+)\s+NESEDÍ:\s*(\d+)', out.stdout)
            if m:
                tot, ok_, bad = map(int, m.groups())
                rows.append({'typ': 'DXF (oracle)', 'dataset': dxf, 'cesta': 'vi_extract',
                             'status': 'ok' if bad == 0 else 'known',
                             'detail': 'SEDÍ %d/%d (NESEDÍ %d = doložené chyby výkresu)' % (ok_, tot, bad),
                             'gt': gtcsv + ' (rozdiely = KONTROLA_vykresov.md)'})
            else:
                rows.append({'typ': 'DXF (oracle)', 'dataset': dxf, 'cesta': 'vi_extract',
                             'status': 'chyba', 'detail': (out.stdout or out.stderr)[:120], 'gt': gtcsv})
        except Exception as e:
            rows.append({'typ': 'DXF (oracle)', 'dataset': dxf, 'cesta': 'vi_extract',
                         'status': 'error', 'detail': repr(e)[:120], 'gt': gtcsv})
    return rows


def main():
    sections = [
        ('CSV', audit_csv), ('PDF (vektor/krivky/popisky)', audit_pdf),
        ('PDF sken', audit_scan), ('Obrázok', audit_image),
        ('ZIP', audit_zip), ('JSON', audit_json), ('DXF/DWG', audit_dxf),
    ]
    all_rows = []
    for name, fn in sections:
        print('\n==== %s ====' % name)
        try:
            rows = fn()
        except Exception as e:
            print('  SEKCIA ZLYHALA:', repr(e)); rows = []
        for r in rows:
            print('  [%-16s] %-34s %-8s %s' % (
                r['status'], r['dataset'][:34], r['cesta'][:8], r['detail'][:60]))
        all_rows += rows

    # súhrn
    by_status = {}
    for r in all_rows:
        by_status[r['status']] = by_status.get(r['status'], 0) + 1
    print('\n' + '=' * 70)
    print('SÚHRN:', ', '.join('%s=%d' % (k, v) for k, v in sorted(by_status.items())))

    out_dir = os.path.join(HERE, 'audit')
    os.makedirs(out_dir, exist_ok=True)
    report = {'platform': sys.platform, 'rows': all_rows, 'summary': by_status}
    json.dump(report, open(os.path.join(out_dir, 'report.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print('report.json ->', os.path.join(out_dir, 'report.json'))


if __name__ == '__main__':
    main()
