#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E0 — Test harness spolahlivosti citania podkladov (offline, oracle-first).

Pre kazdy PDF zvoli CESTU rovnako ako appka (`_run_legend`) + navyse most krivky:
    1) VEKTOR : pdf_legend.to_app_csv         (PDF s textovou vrstvou)
    2) KRIVKY : krivky_na_text.extract_bytes -> pdf_legend.to_app_csv_ocr  (legenda ako obrysy)
    3) OCR    : ocr(_win).recognize_pdf      -> pdf_legend.to_app_csv_ocr  (raster/sken)
Z vyrobeneho app-CSV (to iste, co by videla appka) spocita metriky:
    interiorSum, printedTotal (CELKOVA), diff, #rooms, #units, #areas.

Dve vrstvy pouzitia:
  A) AUTO-METRIKA        : diff = interiorSum - printedTotal (kde je medzisucet vytlaceny)
  B) BASELINE SNAPSHOT   : --save-baseline zapise dnesny vystup; bezne spustenie porovna
                           (regresna poistka: NEW nesmie zhorsit dobre vysledky)
  C) GROUND TRUTH        : ak existuje tests/ground-truth/<key>.json (rucne overene
                           riadky kod->plocha), spocita per-miestnost presnost.

OCR cesta: na Macu bezi Apple Vision (slaby na cele harky) -> realne cisla OCR harkov
merat na Windows (RapidOCR tiled). Vektor a KRIVKY su plne verne aj na Macu.

Pouzitie:
  python3 tests/reading-harness.py <PDF|adresar> [...] [--save-baseline] [--json OUT]
