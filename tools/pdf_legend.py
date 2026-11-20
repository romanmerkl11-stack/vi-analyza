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
#  - spoločný blok pred prvou jednotkou (IC: 4B.00 VÝŤAHOVÁ ŠACHTA, 4B.01 SCHODISKO...) má kód
#    "blok+číslo" = číslice+písmená.bodka.číslo (4B.00) — inak by sa celý blok zahodil.
CODE_RE = re.compile(r'^(?!\d+\.(?:NP|PP)$)(?:[A-Za-zŠš][\wŠš.\-]*\.[\wŠš\-]+|\d+\.[A-Za-zŠš][\wŠš.\-]*|\d+[A-Za-zŠš]+\.[\wŠš\-]+)$', re.I)
# plocha: "341,41", "90.08", "3 028,59", celé číslo, alebo pomlčka (bez plochy)
NUM_RE = re.compile(r'^[-–]$|^\d[\d\s ]*[,\.]\d+$|^\d[\d\s ]*$')

# holý číselný kód miestnosti bez písmena bloku (napr. "1.01", "2.05", "1.1") — niektoré
# projekty (Nové Šúty II) takto značia SPOLOČNÉ priestory (schodiská, sklady) a bez tejto
# vetvy ticho vypadávajú (CODE_RE ich odmieta, NUM_RE ich naopak chytí ako číslo → token sa
# minie so správnym pend_code a celá miestnosť sa zahodí). Úmyselne BEZ voliteľného písmena
# na konci (na rozdiel od CODE_RE) — aby sa nenachytilo číslo VÝKRESU použité ako referencia
# v texte pečiatky/schémy (napr. "1.04a"). CODE_RE ostáva NEZMENENÝ (nulové riziko pre
# _scan_total a _block_of, ktoré sa naň spoliehajú) — rozpoznanie je čisto KONTEXTOVÉ, pozri
# _looks_like_room_name nižšie: berie sa ako kód len keď ho nasleduje token vyzerajúci ako
# NÁZOV a keď sa nečaká plocha k predošlému kódu (pend_code/pend is None).
BARE_NUM_CODE_RE = re.compile(r'^\d+\.\d+$')

# anchor legendy — tolerantný voči OCR (napr. "LEGENDA MIESINOSTI" namiesto "MIESTNOSTÍ").
# "MIES" sa OCR-om číta spoľahlivo; "LEGENDA MATERIÁLOV" cez MIES neprejde.
LEGEND_RE = re.compile(r'LEGENDA\s+MIES', re.I)

# kontrolný súčet — „PODLAHOVÁ PLOCHA CELKOVÁ". OCR niekedy zlepí slová bez medzery
# ("PODLAHOVAPLOCHA"), preto \s* namiesto pevnej medzery. Rovnaký anchor pokrýva aj
# medzisúčet BEZ „CELKOVÁ" (PODLAHOVÁ PLOCHA <jednotky>) — ten sa nesčítava do floor_total.
_TOTAL_ANCHOR_RE = re.compile(r'^PODLAHOVA\s*PL')
# alternatívny per-jednotkový súčet zo sken. legiend (Nové Šúty): „Spolu (Užitková plocha)
# BYT - X.Y.Z :". NIE je plošná CELKOVÁ (chýbajú spoločné priestory) → nesčítava sa do
# floor_total, len sa zapíše ako medzisúčet jednotky (rovnako ako PODLAHOVÁ PLOCHA bez CELKOVÁ).
_UNIT_TOTAL_RE = re.compile(r'^SPOLU\b.*UZITKOVA\s*PLOCHA')


def _scan_total(toks, i, window=5):
    """Od anchor-tokenu na indexe i (PODLAHOVÁ PLOCHA / SPOLU...UŽITKOVÁ PLOCHA) nájdi v
    nasledujúcich `window` tokenoch prvé číslo (plocha) a či sa medzi nimi vyskytuje
    „CELKOVÁ". Poradie NEpredpokladáme — pri OCR sken (zalomenie riadku inak než vo
    vektore) vie číslo vyjsť PRED slovom CELKOVÁ. Vráti (value, is_celkova, next_i)."""
    is_celkova = False
    val = None
    j = i + 1
    end = min(len(toks), i + 1 + window)
    while j < end:
        du = deburr(toks[j])
        if du == 'CELKOVA':
            is_celkova = True
            j += 1
            continue
        if val is None and NUM_RE.match(toks[j]) and not CODE_RE.match(toks[j]):
            val = parse_area(toks[j])
            j += 1
            continue
        break
    return val, is_celkova, j

