#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_legend.py — ORACLE: prečíta LEGENDU MIESTNOSTÍ z vektorového PDF pôdorysu
(RNDZ / EXPEDICIA) do štruktúry miestností a agreguje plochy pre ekonomiku.

Odolnosť voči trochu inej štruktúre tabuľky:
  - parser sa NEVIAŽE na presné poradie stĺpcov ani formát; ide stavovým automatom
    nad tokenmi a rozoznáva ich podľa VZORU (kód / plocha / hlavičkový popis / názov),
  - viacriadkové názvy sa akumulujú,
  - klasifikácia miestnosti je podľa KĽÚČOVÝCH SLOV v názve (nie podľa polohy),
  - hlavná poistka: náš súčet interiéru sa porovnáva s vytlačenou
    „PODLAHOVÁ PLOCHA CELKOVÁ" — ak sedí, parse je správny bez ohľadu na rozloženie.

Pravidlá projektu: half-up 2 desatiny; medzisúčet = súčet zaokrúhlených;
kľúč miestnosti = (blok, jednotka, číslo); typ jednotky z hlavičky.

Použitie:
  python3 tools/pdf_legend.py "EXPEDICIA 0.9_20-07-10/RNDZ_C_02_1NP-C.pdf"
  python3 tools/pdf_legend.py "EXPEDICIA 0.9_20-07-10/"RNDZ_C_*.pdf
  python3 tools/pdf_legend.py --json <pdf>        # strukturovaný výstup
