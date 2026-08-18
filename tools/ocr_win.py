#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ocr_win.py — OCR pre Windows cez RapidOCR (offline, ONNX runtime).

Rovnaké rozhranie ako ocr.py (macOS Vision): `recognize_pdf(data) -> (items, stats)`,
item = {s, x, y, w, h, rot, conf}, súradnice v BODOCH a y rastie NAHOR (ako pdf.js /
Vision) — appka to spracuje tým istým parserom a kontrolou súčtu.

RapidOCR aj jeho ONNX modely sa bundlujú do .exe (PyInstaller --collect-all
rapidocr_onnxruntime onnxruntime), takže OCR sa inštaluje SPOLU s appkou — používateľ
nič doinštalovať nemusí.

Inštalácia pri builde:  py -m pip install rapidocr-onnxruntime
"""

# tvrdé importy — ak niečo chýba, modul sa neimportuje a server ohlási OCR ako nedostupné
from rapidocr_onnxruntime import RapidOCR
import numpy as np
import fitz

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = RapidOCR()
    return _engine


_MAX_PX = 6000          # veľké A1 hárky @400 dpi = desaťtisíce px → onnxruntime padne; dláždime
_OVERLAP_PT = 45.0      # prekryv dlaždíc (body), aby sa text na hranici nestratil


def _spans(total_pt, tile_pt, overlap):
    """Rozdelí 0..total na prekrývajúce sa intervaly (v bodoch)."""
    if total_pt <= tile_pt:
        return [(0.0, total_pt)]
    out, x = [], 0.0
    step = max(tile_pt - overlap, tile_pt * 0.5)
    while x < total_pt:
        out.append((x, min(x + tile_pt, total_pt)))
        if x + tile_pt >= total_pt:
            break
        x += step
    return out


def _dedup(items):
    """Odstráni duplicity z prekryvu dlaždíc (rovnaký text ~na tom istom mieste)."""
    out = []
    for it in items:
        dup = False
        for o in out:
            if o['s'] == it['s'] and abs(o['x'] - it['x']) < 6 and abs(o['y'] - it['y']) < 6:
                dup = True
                break
        if not dup:
            out.append(it)
    return out


def recognize_pdf(data, dpi=400):
    """PDF (bytes) → (items, stats). y rastie NAHOR (ako pdf.js). Veľké hárky OCR-uje po dlaždiciach."""
    engine = _get_engine()
    doc = fitz.open(stream=data)          # auto-detekcia: PDF aj obrázky (PNG/JPG…)
    items = []
    low = 0
    zoom = dpi / 72.0
    tile_pt = _MAX_PX / zoom               # max veľkosť dlaždice v bodoch, aby raster ≤ _MAX_PX
    for pno in range(len(doc)):
        page = doc[pno]
        h_pt, w_pt = page.rect.height, page.rect.width
        for (cx0, cx1) in _spans(w_pt, tile_pt, _OVERLAP_PT):
            for (cy0, cy1) in _spans(h_pt, tile_pt, _OVERLAP_PT):
                clip = fitz.Rect(cx0, cy0, cx1, cy1)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
                if pix.width < 8 or pix.height < 8:
                    continue
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n >= 3:
                    img = np.ascontiguousarray(img[:, :, 2::-1])     # RGB(A) -> BGR
                try:
                    result, _ = engine(img)
                except Exception:                                    # onnxruntime zlyhá na dlaždici → preskoč
                    continue
                if not result:
                    continue
                for box, text, score in result:
                    if not text or not str(text).strip():
                        continue
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    x0, x1 = min(xs), max(xs)
                    y0, y1 = min(ys), max(ys)
                    # pixely v dlaždici (y od vrchu) -> body na strane; y hore = h_pt − (cy0 + y1/zoom)
                    items.append({
                        's': str(text),
                        'x': cx0 + x0 / zoom,
                        'y': h_pt - (cy0 + y1 / zoom),
                        'w': (x1 - x0) / zoom,
                        'h': (y1 - y0) / zoom,
                        'rot': 0.0,
                        'conf': float(score) if score is not None else 1.0,
                    })
                    if score is not None and float(score) < 0.5:
                        low += 1
    doc.close()
    items = _dedup(items)
    return items, {'items': len(items), 'low': low}
