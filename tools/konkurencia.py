#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
konkurencia.py — načítanie porovnateľných projektov (konkurencie) z webu.

Dva režimy (Roman):
  1) search(miesto, typ)  — podľa lokality + typu prehľadá nehnutelnosti.sk (výsledky
     obsahujú aj novostavby od iných developerov) a vráti listingy.
  2) from_url(url)        — používateľ vloží odkaz na stránku konkurencie (aj developerskú
     mikrostránku) a appka z nej vytiahne názov, výmeru a cenu (ld+json, inak heuristika).

Výstup na riadok: {project, place, type, area, eurm2, bez, url}. €/m² a DPH dopočíta appka.
Zámerne nízkoobjemové a používateľom spustené (assistive) — respektuje robots.txt
(nehnutelnosti.sk: /api/ a cenové zoradenie sú zakázané, výsledky/detaily povolené).

Čisté stdlib (urllib) — beží na Macu aj vo Windows .exe.
"""

import html as _html
import json
import re
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

# Verejné web-scrapy (read-only). Neoverujúci TLS kontext = poistka proti self-signed/
# chýbajúcim CA na Windows (rovnaký dôvod ako v kataster.py).
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_BASE = "https://www.nehnutelnosti.sk"
_FS = "https://www.flatscraper.com"
_UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "sk-SK,sk;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}


class KonkurenciaError(Exception):
    pass


def _fetch(url, depth=0, timeout=30):
    """GET s ručným sledovaním presmerovaní (aj 308, ktoré urllib sám nevie)."""
    if depth > 6:
        raise KonkurenciaError("Priveľa presmerovaní.")
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=_UA),
                                   timeout=timeout, context=_SSL_CTX)
        return r.geturl(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            loc = e.headers.get("Location")
            if loc and loc.startswith("/"):
                loc = urllib.parse.urljoin(url, loc)
            if not loc:
                raise KonkurenciaError("Presmerovanie bez cieľa (%s)." % e.code)
            return _fetch(loc, depth + 1, timeout)
        raise KonkurenciaError("HTTP %s" % e.code)
    except Exception as e:                                # noqa: BLE001
        raise KonkurenciaError(str(e))


def _slug(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s


def _strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def _num(s):
    """'7 110,47 €/m²' / '298 000 €' / '41.91 m²' -> float."""
    if s is None:
        return None
    t = re.sub(r"[^\d,.\s]", "", str(s)).strip()
    t = t.replace(" ", "").replace(" ", "")
    if "," in t and "." in t:          # 1.234,56 -> 1234.56
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:                     # 7110,47 -> 7110.47
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


_P = re.compile(r'<p[^>]*data-test-id="text"[^>]*>(.*?)</p>', re.S)
_H2 = re.compile(r'<h2[^>]*data-test-id="text"[^>]*>(.*?)</h2>', re.S)


def _dispo(title):
    m = re.search(r'(\d(?:[,.]\d)?)\s*-?\s*izbov', title or "", re.I)
    return (m.group(1).replace(".", ",") + "-izbový") if m else None


def _parse_cards(html, limit):
    """Rozparsuje výsledkovú stránku nehnutelnosti.sk na listingy."""
    anchor = 'href="' + _BASE + '/detail/'
    parts = html.split(anchor)
    by_url = {}
    order = []
    for seg in parts[1:]:
        card = seg[:4000]                      # jedna karta = po ďalší detail odkaz
        url = _BASE + "/detail/" + _strip_tags(card.split('"', 1)[0])
        title = _strip_tags((_H2.search(card) or [None, ""])[1]) if _H2.search(card) else ""
        ps = [_strip_tags(x) for x in _P.findall(card)]
        place = next((p for p in ps if "okres" in p.lower() or "," in p), None)
        cat = next((p for p in ps if p in ("Byt", "Apartmán", "Dom", "Rodinný dom",
                                           "Pozemok", "Chata", "Garsónka")), None)
        area = next((_num(p) for p in ps if re.search(r"m²|m2", p)), None)
        eurm2 = next((_num(p) for p in ps if re.search(r"€\s*/\s*m", p)), None)
        price = next((_num(p) for p in ps
                      if "€" in p and not re.search(r"/\s*m", p) and _num(p)), None)
        if not title or (area is None and eurm2 is None):
            continue
        row = {
            "project": title,
            "place": place or "",
            "type": _dispo(title) or cat or "",
            "area": area,
            "eurm2": eurm2,
            "bez": price if price is not None else (
                round(area * eurm2, 2) if (area and eurm2) else None),
            "url": url,
        }
        # karta má dva /detail/ odkazy (obrázok + názov) → dedup podľa URL,
        # nechaj kompletnejší záznam (viac vyplnených polí)
        score = sum(1 for v in (row["area"], row["eurm2"], row["bez"]) if v is not None)
        if url not in by_url:
            order.append(url); by_url[url] = (score, row)
        elif score > by_url[url][0]:
            by_url[url] = (score, row)
    return [by_url[u][1] for u in order][:limit]


def search(miesto, typ="byty", limit=15, timeout=30):
    """Lokalita + typ -> porovnateľné listingy (vrátane novostavieb developerov)."""
    if not miesto or not str(miesto).strip():
        return {"ok": False, "error": "Chýba lokalita (miesto)."}
    typ_slug = {"byt": "byty", "byty": "byty", "apartman": "byty", "apartmany": "byty",
                "dom": "domy", "domy": "domy"}.get(_slug(typ), "byty")
    loc = _slug(miesto)
    url = "%s/vysledky/%s/%s/predaj" % (_BASE, typ_slug, loc)
    try:
        final, html = _fetch(url, timeout=timeout)
    except KonkurenciaError as e:
        return {"ok": False, "error": "Načítanie zlyhalo: %s" % e, "url": url}
    rows = _parse_cards(html, limit)
    if not rows:
        return {"ok": False, "error": "Pre danú lokalitu sa nenašli listingy (skús inú lokalitu/typ).",
                "url": final}
    return {"ok": True, "source": "nehnutelnosti.sk", "url": final,
            "miesto": miesto, "typ": typ_slug, "rows": rows}


# ---- režim developerských novostavieb: flatscraper.com --------------------------
# flatscraper indexuje NOVOSTAVBY od developerov; každá karta má data-data='{…}' s čistým
# JSON (projekt, mesto, izby, interiér, cena, odkaz PRIAMO na developera). Ceny sú S DPH
# (spotrebiteľské) → prepočítame na BEZ DPH (/1.23), aby sedeli s modelom (ten DPH pridáva sám).
_FS_DATA = re.compile(r"data-data='([^']+)'")


def search_flatscraper(miesto, typ="byty", limit=15, timeout=30):
    if not miesto or not str(miesto).strip():
        return {"ok": False, "error": "Chýba lokalita (miesto)."}
    first = re.split(r"[-,/]", str(miesto))[0].strip()   # „Bratislava - Rača" → „Bratislava"
    city = _slug(first) or _slug(miesto)
    url = "%s/%s" % (_FS, city)
    try:
        final, html = _fetch(url, timeout=timeout)
    except KonkurenciaError as e:
        return {"ok": False, "error": "Načítanie flatscraper zlyhalo: %s" % e, "url": url}
    rows, seen = [], set()
    for blob in _FS_DATA.findall(html):
        try:
            d = json.loads(_html.unescape(blob))
            interior = float(d.get("interior") or -1)
            price = float(d.get("price") or -1)
        except (ValueError, TypeError):
            continue
        if interior <= 0 or price <= 0:
            continue
        rooms = str(d.get("rooms") or "").strip()
        proj = (d.get("project") or "").strip()
        key = proj + "|" + rooms                          # 1 reprezentant na projekt+dispozíciu
        if key in seen:
            continue
        seen.add(key)
        bez = round(price / 1.23, 2)
        rows.append({
            "project": proj or (d.get("name") or ""),
            "place": (d.get("town") or first).strip(),
            "type": (rooms + "-izbový") if rooms and rooms not in ("-1", "0") else "byt",
            "area": interior,
            "eurm2": round(bez / interior, 2),
            "bez": bez,
            "url": (d.get("url") or "").strip(),          # odkaz PRIAMO na developera
        })
        if len(rows) >= limit:
            break
    if not rows:
        return {"ok": False, "error": ("Pre '%s' flatscraper nenašiel developerské byty. "
                "Skús názov mesta (napr. Bratislava, Trnava, Žilina, Košice, Nitra)." % first),
                "url": final}
    return {"ok": True, "source": "flatscraper.com", "url": final,
            "miesto": miesto, "typ": typ, "rows": rows}


# ---- databáza developerských projektov: bratislavaliving.sk (len Bratislava) ----------
# Next.js stránka: __NEXT_DATA__ obsahuje pole projektov (name, developer, priceFrom/priceTo,
# freeUnits, saleStarted/saleEnded, website = odkaz PRIAMO na developera, slug). Zahŕňa aj
# projekty EŠTE PRED PREDAJOM. POZOR: nemá výmeru bytov → €/m² sa nedá odvodiť (cena od-do +
# link + stav). Vhodné ako prehľad trhu / sledovanie developerov, nie na €/m² porovnanie.
_BL = "https://www.bratislavaliving.sk"
_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def search_bratislavaliving(miesto="Bratislava", typ="byty", limit=15, timeout=30):
    try:
        final, html = _fetch(_BL + "/projekty", timeout=timeout)
    except KonkurenciaError as e:
        return {"ok": False, "error": "Načítanie bratislavaliving zlyhalo: %s" % e, "url": _BL}
    m = _NEXT_RE.search(html)
    if not m:
        return {"ok": False, "error": "bratislavaliving: nečakaná štruktúra stránky.", "url": final}
    try:
        projects = json.loads(m.group(1))["props"]["pageProps"]["projects"]
    except (ValueError, KeyError):
        return {"ok": False, "error": "bratislavaliving: dáta projektov sa nenašli.", "url": final}

    def eur(v):
        try:
            return format(int(v), ",d").replace(",", " ")
        except (TypeError, ValueError):
            return None

    rows = []
    for p in projects:
        if p.get("saleEnded"):
            continue                                   # dopredané = už nie konkurencia
        pf, pt = p.get("priceFrom"), p.get("priceTo")
        parts = []
        if pf:
            parts.append("od " + eur(pf) + (" do " + eur(pt) if pt else "") + " €")
        if p.get("freeUnits"):
            parts.append("%s voľných" % p["freeUnits"])
        if not p.get("saleStarted"):
            parts.append("PRED PREDAJOM")
        dev = p.get("developer")
        if isinstance(dev, dict):
            dev = dev.get("name") or dev.get("slug")
        rows.append({
            "project": p.get("name") or "",
            "place": "Bratislava",
            "type": "",
            "area": None,
            "eurm2": None,                              # bratislavaliving nedáva výmeru → bez €/m²
            "bez": round(pf / 1.23, 2) if pf else None,  # orientačná „od" cena bez DPH
            "note": " · ".join(parts) + ((" · " + dev) if dev else ""),
            "url": p.get("website") or (_BL + "/projekty/" + (p.get("slug") or "")),
        })
        if len(rows) >= limit:
            break
    if not rows:
        return {"ok": False, "error": "bratislavaliving: žiadne aktívne projekty.", "url": final}
    return {"ok": True, "source": "bratislavaliving.sk", "url": final,
            "miesto": "Bratislava", "typ": typ, "rows": rows}


# ---- režim 2: ľubovoľná URL konkurencie -----------------------------------------
def _ldjson_estate(html):
    """Skús vytiahnuť ponuku z ld+json (schema.org) — najspoľahlivejšie, ak je."""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if not isinstance(obj, dict):
                continue
            offers = obj.get("offers") or {}
            price = None
            if isinstance(offers, dict):
                price = offers.get("price")
            area = None
            fs = obj.get("floorSize")
            if isinstance(fs, dict):
                area = fs.get("value")
            if obj.get("name") and (price or area):
                return {"project": _strip_tags(str(obj.get("name"))),
                        "price": _num(price), "area": _num(area)}
    return None


def from_url(url, timeout=30):
    """Ľubovoľná stránka konkurencie -> {project, place, type, area, eurm2, bez, url}."""
    if not url or not re.match(r"^https?://", url.strip(), re.I):
        return {"ok": False, "error": "Zadaj platnú adresu (http/https)."}
    url = url.strip()
    # nehnutelnosti.sk detail vieme presnejšie cez kartový parser
    try:
        final, html = _fetch(url, timeout=timeout)
    except KonkurenciaError as e:
        return {"ok": False, "error": "Načítanie zlyhalo: %s" % e}

    project = area = eurm2 = price = None
    place = ""
    ld = _ldjson_estate(html)
    if ld:
        project, area, price = ld["project"], ld["area"], ld["price"]

    # og:title / <title> ako názov, ak chýba
    if not project:
        m = (re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
             or re.search(r"<title[^>]*>(.*?)</title>", html, re.S))
        if m:
            project = _strip_tags(m.group(1))[:120]

    text = _strip_tags(html)
    if eurm2 is None:
        m = re.search(r"([\d\s.,]+)\s*€\s*/\s*m", text)
        if m:
            eurm2 = _num(m.group(1))
    if area is None:
        m = re.search(r"([\d\s.,]+)\s*m²", text) or re.search(r"([\d\s.,]+)\s*m2", text)
        if m:
            area = _num(m.group(1))
    if price is None:
        m = re.search(r"([\d][\d\s.,]{3,})\s*€(?!\s*/)", text)
        if m:
            price = _num(m.group(1))

    if not project and area is None and price is None and eurm2 is None:
        return {"ok": False, "error": "Zo stránky sa nepodarilo vytiahnuť údaje — doplň riadok ručne.", "url": final}
    if eurm2 is None and area and price:
        eurm2 = round(price / area, 2)
    elif price and eurm2:                 # výmera z ceny a €/m² = najkonzistentnejšia (text býva zaokrúhlený)
        area = round(price / eurm2, 2)
    row = {"project": project or final, "place": place, "type": _dispo(project or ""),
           "area": area, "eurm2": eurm2,
           "bez": price if price is not None else (round(area * eurm2, 2) if (area and eurm2) else None),
           "url": final}
    return {"ok": True, "source": "url", "url": final, "rows": [row]}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and re.match(r"^https?://", sys.argv[1]):
        print(json.dumps(from_url(sys.argv[1]), ensure_ascii=False, indent=1))
    else:
        miesto = sys.argv[1] if len(sys.argv) > 1 else "Vysoké Tatry"
        typ = sys.argv[2] if len(sys.argv) > 2 else "byty"
        print(json.dumps(search(miesto, typ), ensure_ascii=False, indent=1))