HEADER_KEYS = [deburr(x) for x in [
    'LEGENDA MIESTNOSTI', 'PLOCHA / M2', 'PLOCHA/M2', 'UPRAVY POVRCHOV', 'C.M.',
    'NAZOV MIESTNOSTI', 'MIESTN.', 'PODLAHA', 'STENY', 'STROP', 'PODHLAD']]
def is_header(tok):
    # Pozor: samotné „BALKÓN" je aj STĹPEC hlavičky aj NÁZOV miestnosti (balkón).
    # Preto ho NEpovažujeme za hlavičku — v hlavičkovom bloku sa aj tak zahodí
    # (nemá pred sebou kód), a ako názov miestnosti sa správne zachytí.
    d = deburr(tok)
    return any(k in d for k in HEADER_KEYS)

def _looks_like_room_name(tok):
    """Kontextová poistka pre BARE_NUM_CODE_RE: holý číselný kód (napr. "1.01") sa berie
    ako kód miestnosti len vtedy, keď ho nasleduje token vyzerajúci ako NÁZOV — nie číslo
    (plocha), nie hlavička stĺpca a nie kotva súčtu. Bez tejto poistky by sa dalo nesprávne
    "rozbehnúť" parsovanie na hocijakom čísle v tvare X.Y mimo skutočnej tabuľky miestností."""
    if not tok:
        return False
    if NUM_RE.match(tok) or is_header(tok):
        return False
    du = deburr(tok)
    if _TOTAL_ANCHOR_RE.match(du) or _UNIT_TOTAL_RE.match(du):
        return False
    return True

def _bare_code_is_room(toks, i, window=6):
    """Druhá (prísnejšia) poistka pre BARE_NUM_CODE_RE: samotné „nasleduje názvový token"
    nestačí — text pečiatky/titulu vie vyzerať ako názov (napr. „1.01 PÔDORYS 1PP 4xA4",
    „02.11 PÔDORYS - 10.NP-LEGENDA" — reálne overené fantómy z Krasnany a IC1, obe BEZ
    plochy). Preto vyžadujeme, aby v najbližších `window` tokenoch po kóde skutočne prišlo
    ČÍSLO (plocha) skôr, než sa narazí na ďalší kód / kotvu súčtu / hlavičku stĺpca — presne
    tak, ako to pri reálnej miestnosti (kód+názov+plocha) urobí aj samotný stavový automat."""
    n = len(toks)
    j = i + 1
    if j >= n or not _looks_like_room_name(toks[j]):
        return False
    end = min(n, i + 1 + window)
    while j < end:
        tok = toks[j]
        if NUM_RE.match(tok):
            return True
        du = deburr(tok)
        if is_header(tok) or _TOTAL_ANCHOR_RE.match(du) or _UNIT_TOTAL_RE.match(du):
            return False
        if CODE_RE.match(tok) or BARE_NUM_CODE_RE.match(tok):
            return False
        j += 1
    return False

# LOGGIA (tal. písanie) a ZÁHRADA sú exteriér — parita s appkou (roomCategory). Bez nich
# končila plocha loggie v INTERIÉRI (napr. IC 4NP: 14× loggia zle v interiéri).
# Parita s appkou (AnalyzaCore.roomCategory EXTERIÉR): závetrie/strecha/loggia sa NErátajú
# do podlahovej plochy. ZAVETRIE chýbalo → Krasnany 1NP mal +21,2 (závetrie zle v interiéri).
EXT_KEYS = ['BALKON', 'LODZIA', 'LOGGIA', 'LOGGA', 'TERASA', 'PREDZAHRADKA', 'ZAHRAD',
            'ZAVETRIE', 'STRECHA']
TECH_KEYS = ['TECHNICK', 'VYMENNIK', 'NEBYTOVY', 'STROJOVN', 'ROZVODN', 'KOTOLN',
             'TRAFO', 'ELEKTRO', 'UPRATOVAC', 'ODPAD']
GARAZ_KEYS = ['GARAZ', 'PARKOVISKO', 'PARKOVANIE', 'RAMPA', 'STATIE', 'STANIE']
SKLAD_KEYS = ['SKLAD', 'KOBKA', 'PIVNICA']

def is_exterior(name):
    d = deburr(name)
    return any(k in d for k in EXT_KEYS)

