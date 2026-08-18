#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
krivky_na_text.py — z PDF, kde je legenda PREVEDENA NA KRIVKY, spravi textove polozky.

Preco to ide presne a nie odhadom (ako OCR): krivky su presne obrysy pismen, takze
rovnaky znak ma v celom vykrese uplne rovnaky tvar. Staci teda:
  1. kazdu vyplnenu cestu velkosti pisma vyrastrovat do malej bitmapy,
  2. bitmapy zhluknut — kazdy zhluk je jeden znak,
  3. zhluky raz oznacit (mapa znakov nizsie) a to plati pre vsetky vykresy.

Vystup je JSON so zoznamom poloziek {s,x,y,w,h,rot} v rovnakom tvare, aky dava
pdf.js — appka ich spracuje tym istym parserom ako bezne PDF.

    python3 tools/krivky_na_text.py "IC/IC1/06_5np-podorys 5np legenda.pdf" -o out.json

Mapa znakov sa uci z referencneho vykresu (--ref) a uklada do tools/znaky.json.
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

try:
    import fitz
except ImportError:
    sys.exit('Chyba: chyba PyMuPDF.  pip3 install pymupdf')

PPP = 10.0          # px na bod
CELL = 64
SMALL = 16
MAXPT = 6.4         # vacsie vyplnene cesty uz nie su pismena
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mapfile():
    """Launcher ukladá malé moduly naplocho vedľa exe; vývojová verzia ich má v tools/."""
    here = os.path.dirname(os.path.abspath(__file__))
    beside = os.path.join(here, 'znaky.json')
    return beside if os.path.isfile(beside) else os.path.join(ROOT, 'tools', 'znaky.json')


# ---------- geometria ----------

def _flatten(items):
    """Cesta -> zoznam uzavretych obrysov (bezier sa linearizuje)."""
    subs, cur, prev = [], [], None
    for it in items:
        k = it[0]
        if k == 'l':
            p1, p2 = it[1], it[2]
            if prev is None or abs(p1.x - prev.x) > 1e-6 or abs(p1.y - prev.y) > 1e-6:
                if len(cur) > 2:
                    subs.append(cur)
                cur = [(p1.x, p1.y)]
            cur.append((p2.x, p2.y)); prev = p2
        elif k == 'c':
            p0, p1, p2, p3 = it[1], it[2], it[3], it[4]
            if prev is None or abs(p0.x - prev.x) > 1e-6 or abs(p0.y - prev.y) > 1e-6:
                if len(cur) > 2:
                    subs.append(cur)
                cur = [(p0.x, p0.y)]
            for i in range(1, 9):
                t = i / 8.0; u = 1 - t
                cur.append((u*u*u*p0.x + 3*u*u*t*p1.x + 3*u*t*t*p2.x + t*t*t*p3.x,
                            u*u*u*p0.y + 3*u*u*t*p1.y + 3*u*t*t*p2.y + t*t*t*p3.y))
            prev = p3
        elif k == 're':
            r = it[1]
            if len(cur) > 2:
                subs.append(cur)
            subs.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)])
            cur, prev = [], None
    if len(cur) > 2:
        subs.append(cur)
    return subs


def _bitmap(subs, x0, y0):
    """Bitmapa znaku; diery ('O','A') vzniknu XOR-om obrysov (even-odd)."""
    acc = np.zeros((CELL, CELL), dtype=bool)
    for sp in subs:
        poly = [((x - x0) * PPP, (y - y0) * PPP) for x, y in sp]
        if max(p[0] for p in poly) > CELL or max(p[1] for p in poly) > CELL:
            return None
        img = Image.new('1', (CELL, CELL), 0)
        ImageDraw.Draw(img).polygon(poly, fill=1)
        acc ^= np.array(img, dtype=bool)
    im = Image.fromarray((acc * 255).astype('uint8'))
    return np.asarray(im.resize((SMALL, SMALL), Image.BILINEAR), dtype=np.float32) / 255.0