"""
import sys, os, re, glob, json, unicodedata
import fitz  # PyMuPDF


def r2(x):
    if x is None:
        return 0.0
    s = -1 if x < 0 else 1
    return s * round(abs(x) * 100 + 1e-6) / 100.0

def deburr(s):
    s = unicodedata.normalize('NFD', s or '')
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper().strip()

def parse_area(s):
    t = (s or '').strip()
    if t in ('-', '–', ''):
        return None
    t = re.sub(r'[\s ]', '', t).replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None

# kód miestnosti: začína písmenom, obsahuje bodku, môže mať pomlčku (C.-1.01) a viacero
# segmentov (C.-1.S.22, Š.C.09). Bez medzier.
# Kód miestnosti/jednotky: začína písmenom ALEBO číslom (Krasnany má kódy s podlažím
# vpredu: 6.A.01, 6.A-V; RNDZ/SAR majú A.01, B1.3.A). Musí obsahovať bodku. Pomlčka je
# povolená aj v poslednom segmente (6.A-V). Negatívny lookahead vylúči podlažie z titulu
# (6.NP / 1.PP), aby sa nebralo ako kód. Čísla plôch chytá NUM_RE (guard ostáva).
#  - písmenom-začínajúci (A.01, B1.3.A, SO.01, K.1.01) — pôvodné správanie + pomlčka v tail,
#  - číslom-začínajúci LEN ak po prvej bodke nasleduje PÍSMENO jednotky (6.A.01, 6.A-V, 6.A).
#    Tým sa vylúčia čísla výkresov z rozpisky (1.04a → po bodke číslica) aj podlažie (6.NP guard).
CODE_RE = re.compile(r'^(?!\d+\.(?:NP|PP)$)(?:[A-Za-zŠš][\wŠš.\-]*\.[\wŠš\-]+|\d+\.[A-Za-zŠš][\wŠš.\-]*)$', re.I)
# plocha: "341,41", "90.08", "3 028,59", celé číslo, alebo pomlčka (bez plochy)
NUM_RE = re.compile(r'^[-–]$|^\d[\d\s ]*[,\.]\d+$|^\d[\d\s ]*$')

# anchor legendy — tolerantný voči OCR (napr. "LEGENDA MIESINOSTI" namiesto "MIESTNOSTÍ").
# "MIES" sa OCR-om číta spoľahlivo; "LEGENDA MATERIÁLOV" cez MIES neprejde.
LEGEND_RE = re.compile(r'LEGENDA\s+MIES', re.I)

HEADER_KEYS = [deburr(x) for x in [
    'LEGENDA MIESTNOSTI', 'PLOCHA / M2', 'PLOCHA/M2', 'UPRAVY POVRCHOV', 'C.M.',
    'NAZOV MIESTNOSTI', 'MIESTN.', 'PODLAHA', 'STENY', 'STROP', 'PODHLAD']]
def is_header(tok):
    # Pozor: samotné „BALKÓN" je aj STĹPEC hlavičky aj NÁZOV miestnosti (balkón).
    # Preto ho NEpovažujeme za hlavičku — v hlavičkovom bloku sa aj tak zahodí
    # (nemá pred sebou kód), a ako názov miestnosti sa správne zachytí.
    d = deburr(tok)
    return any(k in d for k in HEADER_KEYS)

EXT_KEYS = ['BALKON', 'LODZIA', 'TERASA', 'PREDZAHRADKA']
TECH_KEYS = ['TECHNICK', 'VYMENNIK', 'NEBYTOVY', 'STROJOVN', 'ROZVODN', 'KOTOLN',
             'TRAFO', 'ELEKTRO', 'UPRATOVAC', 'ODPAD']
GARAZ_KEYS = ['GARAZ', 'PARKOVISKO', 'PARKOVANIE', 'RAMPA', 'STATIE', 'STANIE']
SKLAD_KEYS = ['SKLAD', 'KOBKA', 'PIVNICA']

def is_exterior(name):
    d = deburr(name)
    return any(k in d for k in EXT_KEYS)

def classify(code, name):
    dn = deburr(name)
    if 'OBCHODNY PRIESTOR' in dn:
        return 'OP'
    if any(k in dn for k in TECH_KEYS):
        return 'TECH'
    if any(k in dn for k in GARAZ_KEYS):
        return 'GARAZ'
    if '.S.' in deburr(code) or any(k in dn for k in SKLAD_KEYS):
        return 'SKLAD'
    return 'ROOM'

def unit_type_from_header(name):
    d = deburr(name)
    if d.startswith('BYT'):
        return 'BYT'
    if d.startswith('APARTMAN'):
        return 'APARTMAN'
    if d.startswith('STUDIO'):
        return 'STUDIO'
    return None


def parse_legend(page_text):
    """Stavový automat nad tokenmi. Vráti rooms[], units{}, floorTotalPrinted."""
    _m = LEGEND_RE.search(page_text)
    i = _m.start() if _m else -1
    if i < 0:
        return None
    toks = [ln.strip() for ln in page_text[i:].splitlines() if ln.strip() != '']

    rooms, units = [], {}
    cur_unit = None
    floor_total = None
    pend_code, pend_name = None, []

    def flush_as_header():
        # čakajúci kód, ktorý nedostal plochu → hlavička jednotky (ak názov sedí)
        nonlocal cur_unit
        if pend_code is None:
            return
        nm = ' '.join(pend_name).strip()
        ut = unit_type_from_header(nm)
        if ut:
            units[pend_code] = {'code': pend_code, 'type': ut, 'name': nm}
            cur_unit = pend_code
        else:
            # kód bez plochy a bez typu jednotky (napr. len značka) — miestnosť bez plochy
            rooms.append(_mk_room(pend_code, nm, None))

    def _mk_room(code, name, area):
        kind = classify(code, name)
        unit_for = cur_unit
        if kind == 'OP':
            unit_for = code
            units[code] = {'code': code, 'type': 'OBCHODNY PRIESTOR', 'name': name}
        elif kind in ('SKLAD', 'GARAZ', 'TECH'):
            unit_for = None
        return {'code': code, 'name': name, 'area': area,
                'exterior': is_exterior(name), 'unit': unit_for, 'kind': kind}

    for t in toks:
        du = deburr(t)
        if du.startswith('PODLAHOVA PLOCHA'):
            flush_as_header(); pend_code, pend_name = None, []
            _pending_total[0] = 'CELKOVA' if 'CELKOVA' in du else 'SUB'
            continue
        # „PODLAHOVÁ PLOCHA" [„CELKOVÁ"] <číslo> — CELKOVÁ býva samostatný token
        if _pending_total[0] is not None:
            if du == 'CELKOVA':
                _pending_total[0] = 'CELKOVA'; continue
            if NUM_RE.match(t) and not CODE_RE.match(t):
                if _pending_total[0] == 'CELKOVA':
                    # na jednom hárku býva viac legiend vedľa seba → sčítaj všetky CELKOVÉ
                    v = parse_area(t)
                    if v is not None:
                        floor_total = (floor_total or 0) + v
                _pending_total[0] = None; continue
            _pending_total[0] = None   # nie číslo → koniec medzisúčtu, spracuj token ďalej
        if is_header(t):
            continue
        if CODE_RE.match(t) and not NUM_RE.match(t):
            flush_as_header()
            pend_code, pend_name = t, []
            continue
        if NUM_RE.match(t):
            if pend_code is not None:
                rooms.append(_mk_room(pend_code, ' '.join(pend_name).strip(), parse_area(t)))
                pend_code, pend_name = None, []
            continue
        # názvový fragment
        if pend_code is not None:
            pend_name.append(t)
    flush_as_header()
    return {'rooms': rooms, 'units': units, 'floorTotalPrinted': floor_total}

_pending_total = [None]  # malý stavový príznak pre „PODLAHOVÁ PLOCHA <num>"


def aggregate(parsed):
    rooms, units = parsed['rooms'], parsed['units']
    b = {'resiInterior': 0.0, 'resiExterior': 0.0, 'obchodInterior': 0.0,
         'skladInterior': 0.0, 'garazInterior': 0.0, 'spolocne': 0.0}
    interior = 0.0
    for r in rooms:
        if r['area'] is None:
            continue
        a = r2(r['area'])
        if not r['exterior']:
            interior += a
        u = units.get(r['unit']) if r['unit'] else None
        if r['kind'] == 'OP':
            b['obchodInterior'] += a
        elif r['kind'] == 'SKLAD':
            b['skladInterior'] += a
        elif r['kind'] == 'GARAZ':
            b['garazInterior'] += a
        elif u and u['type'] in ('BYT', 'APARTMAN', 'STUDIO'):
            b['resiExterior' if r['exterior'] else 'resiInterior'] += a
        else:
            if not r['exterior']:
                b['spolocne'] += a
    for k in b:
        b[k] = r2(b[k])
    return b, r2(interior)


def extract_meta(text):
    """Vytiahne údaje z rozpisky (rohovej pečiatky). Robustné aj pre OCR (deburr).
    Kľúčové: PODLAŽIE z „PÔDORYS X.NP", SO objekt, blok, parcely."""
    d = deburr(re.sub(r'\s+', ' ', text or ''))     # jednoriadkovo, bez diakritiky
    meta = {'floorName': None, 'levels': [], 'block': None, 'so': None,
            'parcels': None, 'projekt': None, 'miesto': None, 'ku': None, 'datum': None}
    # katastrálne územie z rozpisky: „k.ú. RAČA" → ku 'RACA' (na prednaplnenie katastra)
    m = re.search(r'\bK\.?\s*U\.?\s+([A-Z0-9][A-Z0-9 \-]{1,35}?)'
                  r'(?=\s{2,}|[,;]|\bBLOK\b|\bSO\b|\bMIERKA\b|\bDATUM\b|\bP\.?\s*C\b|\bPARC\b|$)', d)
    if m: meta['ku'] = re.sub(r'\s+', ' ', m.group(1)).strip()
    # miesto (obec) pred „k.ú.": „BRATISLAVA - RAČA, k.ú. …" → 'BRATISLAVA - RACA'
    m = re.search(r'\b([A-Z]{3,}(?:\s*-\s*[A-Z]{3,})?)\s*,?\s*K\.?\s*U\.?\s', d)
    if m: meta['miesto'] = re.sub(r'\s+', ' ', m.group(1)).strip()
    # OCR vie pred „k.ú." zachytiť názov susedného poľa (najmä „POZEM") namiesto obce.
    # Takýto presvedčivo vyzerajúci, ale neplatný údaj radšej necháme na potvrdenie používateľovi.
    if meta['miesto'] in {'POZEM', 'PARCELA', 'STAVBA', 'OBJEKT', 'INVESTOR', 'MIESTO'}:
        meta['miesto'] = None
    # PODLAŽIE — „PODORYS 4.NP, 6.NP" → [4,6] → floorName "4+6NP"
    m = re.search(r'PODORYS[^0-9]{0,6}((?:\d+\s*\.?\s*(?:NP|PP)[,\s]*)+)', d)
    if m:
        pairs = re.findall(r'(\d+)\s*\.?\s*(NP|PP)', m.group(1))
        if pairs:
            sgn = -1 if pairs[0][1] == 'PP' else 1
            meta['levels'] = [sgn * int(n) for n, _ in pairs]
            meta['floorName'] = '+'.join(str(abs(x)) for x in meta['levels']) + ('PP' if sgn < 0 else 'NP')
    m = re.search(r'\bSO[\s\-]?(\d{2,3})\b', d)                 # OBJEKT SO-103
    if m: meta['so'] = m.group(1)
    m = re.search(r'\bBLOK\s+([A-Z0-9]{1,3})\s*[:.]', d)        # BLOK C:
    if m: meta['block'] = m.group(1)
    m = re.search(r'\bP\.?\s*C\.?\s*([0-9][0-9/,\s]{4,})', d)   # p.č. 4757/4, ...
    if m: meta['parcels'] = re.sub(r'\s+', ' ', m.group(1)).strip().strip(',').strip()
    m = re.search(r'(\b[A-Z]{2,}\s*-\s*KOMPLEX[A-Z ]*?)(?=\s+BLOK|\s{2}|$)', d)   # RNDZ - Komplex…
    if m: meta['projekt'] = m.group(1).strip().title()
    m = re.search(r'\b(0?\d)\s*[/.]\s*(20\d\d)\b', d)           # dátum 07/2020
    if m: meta['datum'] = '%s/%s' % (m.group(1), m.group(2))
    return meta