# Do názvu miestnosti niekedy pretečie text zo susednej schémy / pečiatky (Krasnany):
#  - VÝKAZ OKIEN/DVERÍ: „W1B W1B W1A ZK4a ZK6 …" (séria element-kódov),
#  - BLOKOVÁ SCHÉMA: „A B C D E F G H I J K L M" (séria jednopísmenových blokov),
#  - TEXT PEČIATKY: „… DÁTUM: HLAVNÝ PROJEKTANT: MIERKA: …".
# Reálny názov miestnosti nič z toho nie je → zahoď.
_STAMP_KW = ['DATUM', 'PROJEKTANT', 'VYPRACOVAL', 'MIERKA', 'STUPEN', 'FORMAT', 'REVIZIA',
             'INVESTOR', 'NAZOV STAVBY', 'NAZOV VYKRESU', 'CISLO VYKRESU', 'SPRACOVAL', 'ZODPOVED']
def _is_schedule_noise(name):
    if any(k in deburr(name) for k in _STAMP_KW):        # text pečiatky
        return True
    toks = name.split()
    if len(toks) < 3:
        return False
    codes = sum(1 for t in toks if re.match(r'^[A-Za-zŠČšč]{1,3}\d', t))
    if codes >= 3 and codes >= 0.5 * len(toks):          # výkaz okien/dverí
        return True
    singles = sum(1 for t in toks if len(t) <= 2)
    if singles >= 4 and singles >= 0.7 * len(toks):      # bloková schéma A B C D …
        return True
    return False

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

    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        du = deburr(t)
        # „PODLAHOVÁ PLOCHA" [„CELKOVÁ"] <číslo> — poradie CELKOVÁ/číslo nepredpokladáme
        # (OCR sken vie zalomiť riadok inak než vektor a vydať číslo pred slovom CELKOVÁ).
        if _TOTAL_ANCHOR_RE.match(du) or _UNIT_TOTAL_RE.match(du):
            flush_as_header(); pend_code, pend_name = None, []
            anchor_celkova = 'CELKOVA' in du
            is_unit_total = bool(_UNIT_TOTAL_RE.match(du))
            v, more_celkova, i = _scan_total(toks, i)
            # per-jednotkový súčet (Nové Šúty „Spolu…") NIE JE plošná CELKOVÁ → nesčítava sa
            if v is not None and not is_unit_total and (anchor_celkova or more_celkova):
                # na jednom hárku býva viac legiend vedľa seba → sčítaj všetky CELKOVÉ
                floor_total = (floor_total or 0) + v
            continue
        if is_header(t):
            i += 1; continue
        if CODE_RE.match(t) and not NUM_RE.match(t):
            flush_as_header()
            pend_code, pend_name = t, []
            i += 1; continue
        # holý číselný kód (spoločné priestory bez písmena bloku, napr. Nové Šúty II
        # "1.01 SCHODISKO ...") — len keď NEčakáme plochu k predošlému kódu a keď kód
        # skutočne dostane názov+plochu (pozri _bare_code_is_room).
        if pend_code is None and BARE_NUM_CODE_RE.match(t) and _bare_code_is_room(toks, i):
            pend_code, pend_name = t, []
            i += 1; continue
        if NUM_RE.match(t):
            if pend_code is not None:
                nm = ' '.join(pend_name).strip()
                # kód + plocha, ale BEZ názvu = fantóm zo schémy/pečiatky za legendou
                # (reálna miestnosť má vždy názov) — napr. RNDZ B2: „B2.3.C 60,00", „B.05 3,00"
                # alebo názov = výkaz okien (Krasnany „W1B ZK4a …")
                if nm and not _is_schedule_noise(nm):
                    rooms.append(_mk_room(pend_code, nm, parse_area(t)))
                pend_code, pend_name = None, []
            i += 1; continue
        # názvový fragment
        if pend_code is not None:
            pend_name.append(t)
        i += 1
    flush_as_header()
    return {'rooms': rooms, 'units': units, 'floorTotalPrinted': floor_total}


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
    # katastrálne územie z rozpisky: „k.ú. RAČA" (RNDZ) aj „katastrálne územie Trnávka" (IC)
    # → ku 'RACA'/'TRNAVKA' (na prednaplnenie katastra + konkurencie)
    m = re.search(r'\b(?:K\.?\s*U\.?|KATASTR\w*\s+UZEMIE)\s+([A-Z0-9][A-Z0-9 \-]{1,35}?)'
                  r'(?=\s{2,}|[,;]|\bOBEC\b|\bBLOK\b|\bSO\b|\bMIERKA\b|\bDATUM\b|\bP\.?\s*C\b|\bPARC\b|$)', d)
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
    # parcely: „p.č. 4757/4" (RNDZ) aj „parcela č.15850/188" (IC) — deburr → P.C. / PARCELA C.
    m = re.search(r'\b(?:P|PARCEL[AY]?)\.?\s*C\.?\s*([0-9][0-9/,\s]{4,})', d)
    if m: meta['parcels'] = re.sub(r'\s+', ' ', m.group(1)).strip().strip(',').strip()
    m = re.search(r'(\b[A-Z]{2,}\s*-\s*KOMPLEX[A-Z ]*?)(?=\s+BLOK|\s{2}|$)', d)   # RNDZ - Komplex…
    if m: meta['projekt'] = m.group(1).strip().title()
    m = re.search(r'\b(0?\d)\s*[/.]\s*(20\d\d)\b', d)           # dátum 07/2020
    if m: meta['datum'] = '%s/%s' % (m.group(1), m.group(2))
    return meta


