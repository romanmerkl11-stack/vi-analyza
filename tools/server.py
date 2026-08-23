#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — pomocnik, vdaka ktoremu appka spusta nastroje SAMA.

Prehliadac z bezpecnostnych dovodov nesmie spustat programy na disku. Preto
appku obsluzi tento maly server: bezi lokalne, appka mu posle vykres, ktory
sama neprecita, a on na nom spusti prislusny nastroj a vrati vysledok.

    python3 tools/server.py

Otvori prehliadac na http://127.0.0.1:8765 . Nic neodchadza z pocitaca —
server pocuva len na loopbacku a von nic neposiela.

Ak sa appka otvori priamo dvojklikom (bez servera), funguje ako predtym, len
krivkove a skenovane vykresy si musis spracovat rucne.
"""

import importlib.util
import io
import json
import os
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# ROOT = priečinok s appkou (analyza-budovy.html) a podkladmi.
#  - normálne: rodič priečinka tools/
#  - zabalený .exe (PyInstaller): priečinok, kde leží .exe (appka sa serví odtiaľ,
#    takže sa dá aktualizovať cez Google Drive bez nového buildu)
if getattr(sys, 'frozen', False):
    _exedir = os.path.dirname(sys.executable)
    # ak je appka vedľa .exe (živá, aktualizovateľná cez Google Drive) → servuj odtiaľ;
    # inak z priloženého balíka (_MEIPASS) → .exe je úplne samostatný jeden súbor
    if os.path.exists(os.path.join(_exedir, 'analyza-budovy.html')):
        ROOT = _exedir
    else:
        ROOT = getattr(sys, '_MEIPASS', _exedir)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(ROOT, 'tools'))

PORT = 8765
MAXBODY = 200 * 1024 * 1024        # 200 MB, vykresy byvaju velke


def _tools_dir():
    """Priečinok, kde hľadať aktualizovateľné .py moduly: vedľa .exe (frozen) / rodič tools/ (dev)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _try_import(name):
    """AKTUALIZOVATEĽNÉ NA DIAĽKU: ak leží `<name>.py` vedľa .exe, načíta sa TEN (prebije verziu
    zabundlovanú v .exe) → backend (parser, kataster, konkurencia…) sa dá aktualizovať len nahradením
    .py súboru (napr. cez Google Drive), bez nového buildu. Bundle je fallback. Závislosti (fitz,
    rapidocr…) sa aj tak berú z .exe, takže stačí meniť samotné .py moduly."""
    try:
        p = os.path.join(_tools_dir(), name + '.py')
        if getattr(sys, 'frozen', False) and os.path.isfile(p):
            spec = importlib.util.spec_from_file_location(name, p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod            # aby prípadné `import <name>` inde dostalo tú istú verziu
            spec.loader.exec_module(mod)
            print('  (%s: z disku %s)' % (name, p))
            return mod
        return __import__(name)
    except Exception as e:                       # noqa: BLE001
        print('  (nedostupne: %s — %s)' % (name, e))
        return None


krivky = _try_import('krivky_na_text')
kataster = _try_import('kataster')   # parcelné číslo -> verejné údaje z ESKN/ZBGIS
konkurencia = _try_import('konkurencia')   # konkurencia z webu (lokalita/typ alebo URL)
# OCR engine podľa platformy: macOS = Apple Vision (ocr.py), Windows = RapidOCR (ocr_win.py).
# Obidva majú rovnaké rozhranie recognize_pdf(data) -> (items, stats).
ocr = _try_import('ocr') if sys.platform == 'darwin' else _try_import('ocr_win')
legend = _try_import('pdf_legend')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):           # tichsi vypis
        if '/api/' in (self.path or ''):
            sys.stderr.write('  %s\n' % (fmt % args))

    # --- pomocne ---

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0 or n > MAXBODY:
            return None
        buf = io.BytesIO()
        left = n
        while left > 0:
            chunk = self.rfile.read(min(left, 1 << 20))
            if not chunk:
                break
            buf.write(chunk)
            left -= len(chunk)
        return buf.getvalue()

    # --- API ---

    def do_GET(self):
        if self.path.startswith('/api/ping'):
            return self._json({
                'ok': True,
                'krivky': krivky is not None,
                'ocr': ocr is not None,
                'legend': legend is not None,
                'kataster': kataster is not None,
                'konkurencia': konkurencia is not None,
                'platform': sys.platform,
            })
        if self.path.startswith('/api/kataster'):
            return self._run_kataster()
        if self.path.startswith('/api/konkurencia'):
            return self._run_konkurencia()
        if self.path == '/' or self.path == '':
            self.path = '/analyza-budovy.html'
        return super().do_GET()

    def _run_kataster(self):
        """Parcelné číslo (+ k.ú.) -> verejné údaje (výmera, druh, kat. územie, LV, geometria)."""
        if kataster is None:
            return self._json({'ok': False, 'error': 'Modul kataster tu nie je dostupný.'}, 501)
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        number = (q.get('number') or q.get('cislo') or [''])[0].strip()
        ku = (q.get('ku') or [''])[0].strip()
        if not number:
            return self._json({'ok': False, 'error': 'Chýba parcelné číslo (parameter number).'}, 400)
        code_hint = ku if ku.isdigit() else None
        name = None if code_hint else (ku or None)
        try:
            return self._json(kataster.lookup(number, ku_name=name, ku_code_hint=code_hint))
        except Exception as e:                        # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._json({'ok': False, 'error': 'Kataster: %s' % e}, 502)

    def _run_konkurencia(self):
        """Konkurencia z webu: ?url=<odkaz> alebo ?miesto=<lok>&typ=<byty|domy>."""
        if konkurencia is None:
            return self._json({'ok': False, 'error': 'Modul konkurencia tu nie je dostupný.'}, 501)
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        url = (q.get('url') or [''])[0].strip()
        miesto = (q.get('miesto') or [''])[0].strip()
        typ = (q.get('typ') or ['byty'])[0].strip()
        zdroj = (q.get('zdroj') or ['flatscraper'])[0].strip()   # default: developerské novostavby
        try:
            n = int((q.get('limit') or ['15'])[0])
        except ValueError:
            n = 15
        try:
            if url:
                return self._json(konkurencia.from_url(url))
            if miesto:
                if zdroj == 'nehnutelnosti':
                    return self._json(konkurencia.search(miesto, typ, limit=n))
                if zdroj == 'bratislavaliving':
                    return self._json(konkurencia.search_bratislavaliving(miesto, typ, limit=n))
                return self._json(konkurencia.search_flatscraper(miesto, typ, limit=n))
            return self._json({'ok': False, 'error': 'Zadaj lokalitu (miesto) alebo URL.'}, 400)
        except Exception as e:                        # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._json({'ok': False, 'error': 'Konkurencia: %s' % e}, 502)

    def do_POST(self):
        if self.path.startswith('/api/krivky'):
            return self._run(krivky, 'krivky_na_text')
        if self.path.startswith('/api/ocr'):
            return self._run(ocr, 'ocr')
        if self.path.startswith('/api/legend'):
            return self._run_legend()
        self.send_error(404)

    def _run_legend(self):
        """Prečíta legendu miestností z PDF (vektor) → plochy pre ekonomiku."""
        if legend is None:
            return self._json({'ok': False, 'error': 'Nástroj pdf_legend tu nie je dostupný.'}, 501)
        data = self._body()
        if not data:
            return self._json({'ok': False, 'error': 'Prázdne telo požiadavky.'}, 400)
        fname = self.headers.get('X-Filename') or 'pdf'
        try:
            csv = legend.to_app_csv(data, fname)       # vektorové PDF (textová vrstva)
            via = 'vektor'
            meta = None
            diff = interior = printed = residential = None
            if csv:
                r = legend.process_stream(data, fname)  # kontrolné čísla (diff voči CELKOVEJ)
                diff, interior = r.get('diff'), r.get('interiorSum')
                printed, residential = r.get('printedTotal'), r.get('residential')
                meta = legend.meta_from_data(data)      # rozpiska z textu PDF
            else:
                # legenda ako KRIVKY (obrysy písmen, bez textovej vrstvy) — napr. IC1.
                # to_app_csv_ocr vyžaduje kotvu „LEGENDA MIES" v rekonštruovanom texte →
                # hárky s iným (nerozpoznaným) fontom sem nespadnú a idú ďalej na OCR.
                if krivky is not None:
                    try:
                        kitems, _ks = krivky.extract_bytes(data)
                        kcsv = legend.to_app_csv_ocr(kitems, fname)
                        if kcsv:
                            csv, via = kcsv, 'krivky'
                            meta = legend.meta_from_data(data)
                    except Exception:               # noqa: BLE001
                        import traceback
                        traceback.print_exc()
                if not csv and ocr is not None:         # sken / obrázok bez textu → OCR
                    items, _st = ocr.recognize_pdf(data)
                    csv = legend.to_app_csv_ocr(items, fname)
                    via = 'ocr'
                    meta = legend.extract_meta(' '.join(it.get('s', '') for it in items))
            if not csv:
                return self._json({'ok': False, 'error':
                    'Legenda miestností sa nenašla (ani textom, ani OCR). Skús čistejší podklad alebo výrez legendy.'})
            # SO z rozpisky doplní do BLOK riadku (najmä pri OCR, kde výrez legendy SO nemá)
            if meta and meta.get('so') and '- SO ";' in csv:
                csv = csv.replace('- SO ";', '- SO %s";' % meta['so'], 1)
            return self._json({'ok': True, 'csv': csv, 'file': fname, 'via': via, 'meta': meta,
                               'diff': diff, 'interiorSum': interior,
                               'printedTotal': printed, 'residential': residential})
        except Exception as e:                        # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._json({'ok': False, 'error': str(e)}, 500)

    def _run(self, mod, name):
        if mod is None:
            return self._json({'ok': False, 'error': 'Nástroj %s tu nie je dostupný.' % name}, 501)
        data = self._body()
        if not data:
            return self._json({'ok': False, 'error': 'Prázdne telo požiadavky.'}, 400)
        try:
            if mod is krivky:
                items, st = mod.extract_bytes(data)
            else:
                items, st = mod.recognize_pdf(data)      # ocr.py aj ocr_win.py
            return self._json({'ok': True, 'items': items, 'stats': st})
        except Exception as e:                    # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._json({'ok': False, 'error': str(e)}, 500)


def main():
    port = PORT
    for _ in range(20):                           # ked je port obsadeny, skus dalsi
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            break
        except OSError:
            port += 1
    else:
        sys.exit('Chyba: nenasiel sa volny port.')

    url = 'http://127.0.0.1:%d/' % port
    print('=' * 60)
    print('Analyza budovy bezi na %s' % url)
    print('Krivkove vykresy: %s' % ('ANO' if krivky else 'nie'))
    print('OCR (skeny):      %s' % ('ANO (%s)' % ('Vision' if sys.platform == 'darwin' else 'RapidOCR') if ocr else 'nie'))
    print('Zatvorit: Ctrl+C v tomto okne')
    print('=' * 60)
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nKoniec.')


if __name__ == '__main__':
    main()
