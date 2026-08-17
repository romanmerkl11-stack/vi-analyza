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


def recognize_pdf(data, dpi=400):
    """PDF (bytes) → (items, stats). y rastie NAHOR (ako pdf.js)."""
    engine = _get_engine()
    doc = fitz.open(stream=data)          # auto-detekcia: PDF aj obrázky (PNG/JPG…)
    items = []
    low = 0
    zoom = dpi / 72.0
    for pno in range(len(doc)):
        page = doc[pno]
        h_pt = page.rect.height
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n >= 3:
            img = np.ascontiguousarray(img[:, :, 2::-1])     # RGB(A) -> BGR pre RapidOCR
        result, _ = engine(img)
        if not result:
            continue
        for box, text, score in result:
            if not text or not str(text).strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            # pixely (y dole od vrchu) -> body, y hore. y = spodok bloku (~baseline, ako Vision).
            items.append({
                's': str(text),
                'x': x0 / zoom,
                'y': h_pt - (y1 / zoom),
                'w': (x1 - x0) / zoom,
                'h': (y1 - y0) / zoom,
                'rot': 0.0,
                'conf': float(score) if score is not None else 1.0,
            })
            if score is not None and float(score) < 0.5:
                low += 1
    doc.close()
    return items, {'items': len(items), 'low': low}