# ---- POLOHOVÉ čítanie legendy (stĺpce „Č.M.", riadky podľa polohy znakov) -------
# get_text('text') vracia text v poradí streamu. V exportoch z DWG (Gerlach II) majú slová
# jedného riadku legendy rozdielny `top` (0,6–2 pt) a znaky susedných riadkov sa premiešajú
# („3.04" / „3.05" → „3", „.", „0", „4"). Preto sa legenda skladá z POLOHY znakov:
#   1) slová zo znakov (len vodorovné): riadok = round(top*2)/2, nové slovo pri medzere
#      > max(1, 0,25·veľkosť písma),
#   2) stĺpec legendy = každé slovo „Č.M."; x-rozsah [x−8, ďalšie Č.M.−8) alebo +276 pt
#      (kód začína ~4 pt vľavo od hlavičky). Z hlavičky x pozície INTERIÉR / PODLAHA / STENY,
#   3) kotvy riadkov = kód alebo PODLAHOVÁ / PODL. v ľavých 25 pt stĺpca; stĺpec končí pri
#      medzere medzi kotvami > 25 pt (NIE pri CELKOVÁ — stĺpec pokračuje pod CELKOVOU iného),
#   4) každé slovo stĺpca patrí najbližšej kotve, ak |Δtop| < 5,5 pt.
# Overené na Gerlach II: 259/259 bytov sedí s PODLAHOVÁ PLOCHA, 20/20 podlaží s CELKOVÁ.

POS_CODE_RE = re.compile(r'^\d+[A-Z]?\.(?:[A-Z]\.)?(?:-?\d+\.)?\d+\.?$')
AREA_TOK_RE = re.compile(r'^\d[\d\s ]*,\d{2}$')
UNIT_CODE_RE = re.compile(r'^\d+\.\d+$')          # miestnosť v byte (1.01); inak spoločný priestor


def _page_words(page):
    """Slová zo znakov strany: [{'s','x0','x1','top','size'}] (len vodorovný text)."""
    chars = []
    raw = page.get_text('rawdict')
    for b in raw.get('blocks', []):
        for ln in b.get('lines', []):
            d = ln.get('dir', (1, 0))
            if abs(d[0] - 1) > 1e-3 or abs(d[1]) > 1e-3:
                continue                                    # otočený text (kóty, popisy) mimo legendy
            for sp in ln.get('spans', []):
                size = sp.get('size') or 8.0
                for ch in sp.get('chars', []):
                    c = ch.get('c', '')
                    x0, y0, x1, _y1 = ch['bbox']
                    chars.append((round(y0 * 2) / 2, x0, x1, c, size))
    chars.sort(key=lambda t: (t[0], t[1]))
    words, cur = [], None
    for top, x0, x1, c, size in chars:
        if c.isspace():
            cur = None
            continue
        if (cur is not None and cur['top'] == top
                and x0 - cur['x1'] < max(1.0, 0.25 * size) and x0 > cur['x0'] - 0.5):
            cur['s'] += c
            cur['x1'] = max(cur['x1'], x1)
        else:
            cur = {'s': c, 'x0': x0, 'x1': x1, 'top': top, 'size': size}
            words.append(cur)
    return words


def _is_anchor(w):
    d = deburr(w['s'])
    return bool(POS_CODE_RE.match(w['s'])) or d in ('PODLAHOVA', 'PODL.')