def _process_doc(doc, fname):
    tot = {'resiInterior': 0.0, 'resiExterior': 0.0, 'obchodInterior': 0.0,
           'skladInterior': 0.0, 'garazInterior': 0.0, 'spolocne': 0.0}
    interior = printed = 0.0
    units = res = rooms = 0
    any_leg = False
    for pno in range(len(doc)):
        _pending_total[0] = None
        parsed = parse_legend(doc[pno].get_text('text'))
        if not parsed:
            continue
        any_leg = True
        b, intr = aggregate(parsed)
        for k in tot:
            tot[k] += b[k]
        interior += intr
        if parsed['floorTotalPrinted'] is not None:
            printed += parsed['floorTotalPrinted']
        units += len(parsed['units']); rooms += len(parsed['rooms'])
        res += sum(1 for u in parsed['units'].values() if u['type'] in ('BYT', 'APARTMAN', 'STUDIO'))
    if not any_leg:
        return {'file': fname, 'ok': False, 'note': 'legenda nenájdená'}
    for k in tot:
        tot[k] = r2(tot[k])
    printed = r2(printed) if printed else None
    diff = None if printed is None else r2(r2(interior) - printed)
    return {'file': fname, 'ok': True, 'units': units, 'residential': res, 'rooms': rooms,
            'interiorSum': r2(interior), 'printedTotal': printed, 'diff': diff, 'buckets': tot}