def glyphs(page):
    out = []
    for dr in page.get_drawings():
        if dr['type'] not in ('f', 'fs'):
            continue
        r = dr['rect']
        if not (0 < r.width <= MAXPT and 0 < r.height <= MAXPT):
            continue
        subs = _flatten(dr['items'])
        if not subs:
            continue
        b = _bitmap(subs, r.x0, r.y0)
        if b is None:
            continue
        out.append({'x': r.x0, 'x1': r.x1, 'y0': r.y0, 'y1': r.y1, 'bmp': b,
                    'subs': [[(round(x - r.x0, 3), round(y - r.y0, 3)) for x, y in sp] for sp in subs]})
    return out


def cluster(items, tol=1.6):
    if not items:
        return [], np.array([], dtype=int)
    V = np.stack([g['bmp'].ravel() for g in items])
    reps, labels = [], np.full(len(items), -1)
    for i in range(len(items)):
        if labels[i] >= 0:
            continue
        c = len(reps); reps.append(i)
        d = np.linalg.norm(V - V[i], axis=1)
        labels[np.where((d < tol) & (labels < 0))[0]] = c
    return reps, labels


# ---------- mapa znakov ----------

def save_map(items, reps, chars):
    """Ulozi OBRYSY vzorov, nie hotove bitmapy.

    Bitmapa zavisi od toho, cim sa kresli — python (PIL) a prehliadac (canvas)
    vyhladzuju inak. Keby sa ulozila bitmapa z pythonu a porovnavala s bitmapou
    z prehliadaca, cast znakov by sa trafila tesne vedla a vysledok by sa lisil
    stroj od stroja. Z obrysu si kazda strana vykresli vzor vlastnym rasterom,
    takze porovnava rovnake s rovnakym."""
    data = [{'ch': chars[c], 'subs': items[gi]['subs']}
            for c, gi in enumerate(reps) if chars.get(c)]
    json.dump(data, open(_mapfile(), 'w'), ensure_ascii=False)
    return len(data)


def load_map():
    mapfile = _mapfile()
    if not os.path.exists(mapfile):
        raise FileNotFoundError('Chýba mapa znakov: %s' % mapfile)
    data = json.load(open(mapfile, encoding='utf-8'))
    chars, vecs = [], []
    for d in data:
        b = _bitmap([[(x, y) for x, y in sp] for sp in d['subs']], 0.0, 0.0)
        if b is None:
            continue
        chars.append(d['ch']); vecs.append(b.ravel())
    return chars, np.array(vecs, dtype=np.float32)


def label_glyphs(items, chars, M, cutoff=1.9):
    """Kazdemu znaku najblizsi vzor; prilis vzdialene sa zahodia."""
    if not items:
        return [], 0
    V = np.stack([g['bmp'].ravel() for g in items])
    D = np.linalg.norm(V[:, None, :] - M[None, :, :], axis=2)
    j = D.argmin(axis=1); dmin = D.min(axis=1)
    out, dropped = [], 0
    for i, g in enumerate(items):
        if dmin[i] > cutoff:
            dropped += 1
            continue
        g = dict(g); g['ch'] = chars[j[i]]
        out.append(g)
    return out, dropped


# ---------- znaky -> bunky ----------

def cells(items, page_h, word_f=0.16, cell_f=0.42):
    """Zoskupi znaky do riadkov a buniek. Vystup ma y rastuce NAHOR (ako pdf.js)."""
    if not items:
        return []
    a = sorted(items, key=lambda g: (g['y1'], g['x']))
    pitch = _pitch([g['y1'] for g in a]) or 7.3
    rows, cur = [], [a[0]]
    for g in a[1:]:
        if abs(g['y1'] - cur[-1]['y1']) > 0.45 * pitch:
            rows.append(cur); cur = [g]
        else:
            cur.append(g)
    rows.append(cur)

    out = []
    for r in rows:
        r.sort(key=lambda g: g['x'])
        em = float(np.median([g['y1'] - g['y0'] for g in r])) / 0.72
        wt, ct, minadv = word_f * em, cell_f * em, 0.30 * em
        for g in r:
            g['xe'] = max(g['x1'], g['x'] + minadv) if g['ch'] in '1I.,l' else g['x1']
        cell = [r[0]]
        for i in range(1, len(r)):
            if r[i]['x'] - r[i - 1]['xe'] > ct:
                out.append(_mk(cell, wt, page_h)); cell = [r[i]]
            else:
                cell.append(r[i])
        out.append(_mk(cell, wt, page_h))
    return out