def legend_rows_positional(page):
    """Riadky legendy z polohy znakov. Vráti list stĺpcov (každý list riadkov) alebo None.
    Riadok: {'code','name','area','podlaha','steny','strop','kind'} kde kind ∈
    'room' | 'unit' | 'sub' (PODLAHOVÁ PLOCHA) | 'total' (PODL. PLOCHA CELKOVÁ)."""
    words = _page_words(page)
    heads = sorted([w for w in words if deburr(w['s']) == 'C.M.'], key=lambda w: (w['x0'], w['top']))
    if not heads:
        return None
    cols = []
    for k, h in enumerate(heads):
        x_lo = h['x0'] - 8
        nxt = [o['x0'] for o in heads if o['x0'] > h['x0'] + 20]
        x_hi = (min(nxt) - 8) if nxt else h['x0'] + 276
        # dva Č.M. nad sebou v rovnakom stĺpci (pokračovanie legendy nižšie na hárku) → každý
        # má vlastný y-začiatok; ďalší Č.M. pod ním ukončí aktuálny
        below = [o['top'] for o in heads if abs(o['x0'] - h['x0']) <= 20 and o['top'] > h['top'] + 5]
        y_stop = min(below) - 2 if below else float('inf')
        cw = [w for w in words if x_lo <= w['x0'] < x_hi and h['top'] - 30 <= w['top'] < y_stop]
        hdr = [w for w in cw if abs(w['top'] - h['top']) <= 15]

        def hx(*keys):
            xs = [w['x0'] for w in hdr if any(deburr(w['s']).startswith(k) for k in keys)]
            return min(xs) if xs else None
        ax = hx('INTERIER', 'PLOCHA')
        px = hx('PODLAHA')
        sx = hx('STENY', 'STENA')
        tx = hx('STROP', 'PODHLAD')
        anchors = sorted([w for w in cw if w['top'] > h['top'] + 2 and w['x0'] < x_lo + 8 + 25
                          and _is_anchor(w)], key=lambda w: w['top'])
        kept, last = [], h['top']
        for a in anchors:
            if a['top'] - last > 25 + (10 if not kept else 0):
                break
            kept.append(a)
            last = a['top']
        if not kept:
            continue
        y_end = kept[-1]['top'] + 5.5
        groups = [[] for _ in kept]
        for w in cw:
            if w['top'] <= h['top'] + 2 or w['top'] > y_end:
                continue
            best, bd = None, 5.5
            for i, a in enumerate(kept):
                dd = abs(w['top'] - a['top'])
                if dd < bd:
                    best, bd = i, dd
            if best is not None:
                groups[best].append(w)
        rows = []
        for a, g in zip(kept, groups):
            g.sort(key=lambda w: w['x0'])
            rows.append(_pos_row(a, g, ax, px, sx, tx))
        cols.append({'x': h['x0'], 'top': h['top'], 'rows': rows})
    if not cols:
        return None
    cols.sort(key=lambda c: (c['x'], c['top']))
    return [c['rows'] for c in cols]


def _pos_row(anchor, g, ax, px, sx, tx):
    da = deburr(anchor['s'])
    text = ' '.join(w['s'] for w in g)
    dtext = deburr(text)
    area = None
    a_lo = (ax - 15) if ax is not None else -1e9
    a_hi = (px - 3) if px is not None else 1e9
    for w in g:
        if AREA_TOK_RE.match(w['s']) and a_lo <= w['x0'] < a_hi:
            area = parse_area(w['s'])
    if da in ('PODLAHOVA', 'PODL.'):
        return {'code': '', 'name': text, 'area': area, 'podlaha': '', 'steny': '', 'strop': '',
                'kind': 'total' if 'CELKOV' in dtext else 'sub'}

    def span(lo, hi):
        return ' '.join(w['s'] for w in g if w is not anchor
                        and (lo is None or w['x0'] >= lo - 3) and (hi is None or w['x0'] < hi - 3))
    name_hi = (ax - 3) if ax is not None else None
    name = ' '.join(w['s'] for w in g if w is not anchor and not AREA_TOK_RE.match(w['s'])
                    and (name_hi is None or w['x0'] < name_hi)).strip()
    podlaha = span(px, sx) if px is not None else ''
    steny = span(sx, tx) if sx is not None else ''
    strop = span(tx, None) if tx is not None else ''
    dn = deburr(name)
    kind = 'unit' if (dn.startswith('APARTMAN') or dn.startswith('BYT')) else 'room'
    return {'code': anchor['s'], 'name': name, 'area': area, 'podlaha': podlaha.strip(),
            'steny': steny.strip(), 'strop': strop.strip(), 'kind': kind}


