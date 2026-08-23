#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regresny test dvoch opráv parsera legendy (pdf_legend.py):
  Fix 1 — LOGGIA/ZÁHRADA su exterier (parita s appkou); plocha loggie nesmie skoncit v interieri.
  Fix 2 — spolocny blok pred prvou jednotkou (kod "4B.00") sa musi zachytit, nie zahodit.
Overene na realnom vykrese IC1 4NP: pred opravou diff -31,05, po oprave ~0.

Spustaj z adresara repa:  python3 tests/test_legend_columns.py
"""
import sys, os, csv, io
sys.path.insert(0, 'tools')
import pdf_legend as L

IC_4NP = os.path.join(os.path.dirname(__file__), '..', '..', 'IC', 'IC1',
                      '05_4np-podorys 4np legenda.pdf')
RNDZ_B2 = os.path.join(os.path.dirname(__file__), '..', '..', 'EXPEDICIA 0.9_20-07-10',
                       'RNDZ_B_04_3+5+7NP-B2.pdf')


def test_exterior_keys():
    assert L.is_exterior('LOGGIA'), 'LOGGIA ma byt exterier'
    assert L.is_exterior('LOGGIA A.07'), 'LOGGIA v nazve ma byt exterier'
    assert L.is_exterior('ZÁHRADA'), 'ZAHRADA ma byt exterier'
    assert L.is_exterior('BALKÓN') and L.is_exterior('TERASA'), 'povodne exterier klucov musia zostat'
    assert not L.is_exterior('KUCHYŇA'), 'interier miestnost nesmie byt exterier'


def test_code_re():
    assert L.CODE_RE.match('4B.00'), 'kod spolocneho bloku 4B.00 ma matchovat'
    assert L.CODE_RE.match('4B.01') and L.CODE_RE.match('4.B.A') and L.CODE_RE.match('A.01')
    assert L.CODE_RE.match('6.A.01') and L.CODE_RE.match('B1.3.A')
    # guardy: podlazie a cislo vykresu sa NESMU brat ako kod
    assert not L.CODE_RE.match('6.NP') and not L.CODE_RE.match('10.NP')
    assert not L.CODE_RE.match('1.04a') and not L.CODE_RE.match('2NP')


def test_ic_4np_realny_vykres():
    if not os.path.exists(IC_4NP):
        print('  (preskocene: IC1 4NP PDF nie je dostupny)')
        return
    data = open(IC_4NP, 'rb').read()
    r = L.process_stream(data)
    assert r['ok'], 'legenda 4NP sa ma precitat'
    # diff voci vytlacenej CELKOVEJ ~0 (pred opravou -31,05)
    assert abs(r['diff']) < 0.5, 'diff 4NP ma byt ~0, je %.2f' % r['diff']
    # spolocny blok 4B.0x je v CSV
    csvt = L.to_app_csv(data)
    codes = [(''.join(row[0:1]) or '').strip().strip('"')
             for row in csv.reader(io.StringIO(csvt), delimiter=';') if len(row) >= 3]
    assert any(c.startswith('4B.') for c in codes), 'spolocny blok 4B.0x ma byt v CSV'
    # loggia je v EXTERIEROVOM stlpci (row[3]), nie v interierovom (row[2])
    for row in csv.reader(io.StringIO(csvt), delimiter=';'):
        if len(row) >= 4 and 'LOGGIA' in L.deburr(row[1]):
            assert L.parse_area(row[2]) is None, 'LOGGIA nesmie mat plochu v interieri: %r' % row
            assert L.parse_area(row[3]) is not None, 'LOGGIA ma mat plochu v exterieri: %r' % row


def test_rndz_b2_fantomy():
    # Fix 3: za „PODLAHOVÁ PLOCHA CELKOVÁ" nasleduje schéma/pečiatka; parser tam nachytal
    # kódy s plochou ale BEZ názvu („B2.3.C 60,00", „B.05 3,00") -> +62,99 nad CELKOVÚ.
    if not os.path.exists(RNDZ_B2):
        print('  (preskocene: RNDZ B2 PDF nie je dostupny)')
        return
    data = open(RNDZ_B2, 'rb').read()
    r = L.process_stream(data)
    assert r['ok'] and abs(r['diff']) < 0.1, 'RNDZ B2 diff ma byt ~0 (pred fixom +62,99), je %.2f' % r['diff']
    # ziadna interierova miestnost s prazdnym nazvom
    csvt = L.to_app_csv(data)
    for row in csv.reader(io.StringIO(csvt), delimiter=';'):
        if len(row) >= 3 and (row[0] or '').strip().strip('"'):
            name = (row[1] or '').strip().strip('"').strip()
            iv = L.parse_area(row[2])
            if iv is not None:
                assert name, 'miestnost s plochou nesmie mat prazdny nazov: %r' % row


if __name__ == '__main__':
    test_exterior_keys()
    test_code_re()
    test_ic_4np_realny_vykres()
    test_rndz_b2_fantomy()
    print('test_legend_columns: PASS')