def _pitch(ys):
    u = sorted(set(round(y, 1) for y in ys))
    gaps = [b - a for a, b in zip(u, u[1:]) if b - a > 1.0]
    if len(gaps) < 3:
        return None
    gaps.sort()
    return gaps[len(gaps) // 2]


def _mk(cell, wt, page_h):
    s = cell[0]['ch']
    for i in range(1, len(cell)):
        if cell[i]['x'] - cell[i - 1]['xe'] > wt:
            s += ' '
        s += cell[i]['ch']
    x0 = cell[0]['x']
    return {'s': s, 'x': x0, 'y': page_h - cell[0]['y1'],
            'w': cell[-1]['x1'] - x0,
            'h': max(g['y1'] - g['y0'] for g in cell) / 0.72, 'rot': 0.0}


# ---------- hlavny beh ----------

def extract_bytes(data):
    """To iste ako extract(), ale zo suboru v pamati — pouziva to tools/server.py."""
    doc = fitz.open(stream=data, filetype='pdf')
    items, st = _extract_doc(doc)
    doc.close()
    return items, st


def _extract_doc(doc):
    items, glyphs_n, dropped = [], 0, 0
    chars, M = load_map()
    for pno in range(len(doc)):
        page = doc[pno]
        g = glyphs(page)
        lab, dr = label_glyphs(g, chars, M)
        items += cells(lab, page.rect.height)
        glyphs_n += len(g); dropped += dr
    return items, {'glyphs': glyphs_n, 'dropped': dropped, 'cells': len(items)}


def extract(path):
    doc = fitz.open(path)
    page = doc[0]
    g = glyphs(page)
    chars, M = load_map()
    lab, dropped = label_glyphs(g, chars, M)
    out = cells(lab, page.rect.height)
    doc.close()
    return out, {'glyphs': len(g), 'labelled': len(lab), 'dropped': dropped, 'cells': len(out)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf', nargs='*')
    ap.add_argument('-o', '--out', help='JSON s polozkami (inak sa vypise text)')
    ap.add_argument('--ref', help='vykres, z ktoreho sa nauci mapa znakov')
    ap.add_argument('--chars', help='JSON {index zhluku: znak} k --ref')
    a = ap.parse_args()

    if a.ref:
        doc = fitz.open(a.ref)
        g = glyphs(doc[0])
        reps, lab = cluster(g)
        if not a.chars:
            print('zhlukov: %d (bez --chars sa mapa neulozi)' % len(reps))
            return
        chars = {int(k): v for k, v in json.load(open(a.chars, encoding='utf-8')).items()}
        print('mapa ulozena, vzorov: %d' % save_map(g, reps, chars))
        return

    result = {}
    for p in a.pdf:
        items, st = extract(p)
        result[os.path.basename(p)] = items
        print('%-45s znakov %4d, nezaradenych %3d, buniek %4d'
              % (os.path.basename(p)[:45], st['glyphs'], st['dropped'], st['cells']))
    if a.out:
        json.dump(result, open(a.out, 'w'), ensure_ascii=False)
        print('JSON -> ' + a.out)
    else:
        for name, items in result.items():
            print('=== ' + name)
            for c in items:
                print('  %7.1f %6.1f  %s' % (c['y'], c['x'], c['s']))


if __name__ == '__main__':
    main()