def process(path):
    return _process_doc(fitz.open(path), os.path.basename(path))

def process_stream(data, fname='pdf'):
    return _process_doc(fitz.open(stream=data, filetype='pdf'), fname)


# ---- generátor syntetickej CSV legendy (formát appky) -----------------------
# PDF sa premení na CSV, akú appka bežne načíta → prejde rovnakým pipeline
# (AnalyzaCore.buildModel) a naplní CELÚ analýzu, nielen ekonomiku. Kategórie,
# jednotky aj sklady/garáže si appka odvodí sama z názvov a poradia.

def _fnum(v):
    return '' if v is None else ('%.2f' % v).replace('.', ',')

def _block_of(toks):
    for t in toks:
        if CODE_RE.match(t) and not NUM_RE.match(t):
            seg = deburr(t).split('.')[0]
            return seg or None
    return None

def legend_to_csv_page(page_text):
    """Jedna strana → riadky CSV (bez hlavičky). Vráti (rows, block) alebo (None,None)."""
    _m = LEGEND_RE.search(page_text)
    i = _m.start() if _m else -1
    if i < 0:
        return None, None
    toks = [ln.strip() for ln in page_text[i:].splitlines() if ln.strip() != '']
    block = _block_of(toks)
    so = None
    m = re.search(r'\bSO[\s\-]?(\d{2,3})\b', page_text)
    if m:
        so = m.group(1)
    rows = []
    if block:
        rows.append(';"  BLOK ""%s"" - SO %s";;;;;' % (block, so or ''))
    pend = None; pname = []; pt = None; celk = 0.0; any_celk = False
    # Za koncom legendy býva pomocná tabuľka (kľúč bytov / schéma šácht) — bare hlavičky
    # bytov/apartmánov BEZ medzisúčtu. Reálna jednotka bez vlastnej plochy má vždy
    # „PODLAHOVÁ PLOCHA" medzisúčet → hlavičku bez neho na konci zahodíme (fantóm).
    unit_hdr_rows = []      # indexy riadkov s bare hlavičkou jednotky
    valid_units = set()     # indexy hlavičiek, po ktorých prišiel medzisúčet

    def _q(s):
        return str(s).replace('"', '""')          # escape úvodzoviek v CSV poli

    def emit_room(code, name, area):
        # OCR vracia hrubé boxy (celý riadok tabuľky = 1 box) → plocha „5,24 m²" ostane v NÁZVE.
        # Ak miestnosť nemá plochu, ale v názve je „<číslo>,<číslo> m²", vytiahni ju a názov skráť.
        if area is None and name:
            m = re.search(r'(\d+[,\.]\d+)\s*m', name)
            if m:
                area = parse_area(m.group(1))
                name = name[:m.start()].strip() or name
        # OCR šum z rohovej pečiatky (projektant/investor…) = dlhý názov BEZ plochy → zahoď
        if area is None and len(name.strip()) > 45:
            return
        ext = is_exterior(name)
        av = _fnum(area)
        intc = '' if ext else av
        extc = av if ext else ''
        rows.append('"%s";"  %s";"%s";"%s";;;' % (_q(code), _q(name), intc, extc))

    def flush():
        if pend is None:
            return
        nm = ' '.join(pname).strip()
        if unit_type_from_header(nm):
            rows.append('"%s";"  %s";;;;;' % (_q(pend), _q(nm)))   # hlavička jednotky
            unit_hdr_rows.append(len(rows) - 1)
        else:
            emit_room(pend, nm, None)

    for t in toks:
        du = deburr(t)
        if du.startswith('PODLAHOVA PLOCHA'):
            flush(); pend = None; pname = []
            pt = 'C' if 'CELKOVA' in du else 'S'
            continue
        if pt is not None:
            if du == 'CELKOVA':
                pt = 'C'; continue
            if NUM_RE.match(t) and not CODE_RE.match(t):
                v = parse_area(t)
                if pt == 'C':
                    if v is not None:
                        celk += v; any_celk = True
                else:
                    rows.append(';"  PODLAHOVA PLOCHA";"%s";;;;' % _fnum(v))   # medzisúčet jednotky
                    if unit_hdr_rows:
                        valid_units.add(unit_hdr_rows[-1])   # medzisúčet potvrdzuje poslednú hlavičku
                pt = None; continue
            pt = None
        if is_header(t):
            continue
        if CODE_RE.match(t) and not NUM_RE.match(t):
            flush(); pend = t; pname = []
            continue
        if NUM_RE.match(t):
            if pend is not None:
                emit_room(pend, ' '.join(pname).strip(), parse_area(t))
                pend = None; pname = []
            continue
        if pend is not None:
            pname.append(t)
    flush()
    # zahoď fantómové hlavičky jednotiek (bez medzisúčtu) z pomocnej tabuľky za legendou
    drop = set(unit_hdr_rows) - valid_units
    if drop:
        rows = [r for i, r in enumerate(rows) if i not in drop]
    if any_celk:
        rows.append(';"  PODL. PLOCHA CELKOVA";"%s";;;;' % _fnum(r2(celk)))
    return rows, block