def is_exterior_pos(name, podlaha=''):
    """Exteriér pre polohový parser: názov (balkón/terasa/loggia/závetrie/predzáhradka),
    mrazuvzdorná dlažba GRES M. (balkóny, terasy, loggie, závetria) alebo VSYP (štrkový
    vsyp okolo objektu — nie je podlahová plocha, nezapočítava sa do PODLAHOVEJ PLOCHY)."""
    dp = deburr(podlaha)
    return (is_exterior(name) or 'ZAVETR' in deburr(name) or dp.startswith('GRES M')
            or dp.startswith('VSYP') or deburr(name).startswith('VSYP'))


def objects_from_name(fname):
    """Stavebné objekty z názvu výkresu: „GR_SO.22.7-8-02.5_podkr" → ['7','8'],
    „GR_SO.22.5-02.2_1np" → ['5'] (číslo výkresu „-02" nie je rozsah: 2 < 5).
    Bez vzoru SO.<x>.<objekt> → []."""
    base = os.path.basename(fname or '')
    m = re.search(r'SO[._\s-]?\d+\.(\d+)(?:-(\d+))?(?=[-_.\s]|$)', base, re.I)
    if not m:
        return []
    a = int(m.group(1))
    if m.group(2) is not None:
        b = int(m.group(2))
        if a < b <= a + 9:
            return [str(n) for n in range(a, b + 1)]
    return [str(a)]


def positional_csv_rows(cols, objects=None):
    """Riadky legendy (z legend_rows_positional) → riadky app-CSV vrátane PODLAHA/STENY/STROP."""
    def q(s):
        return str(s).replace('"', '""')
    so = '-'.join([objects[0], objects[-1]]) if objects and len(objects) > 1 else (objects[0] if objects else '')
    rows, celk, any_celk, cur_block = [], 0.0, False, None
    for col in cols:
        for r in col:
            if r['kind'] == 'total':
                if r['area'] is not None:
                    celk += r['area']; any_celk = True
                continue
            if r['kind'] == 'sub':
                rows.append(';"  PODLAHOVA PLOCHA";"%s";;;;' % _fnum(r['area']))
                continue
            blk = r['code'].split('.')[0] if not UNIT_CODE_RE.match(r['code']) else None
            if blk and blk != cur_block:
                cur_block = blk
                rows.append(';"  BLOK ""%s"" - SO %s";;;;;' % (q(blk), so or ''))
            if r['kind'] == 'unit':
                rows.append('"%s";"  %s";%s;;;;' % (q(r['code']), q(r['name']),
                            ('"%s"' % _fnum(r['area'])) if r['area'] is not None else ''))
                continue
            if not r['name'] and r['area'] is None:
                continue
            ext = is_exterior_pos(r['name'], r['podlaha'])
            av = _fnum(r['area'])
            rows.append('"%s";"  %s";"%s";"%s";"%s";"%s";"%s"' % (
                q(r['code']), q(r['name']), '' if ext else av, av if ext else '',
                q(r['podlaha']), q(r['steny']), q(r['strop'])))
    if any_celk:
        rows.append(';"  PODL. PLOCHA CELKOVA";"%s";;;;' % _fnum(r2(celk)))
    return rows


def positional_check(cols):
    """Kontrolné čísla z polohového čítania: jednotky, miestnosti, súčty.
    Úsek legendy (po „PODL. PLOCHA CELKOVÁ") sa sčíta z medzisúčtov PODLAHOVÁ PLOCHA, ak ich
    má (= tak ako výkres), inak z interiérových miestností. Každý byt sa navyše overí
    proti svojej PODLAHOVEJ PLOCHE (badUnits)."""
    units = res = rooms = 0
    interior = total_calc = 0.0
    seg_subs = seg_rooms = 0.0
    seg_has_sub = False
    printed = None
    bad_units = []
    cur, cur_sum = None, 0.0

    def close_segment():
        nonlocal total_calc, seg_subs, seg_rooms, seg_has_sub
        total_calc += seg_subs if seg_has_sub else seg_rooms
        seg_subs = seg_rooms = 0.0
        seg_has_sub = False
    for col in cols:
        for r in col:
            if r['kind'] == 'total':
                if r['area'] is not None:
                    printed = (printed or 0) + r['area']
                close_segment()
            elif r['kind'] == 'sub':
                if r['area'] is not None:
                    seg_subs += r['area']; seg_has_sub = True
                if cur is not None and r['area'] is not None and abs(r2(cur_sum) - r['area']) > 0.02:
                    bad_units.append({'code': cur, 'sum': r2(cur_sum), 'printed': r['area']})
                cur, cur_sum = None, 0.0
            elif r['kind'] == 'unit':
                units += 1; res += 1
                cur, cur_sum = r['code'], 0.0
            else:
                rooms += 1
                if r['area'] is not None and not is_exterior_pos(r['name'], r['podlaha']):
                    interior += r['area']; seg_rooms += r['area']
                    if cur is not None:
                        cur_sum += r['area']
    close_segment()
    return {'units': units, 'residential': res, 'rooms': rooms,
            'interiorSum': r2(total_calc), 'roomInteriorSum': r2(interior),
            'printedTotal': r2(printed) if printed is not None else None, 'badUnits': bad_units}


