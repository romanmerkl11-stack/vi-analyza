import sys

sys.path.insert(0, 'tools')
import pdf_legend


def test_meta_guards():
    good = pdf_legend.extract_meta('BRATISLAVA - RAČA, k.ú. RAČA  p.č. 17353/1,2,7')
    assert good['miesto'] == 'BRATISLAVA - RACA'
    assert good['parcels'] == '17353/1,2,7'
    bad = pdf_legend.extract_meta('POZEM, k.ú. IVANKA PRI DUNAJI')
    assert bad['miesto'] is None


if __name__ == '__main__':
    test_meta_guards()
    print('test_pdf_meta: PASS')