_CSV_HEAD = ['"  LEGENDA MIESTNOSTI";;"PLOCHA / M2";;"UPRAVY POVRCHOV";;',
             '"C.M.";"NAZOV MIESTNOSTI";"INTERIER";"EXTERIER";"PODLAHA";"STENY";"STROP / PODHLAD"']

def to_app_csv(data, fname='pdf'):
    """Vektorové PDF (bytes) → text CSV legendy pre appku (všetky strany spojené).
    Obrázok/sken (bez textovej vrstvy) vráti None → volajúci skúsi OCR cestu."""
    try:
        doc = fitz.open(stream=data)          # auto-detekcia (PDF aj obrázky)
    except Exception:
        return None
    body = []
    for pno in range(len(doc)):
        rows, _ = legend_to_csv_page(doc[pno].get_text('text'))
        if rows:
            body += rows
    if not body:
        return None
    return '\r\n'.join(_CSV_HEAD + body) + '\r\n'


# ---- OCR cesta (sken / obrázok bez textovej vrstvy) -------------------------
# Poradie textu sa zrekonštruuje z polohovaných OCR položiek (pásma + riadky),
# potom ide cez ten istý parser ako vektor. Poistka: kontrola CELKOVEJ v appke.

def _to_rows_tokens(items):
    a = sorted(items, key=lambda it: (-it.get('y', 0), it.get('x', 0)))
    rows = []
    cur = None
    for it in a:
        tol = max(2.0, (it.get('h') or 8) * 0.6)
        if cur is None or abs(cur['y'] - it.get('y', 0)) > tol:
            cur = {'y': it.get('y', 0), 'cells': [it]}
            rows.append(cur)
        else:
            cur['cells'].append(it)
    toks = []
    for r in rows:
        for c in sorted(r['cells'], key=lambda it: it.get('x', 0)):
            s = (c.get('s') or '').strip()
            if s:
                toks.append(s)
    return toks