def _positional_doc(doc):
    out = []
    for pno in range(len(doc)):
        cols = legend_rows_positional(doc[pno])
        if cols and sum(len(c) for c in cols) >= 3:
            out.append(cols)
    return out


def _positional_summary(pos, fname):
    tot = {'units': 0, 'residential': 0, 'rooms': 0, 'interiorSum': 0.0, 'printedTotal': None,
           'badUnits': []}
    for cols in pos:
        c = positional_check(cols)
        for k in ('units', 'residential', 'rooms'):
            tot[k] += c[k]
        tot['interiorSum'] = r2(tot['interiorSum'] + c['interiorSum'])
        if c['printedTotal'] is not None:
            tot['printedTotal'] = r2((tot['printedTotal'] or 0) + c['printedTotal'])
        tot['badUnits'] += c['badUnits']
    diff = None if tot['printedTotal'] is None else r2(tot['interiorSum'] - tot['printedTotal'])
    return dict(tot, file=fname, ok=True, diff=diff, via='polohovo', objects=objects_from_name(fname))


def _prefer_positional(pos_r, text_r):
    """Polohové čítanie sa použije, keď sedí s CELKOVOU, alebo je bližšie než textové.
    Staršie projekty (RNDZ/IC/Krasnany), kde textové čítanie sedí, tak ostanú bez zmeny."""
    if not pos_r:
        return False
    pd = pos_r.get('diff')
    if pd is not None and abs(pd) <= 0.05 and not pos_r.get('badUnits'):
        return True
    if not text_r or not text_r.get('ok'):
        return pd is not None or pos_r.get('rooms', 0) >= 3
    td = text_r.get('diff')
    if td is None:
        return pd is not None
    return pd is not None and abs(pd) < abs(td)


def _choose(doc, fname):
    """(via, positional_pages|None, summary) — rozhodne medzi polohovým a textovým čítaním."""
    pos = _positional_doc(doc)
    pos_r = _positional_summary(pos, fname) if pos else None
    text_r = _process_doc_text(doc, fname)
    if _prefer_positional(pos_r, text_r):
        return 'polohovo', pos, pos_r
    return 'text', None, text_r


def _process_doc(doc, fname):
    return _choose(doc, fname)[2]