"""
import sys, os, json, glob, hashlib, csv, io

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'tools'))          # repo tools (zdroj pravdy)
sys.path.insert(1, os.path.join(REPO, '..', 'tools'))    # root tools/ (ocr.py Apple Vision)
sys.path.insert(2, os.path.join(REPO, '..'))             # koreň projektu (vi_flatmix.py)

import pdf_legend as L
try:
    import krivky_na_text as K
except Exception:
    K = None
try:
    import vi_flatmix as FLAT          # flatmix „popisky" (apartmánové štítky v pôdoryse)
except Exception:
    FLAT = None


def _round2(x):
    return int(x * 100 + (0.5 if x >= 0 else -0.5)) / 100.0


def _load_ocr():
    """Vrati modul OCR podla OS (Apple Vision / RapidOCR), alebo None."""
    name = 'ocr' if sys.platform == 'darwin' else 'ocr_win'
    try:
        return __import__(name)
    except Exception:
        return None


def csv_metrics(text):
    """Metriky z app-CSV (delimiter ';'): sumy interieru/exterieru, CELKOVA, pocty."""
    interior = exterior = 0.0
    printed = None
    rooms = units = areas = 0
    rdr = csv.reader(io.StringIO(text), delimiter=';')
    for row in rdr:
        if len(row) < 3:
            continue
        code = (row[0] or '').strip().strip('"').strip()
        name = (row[1] or '').strip().strip('"').strip()
        up = L.deburr(name).upper()
        iv = L.parse_area(row[2]) if len(row) > 2 else None
        ev = L.parse_area(row[3]) if len(row) > 3 else None
        # hlavicka tabulky / blok
        if up.startswith('C.M') or 'NAZOV MIESTNOSTI' in up or 'LEGENDA' in up:
            continue
        # medzisucet / celkova
        if 'CELKOV' in up:
            if iv is not None:
                printed = (printed or 0.0) + iv
            continue
        if 'PODLAHOVA PLOCHA' in up:
            continue
        # hlavicka jednotky (byt/apartman/studio/obchod) = kod bez plochy alebo s nazvom jednotky
        if any(w in up for w in ('BYT', 'APARTMAN', 'APARTMÁN', 'STUDIO', 'OBCHOD', 'NEBYTOV')) and iv is None:
            units += 1
            continue
        # riadok miestnosti
        if code or iv is not None or ev is not None:
            rooms += 1
            if iv is not None:
                interior += iv
                areas += 1
            if ev is not None:
                exterior += ev
    return {
        'interiorSum': _round2(interior),
        'exteriorSum': _round2(exterior),
        'printedTotal': (_round2(printed) if printed else None),
        'diff': (None if not printed else _round2(_round2(interior) - _round2(printed))),
        'rooms': rooms, 'units': units, 'areas': areas,
    }


def analyze_pdf(path):
    data = open(path, 'rb').read()
    key = os.path.basename(path)
    res = {'file': key, 'kb': len(data) // 1024, 'via': None, 'ok': False, 'note': ''}

    # 1) VEKTOR
    csv_text = None
    try:
        csv_text = L.to_app_csv(data)
    except Exception as e:
        res['note'] = 'to_app_csv ERR: %r' % e
    if csv_text:
        res['via'] = 'vektor'
    else:
        # 2) KRIVKY
        if K is not None:
            try:
                items, stats = K.extract_bytes(data)
                if items:
                    ct = L.to_app_csv_ocr(items)
                    if ct and ct.count('\n') > 3:
                        csv_text = ct
                        res['via'] = 'krivky'
                        res['krivky'] = {'glyphs': stats.get('glyphs'),
                                         'cells': stats.get('cells'),
                                         'dropped': stats.get('dropped')}
            except Exception as e:
                res['note'] = 'krivky ERR: %r' % e
        # 3) OCR
        if csv_text is None:
            ocr = _load_ocr()
            if ocr is not None:
                try:
                    items, st = ocr.recognize_pdf(data)
                    ct = L.to_app_csv_ocr(items)
                    if ct:
                        csv_text = ct
                        res['via'] = 'ocr'
                        res['ocr'] = {'items': st.get('items'), 'low': st.get('low')}
                except Exception as e:
                    res['note'] = 'ocr ERR: %r' % e

    if not csv_text:
        # 4) FLATMIX — nie je legenda miestnosti, ale apartmanove popisky v podoryse (IC2 typ)
        if FLAT is not None:
            try:
                fr = FLAT.read_pdf(path)
                units = fr.get('units') or []
                if units:
                    area = round(sum((u.get('area') or 0) for u in units), 2)
                    res.update({'via': 'flatmix', 'ok': True, 'mode': fr.get('mode'),
                                'units': len(units), 'rooms': 0, 'areas': len(units),
                                'interiorSum': area, 'exteriorSum': 0.0,
                                'printedTotal': None, 'diff': None})
                    return res
            except Exception as e:
                res['note'] = 'flatmix ERR: %r' % e
        res['note'] = res['note'] or 'legenda nenajdena ziadnou cestou'
        return res

    res['ok'] = True
    res['csv_sha'] = hashlib.sha1(csv_text.encode('utf-8', 'replace')).hexdigest()[:12]
    res.update(csv_metrics(csv_text))
    res['_csv'] = csv_text  # pre ground-truth porovnanie / debug (nezapisuje sa do baseline)
    return res


def gt_compare(res, gt):
    """Per-miestnost presnost proti ground-truth.
    Format GT: bud {code: interior_area}, alebo {'interior': {...}, 'exterior': {...}}."""
    if isinstance(gt, dict) and 'interior' in gt and isinstance(gt['interior'], dict):
        gt = gt['interior']
    got = {}
    rdr = csv.reader(io.StringIO(res.get('_csv', '')), delimiter=';')
    for row in rdr:
        if len(row) < 3:
            continue
        code = (row[0] or '').strip().strip('"').strip()
        iv = L.parse_area(row[2])
        if code and iv is not None:
            got[code] = iv
    hit = miss = wrong = 0
    details = []
    for code, area in gt.items():
        if code not in got:
            miss += 1; details.append('CHYBA %s (ocak %.2f)' % (code, area))
        elif abs(got[code] - area) > 0.01:
            wrong += 1; details.append('ZLE  %s: %.2f != %.2f' % (code, got[code], area))
        else:
            hit += 1
    extra = [c for c in got if c not in gt]
    return {'hit': hit, 'miss': miss, 'wrong': wrong, 'total_gt': len(gt),
            'extra_rows': len(extra), 'details': details[:20]}


def iter_pdfs(args):
    for a in args:
        if os.path.isdir(a):
            for p in sorted(glob.glob(os.path.join(a, '**', '*.pdf'), recursive=True)):
                yield p
        elif a.lower().endswith('.pdf'):
            yield a


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith('--')]
    save_baseline = '--save-baseline' in sys.argv
    json_out = None
    if '--json' in sys.argv:
        json_out = sys.argv[sys.argv.index('--json') + 1]
    if not argv:
        print(__doc__); sys.exit(1)

    gt_dir = os.path.join(HERE, 'ground-truth')
    base_path = os.path.join(HERE, 'baseline', 'reading.json')
    baseline = {}
    if os.path.exists(base_path):
        baseline = json.load(open(base_path, encoding='utf-8'))

    rows = []
    print('%-42s %-7s %5s %5s %5s %10s %10s %8s' %
          ('subor', 'cesta', 'rooms', 'unit', 'area', 'interior', 'CELKOVA', 'diff'))
    print('-' * 100)
    out = {}
    for p in iter_pdfs(argv):
        r = analyze_pdf(p)
        key = r['file']
        via = r['via'] or '-'
        if r['ok']:
            print('%-42s %-7s %5s %5s %5s %10.2f %10s %8s' %
                  (key[:42], via, r['rooms'], r['units'], r['areas'],
                   r['interiorSum'],
                   ('%.2f' % r['printedTotal']) if r['printedTotal'] else '-',
                   ('%+.2f' % r['diff']) if r['diff'] is not None else '-'))
        else:
            print('%-42s %-7s  ZLYHALO: %s' % (key[:42], via, r['note']))
        # ground truth
        gtf = os.path.join(gt_dir, os.path.splitext(key)[0] + '.json')
        if os.path.exists(gtf) and r['ok']:
            gt = json.load(open(gtf, encoding='utf-8'))
            g = gt_compare(r, gt)
            print('    GT: %d/%d OK, %d chyba, %d zle, +%d extra' %
                  (g['hit'], g['total_gt'], g['miss'], g['wrong'], g['extra_rows']))
            for d in g['details']:
                print('        ', d)
            r['gt'] = g
        # regresia voci baseline
        if key in baseline and r['ok']:
            b = baseline[key]
            if b.get('csv_sha') != r.get('csv_sha'):
                di = (r['interiorSum'] - b.get('interiorSum', 0))
                print('    ZMENA voci baseline: interior %+.2f (bolo %.2f), via %s->%s' %
                      (di, b.get('interiorSum', 0), b.get('via'), via))
        r.pop('_csv', None)
        out[key] = r
        rows.append(r)

    ok = sum(1 for r in rows if r['ok'])
    zero = sum(1 for r in rows if r['ok'] and abs(r.get('diff') or 0) < 0.01 and r.get('printedTotal'))
    withtot = sum(1 for r in rows if r['ok'] and r.get('printedTotal'))
    print('-' * 100)
    print('SPOLU: %d/%d precitane; %d/%d s medzisuctom sedi (diff=0)' %
          (ok, len(rows), zero, withtot))

    if json_out:
        json.dump(out, open(json_out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('JSON ->', json_out)
    if save_baseline:
        os.makedirs(os.path.dirname(base_path), exist_ok=True)
        json.dump(out, open(base_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('BASELINE ulozeny ->', base_path)


if __name__ == '__main__':
    main()