def _legend_regions(items):
    """Priestorovo oreže KAŽDÚ legendu z celého (naskenovaného) hárku:
    x-pás od kotvy „LEGENDA MIESTNOSTÍ" po ďalšiu kotvu, y od kotvy nadol po jej „CELKOVÁ".
    Tým vypadne výkres (vľavo), rohová pečiatka (dole) aj legenda materiálov."""
    anchors = sorted([it for it in items if LEGEND_RE.search(it.get('s', ''))],
                     key=lambda a: a.get('x', 0))
    if not anchors:
        return []
    sheet_w = max((it.get('x', 0) for it in items), default=1000)
    regions = []
    for k, a in enumerate(anchors):
        ax, ay = a.get('x', 0), a.get('y', 0)
        x_lo = ax - 20
        # šírka legendy je obmedzená (aby nepohltila legendu materiálov / pravú časť hárku)
        x_cap = ax + 0.40 * sheet_w
        x_hi = min(anchors[k + 1].get('x', 0) - 20, x_cap) if k + 1 < len(anchors) else x_cap
        col = [it for it in items if x_lo <= it.get('x', 0) < x_hi and it.get('y', 0) <= ay + 3]
        cels = [it.get('y', 0) for it in col if re.search(r'CELKOV', deburr(it.get('s', '')))]
        y_bot = min(cels) if cels else None       # y rastie hore → spodok = najmenšie y
        band = [it for it in col if (y_bot is None or it.get('y', 0) >= y_bot - 4)]
        regions.append(band)
    return regions

def _items_to_text(items):
    its = [it for it in items if (it.get('s') or '').strip()]
    lines = []
    for region in _legend_regions(its):
        lines += _to_rows_tokens(region)
    return '\n'.join(lines)

def meta_from_data(data):
    """Rozpiska z vektorového PDF (text všetkých strán)."""
    try:
        doc = fitz.open(stream=data)
        text = ' '.join(doc[p].get_text('text') for p in range(len(doc)))
        doc.close()
        return extract_meta(text)
    except Exception:
        return None

def to_app_csv_ocr(items, fname='pdf'):
    """OCR položky (jedna strana/obrázok) → text CSV legendy, alebo None."""
    text = _items_to_text(items or [])
    if not LEGEND_RE.search(text):
        return None
    rows, _ = legend_to_csv_page(text)
    if not rows:
        return None
    return '\r\n'.join(_CSV_HEAD + rows) + '\r\n'


def main(argv):
    as_json = False
    if argv and argv[0] == '--json':
        as_json = True; argv = argv[1:]
    paths = []
    for a in argv:
        paths.extend(sorted(glob.glob(a)) if any(c in a for c in '*?[') else [a])
    if not paths:
        print('Použitie: pdf_legend.py [--json] <pdf> [pdf...]'); return 1
    if as_json:
        out = []
        for p in paths:
            r = process(p); r.pop('parsed', None); out.append(r)
        print(json.dumps(out, ensure_ascii=False, indent=1)); return 0
    total = {'resiInterior': 0.0, 'resiExterior': 0.0, 'obchodInterior': 0.0,
             'skladInterior': 0.0, 'garazInterior': 0.0, 'spolocne': 0.0}
    for p in paths:
        r = process(p)
        if not r.get('ok'):
            print('%-34s  %s' % (r['file'], r.get('note'))); continue
        chk = 'OK' if (r['diff'] is not None and abs(r['diff']) < 0.02) else \
              ('Δ%+.2f' % r['diff'] if r['diff'] is not None else 'bez CELKOVEJ')
        print('%-34s jedn=%2d (byv=%2d) miest=%3d  interiér=%9.2f  CELKOVÁ=%9s  %s'
              % (r['file'], r['units'], r['residential'], r['rooms'], r['interiorSum'],
                 ('%.2f' % r['printedTotal']) if r['printedTotal'] is not None else '—', chk))
        for k in total:
            total[k] += r['buckets'][k]
    print('-' * 96)
    print('AGREGÁT pre ekonomiku (súčet súborov, bez násobičov opakovaných podlaží):')
    for k, v in total.items():
        print('   %-16s %12.2f m²' % (k, r2(v)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
