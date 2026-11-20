#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regresný test polohového čítania legendy (pdf_legend.legend_rows_positional).

Syntetický hárok napodobňuje chyby exportu z DWG (Gerlach II):
  - znaky sú v streame zapísané v NÁHODNOM poradí (get_text('text') ich premieša),
  - slová jedného riadku majú rozdielny top (0,6–2 pt),
  - kód začína ~4 pt vľavo od hlavičky „Č.M.",
  - ľavý stĺpec pokračuje POD „CELKOVÁ" pravého stĺpca (koniec stĺpca = medzera > 25 pt),
  - kódy 5.1.01 / 7A.1.01 / 9.B.-1.01, hlavička bytu 7.B.1.04., miestnosti 1.01,
  - materiál „GRES, NAT.1" ostáva jeden materiál, GRES M. je exteriér.

Spúšťaj z adresára repa:  python3 tests/test_legend_positional.py
"""
import sys, os, csv, io, random
sys.path.insert(0, 'tools')
import pdf_legend as L
import fitz

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
if not os.path.exists(FONT):
    FONT = 'C:/Windows/Fonts/arial.ttf'

# (kód, názov, plocha, podlaha, steny)
LEFT = [
    ('5.1.01', 'SCHODISKO', '18,40', 'GRES, NAT.1', 'OMIET.'),
    ('5.1.02', 'SPOLOČNÁ CHODBA', '22,10', 'KOBEREC', 'OMIET.'),
    ('9.B.-1.01', 'VÝŤAHOVÁ ŠACHTA', '4,00', 'HI.N.', '-'),
    ('5.1.03', 'VSYP', '3,00', 'VSYP', '-'),
    ('SUB', 'PODLAHOVÁ PLOCHA', '47,50', '', ''),
    ('7.B.1.04.', 'BYT 2-IZB.', None, '', ''),
    ('1.01', 'PREDSIEŇ', '5,20', 'LAMINO', 'OMIET.'),
    ('1.02', 'KÚPEĽŇA', '4,30', 'KER.DL.', 'KER.O.'),
    ('1.03', 'IZBA', '15,00', 'LAMINO', 'OMIET.'),
    ('1.04', 'BALKÓN', '6,00', 'GRES M.', '-'),
    ('SUB', 'PODLAHOVÁ PLOCHA', '24,50', '', ''),
    ('7.B.1.05.', 'BYT 1-IZB.', None, '', ''),
    ('1.01', 'IZBA S KK', '20,00', 'LAMINO', 'OMIET.'),
    ('1.02', 'WC', '1,50', 'KER.DL.', 'KER.O.'),
    ('1.03', 'ZÁVETRIE', '2,00', 'GRES M.', '-'),
    ('SUB', 'PODLAHOVÁ PLOCHA', '21,50', '', ''),
    ('TOT', 'PODL. PLOCHA CELKOVÁ', '93,50', '', ''),
]
RIGHT = [
    ('7A.1.01', 'SKLAD', '3,25', 'BET.DL.', '-'),
    ('TOT', 'PODL. PLOCHA CELKOVÁ', '3,25', '', ''),
]
EXPECT_TOTAL = 96.75   # 93,50 + 3,25 (VSYP = interiér, je v CELKOVEJ)


def _draw_legend(chars, x0, top, rows, rnd):
    hdr = [('LEGENDA MIESTNOSTÍ', 4, -14), ('Č.M.', 4, 0), ('NÁZOV MIESTNOSTI', 30, 0),
           ('INTERIÉR', 130, 0), ('PODLAHA', 175, 0), ('STENY', 220, 0), ('STROP', 250, 0)]
    for s, dx, dy in hdr:
        chars.append((s, x0 + dx, top + dy))
    y = top + 9
    for code, name, area, pod, st in rows:
        j = lambda: rnd.uniform(0, 1.8)                    # rozdielny top slov v riadku
        if code in ('SUB', 'TOT'):
            chars.append((name, x0, y + j()))             # PODLAHOVÁ PLOCHA v stĺpci kódu
        else:
            chars.append((code, x0, y + j()))             # 4 pt vľavo od „Č.M."
            chars.append((name, x0 + 30, y + j()))
        if area:
            chars.append((area, x0 + 135, y + j()))
        if pod:
            chars.append((pod, x0 + 176, y + j()))
        if st:
            chars.append((st, x0 + 221, y + j()))
        y += 8


def make_pdf():
    rnd = random.Random(7)
    doc = fitz.open()
    page = doc.new_page(width=1190, height=842)
    font = fitz.Font(fontfile=FONT)
    words = []
    _draw_legend(words, 560, 100, LEFT, rnd)
    _draw_legend(words, 860, 100, RIGHT, rnd)
    words.append(('PÔDORYS 2.NP', 900, 760))
    # rozbi na znaky a zapíš v náhodnom poradí (premiešaný stream)
    glyphs = []
    for s, x, y in words:
        cx = x
        for c in s:
            glyphs.append((c, cx, y))
            cx += font.text_length(c, fontsize=6)
    rnd.shuffle(glyphs)
    tw = fitz.TextWriter(page.rect)
    for c, x, y in glyphs:
        tw.append((x, y + 6), c, font=font, fontsize=6)
    tw.write_text(page)
    return doc.tobytes()


def test_positional():
    data = make_pdf()
    doc = fitz.open(stream=data, filetype='pdf')
    cols = L.legend_rows_positional(doc[0])
    assert cols and len(cols) == 2, 'dva stĺpce legendy, je %r' % (cols and len(cols))
    left = cols[0]
    codes = [r['code'] for r in left if r['kind'] in ('room', 'unit')]
    assert codes[:4] == ['5.1.01', '5.1.02', '9.B.-1.01', '5.1.03'], codes
    assert '7.B.1.04.' in codes and codes.count('1.01') == 2, codes
    # stĺpec pokračuje pod CELKOVÁ pravého stĺpca → posledná CELKOVÁ ľavého je prečítaná
    assert left[-1]['kind'] == 'total' and left[-1]['area'] == 93.5, left[-1]
    sch = left[0]
    assert sch['name'] == 'SCHODISKO' and sch['area'] == 18.4 and sch['podlaha'] == 'GRES, NAT.1', sch
    units = [r for r in left if r['kind'] == 'unit']
    assert [u['name'] for u in units] == ['BYT 2-IZB.', 'BYT 1-IZB.'], units

    chk = L._process_doc(doc, 'GR_SO.22.7-8-02.3_2np.pdf')
    assert chk['via'] == 'polohovo', chk
    assert chk['printedTotal'] == EXPECT_TOTAL, chk
    assert chk['diff'] == 0, 'súčet interiéru má sedieť s CELKOVOU, %r' % chk
    assert chk['units'] == 2 and not chk['badUnits'], chk
    assert chk['objects'] == ['7', '8'], chk

    csvt = L.to_app_csv(data, 'GR_SO.22.7-8-02.3_2np.pdf')
    rows = list(csv.reader(io.StringIO(csvt), delimiter=';'))
    byname = {r[1].strip(): r for r in rows if len(r) > 5}
    assert byname['SCHODISKO'][4] == 'GRES, NAT.1', byname['SCHODISKO']
    assert byname['KÚPEĽŇA'][5] == 'KER.O.'
    assert byname['BALKÓN'][3] == '6,00' and byname['BALKÓN'][2] == ''   # exteriér
    assert byname['ZÁVETRIE'][3] == '2,00'                               # GRES M. → exteriér
    assert any('BLOK ""7A"" - SO 7-8' in ln or 'BLOK "7A" - SO 7-8' in ln for ln in csvt.splitlines()), csvt
    assert 'PODL. PLOCHA CELKOVA";"96,75"' in csvt, csvt


def test_objects_from_name():
    assert L.objects_from_name('GR_SO.22.7-8-02.5_podkr.pdf') == ['7', '8']
    assert L.objects_from_name('GR_SO.22.5-02.2_1np.pdf') == ['5']
    assert L.objects_from_name('GR_SO.22.9.dwg') == ['9']
    assert L.objects_from_name('RNDZ_C_02_1NP-C.pdf') == []


if __name__ == '__main__':
    if not os.path.exists(FONT):
        print('test_legend_positional: SKIP (chýba TTF font s diakritikou)'); sys.exit(0)
    test_objects_from_name()
    test_positional()
    print('test_legend_positional: PASS')