def _process_doc_text(doc, fname):
    tot = {'resiInterior': 0.0, 'resiExterior': 0.0, 'obchodInterior': 0.0,
           'skladInterior': 0.0, 'garazInterior': 0.0, 'spolocne': 0.0}
    interior = printed = 0.0
    units = res = rooms = 0
    any_leg = False
    for pno in range(len(doc)):
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
        # kód + plocha, ale BEZ názvu = fantóm zo schémy/pečiatky za legendou → zahoď
        # (reálna miestnosť má vždy názov) — napr. RNDZ B2: „B2.3.C 60,00", „B.05 3,00"
        if not name.strip():
            return
        # názov = výkaz okien/dverí zo schémy (Krasnany „W1B W1A ZK4a …") → zahoď
        if _is_schedule_noise(name):
            return
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

    idx = 0
    n = len(toks)
    while idx < n:
        t = toks[idx]
        du = deburr(t)
        # „PODLAHOVÁ PLOCHA" [„CELKOVÁ"] <číslo> — poradie CELKOVÁ/číslo nepredpokladáme
        # (OCR sken vie zalomiť riadok inak než vektor a vydať číslo pred slovom CELKOVÁ).
        if _TOTAL_ANCHOR_RE.match(du) or _UNIT_TOTAL_RE.match(du):
            flush(); pend = None; pname = []
            anchor_celkova = 'CELKOVA' in du
            is_unit_total = bool(_UNIT_TOTAL_RE.match(du))
            v, more_celkova, idx = _scan_total(toks, idx)
            if v is not None:
                # per-jednotkový súčet (Nové Šúty „Spolu…") NIE JE plošná CELKOVÁ, len
                # medzisúčet jednotky (rovnako ako PODLAHOVÁ PLOCHA bez slova CELKOVÁ)
                if not is_unit_total and (anchor_celkova or more_celkova):
                    celk += v; any_celk = True
                else:
                    rows.append(';"  PODLAHOVA PLOCHA";"%s";;;;' % _fnum(v))   # medzisúčet jednotky
                    if unit_hdr_rows:
                        valid_units.add(unit_hdr_rows[-1])   # medzisúčet potvrdzuje poslednú hlavičku
            continue
        if is_header(t):
            idx += 1; continue
        if CODE_RE.match(t) and not NUM_RE.match(t):
            flush(); pend = t; pname = []
            idx += 1; continue
        # holý číselný kód (pozri komentár pri BARE_NUM_CODE_RE / parse_legend)
        if pend is None and BARE_NUM_CODE_RE.match(t) and _bare_code_is_room(toks, idx):
            pend, pname = t, []
            idx += 1; continue
        if NUM_RE.match(t):
            if pend is not None:
                emit_room(pend, ' '.join(pname).strip(), parse_area(t))
                pend = None; pname = []
            idx += 1; continue
        if pend is not None:
            pname.append(t)
        idx += 1
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
    # 1) polohové čítanie (stĺpce Č.M.) — spoľahlivé aj pri premiešanom poradí streamu
    via, pos, _r = _choose(doc, fname)
    if pos:
        objs = objects_from_name(fname)
        body = []
        for cols in pos:
            body += positional_csv_rows(cols, objs)
        if body:
            return '\r\n'.join(_CSV_HEAD + body) + '\r\n'
    # 2) pôvodné čítanie z textového streamu (RNDZ, Krasnany, IC …)
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

# OCR dá plochu s jednotkou rovno v tom istom boxe ("16,74 m²", niekedy "1,4 m?" keď sa
# "²" prečíta ako "?"). Bez tohto orezania číslo nikdy neprejde cez NUM_RE (ostane "zliate"
# v mene, lebo token má za sebou text naviac) a spolieha sa len na krehký fallback v emit_room.
_AREA_UNIT_RE = re.compile(r'^(?P<num>[-–]|\d[\d\s ]*[,.]\d+|\d[\d\s ]*)\s*m[²2?]\s*$', re.I)

def _strip_area_unit(s):
    m = _AREA_UNIT_RE.match(s)
    return m.group('num') if m else s

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
                toks.append(_strip_area_unit(s))
    return toks

# hlavičky stĺpcov „úpravy povrchov" (materiál podlahy/stien/stropu) — SUSEDNÝ blok vpravo
# od stĺpca PLOCHA. Nepatria k miestnosti; ich obsah ("Gresová dlažba", "OMIETKA"…) by sa
# inak zliapal do názvu miestnosti, keďže token-parser ich od názvu nevie odlíšiť.
_FINISH_HDRS = {'PODLAHA', 'STENY', 'STROP', 'PODHLAD'}

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
        # rekonštrukcia stĺpcov: nájdi hlavičky PLOCHA a prvého „úpravy povrchov" stĺpca
        # (PODLAHA/STENY/STROP/PODHĽAD) blízko kotvy a zaraž región tesne pred ním —
        # inak sa materiál podlahy/stien/stropu (a cudzia LEGENDA MATERIÁLOV ešte ďalej
        # vpravo) zlepí do názvu miestnosti.
        hdr_band = [it for it in col if it.get('y', 0) >= ay - 40]
        area_x = min((it.get('x', 0) for it in hdr_band
                      if deburr(it.get('s', '')).startswith('PLOCHA')), default=None)
        finish_x = min((it.get('x', 0) for it in hdr_band
                        if deburr(it.get('s', '')) in _FINISH_HDRS), default=None)
        if area_x is not None and finish_x is not None and finish_x > area_x:
            x_hi = min(x_hi, area_x + 0.5 * (finish_x - area_x))
            col = [it for it in col if it.get('x', 0) < x_hi]
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
