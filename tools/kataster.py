#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kataster.py — oracle: parcelné číslo -> verejné údaje z ESKN/ZBGIS.

Celý reťazec je VEREJNÝ (bez prihlásenia, bez reCAPTCHA), overený 2026-08-16:

    parcelné číslo (+ k.ú.)
      1) GET zbgis.skgeodesy.sk/mapka/api/search/kataster/{kuKod}/mu/{kuKod}?q={cislo}
         -> kandidáti parciel (id, k.ú. kód+názov, C alebo E)
      2) GET kataster.skgeodesy.sk/eskn/rest/services/VRM/identify/MapServer/{1|2}/query
             ?objectIds={id}&outFields=...&returnGeometry=true
         -> výmera, druh pozemku (id), kat. územie, číslo LV, geometria

POZOR na to, čo NEROBIŤ (spike p4-n1):
  - Atribútový /query (where=...) beží cez gateway do 504 — funguje LEN objectIds a identify.
  - Vlastníci / výpis LV (PortalODataPublic, GeneratePrfPublic) sú za reCAPTCHA a sú to
    OSOBNÉ ÚDAJE -> neautomatizovať. Pre vlastníkov dávame používateľovi deep-link na portál.

Beží na Macu aj vo Windows .exe (čisté stdlib: urllib). Servr (server.py) ho volá
cez endpoint /api/kataster; jadro je bez interakcie a bez COM.
"""

import json
import ssl
import urllib.parse
import urllib.request

# ESKN/ZBGIS servery (skgeodesy.sk) majú v certifikačnej reťazi self-signed certifikát → na
# Windows Python zlyhá na overení („SSL: CERTIFICATE_VERIFY_FAILED"); na Macu prejde cez systémové
# CA. Dáta sú VEREJNÉ a len na ČÍTANIE a doména je štátny kataster, preto pre tieto volania použijeme
# neoverujúci TLS kontext. (Nikam sa neposielajú žiadne citlivé údaje.)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# --- endpointy ---
_ZBGIS = "https://zbgis.skgeodesy.sk"
_SEARCH = _ZBGIS + "/mapka/api/search/kataster/{ku}/mu/{ku}"
_SUGGEST = _ZBGIS + "/mapka/api/suggest/kataster"
# vrstvy: 1 = Parcela C (register C), 2 = Parcela E (register E)
_VRM = "https://kataster.skgeodesy.sk/eskn/rest/services/VRM/identify/MapServer/{layer}/query"
# deep-link na oficiálny portál (tu používateľ vidí aj vlastníkov, reCAPTCHA rieši človek)
_DEEPLINK = _ZBGIS + "/mkzbgis/sk/kataster/detail/{typ}/{ku}/{num}"

# Hlavičky sú povinné — bez Referer/UA vracia gateway 403/504.
_HDRS = {
    "User-Agent": "Mozilla/5.0 (Vi-Analyza kataster helper)",
    "Referer": _ZBGIS + "/mkzbgis/sk/kataster",
    "Accept": "application/json",
}

# Druh pozemku — interný ESKN číselník NATURE_OF_LAND_USE_ID (1..10).
# OVERENÉ 2026-08-16 konzistenciou s veľkosťou parciel (identify na známych typoch):
#   23 ha -> id 7 (lesný pozemok), 4 ha -> id 1 (orná pôda), TTP -> id 6,
#   malá urbánna -> id 9 (zastavaná plocha a nádvorie), id 10 (ostatná plocha).
# raw id (druh_id) sa vždy vracia tiež, takže prípadná oprava textu je triviálna.
DRUH_POZEMKU = {
    1: "orná pôda",
    2: "chmeľnica",
    3: "vinica",
    4: "záhrada",
    5: "ovocný sad",
    6: "trvalý trávny porast",
    7: "lesný pozemok",
    8: "vodná plocha",
    9: "zastavaná plocha a nádvorie",
    10: "ostatná plocha",
}

_CATEGORY_LAYER = {"parcela-c": 1, "parcela-e": 2}


class KatasterError(Exception):
    pass


def _get(url, params, timeout=30):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(url + "?" + q, headers=_HDRS)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        raise KatasterError("Neočakávaná odpoveď služby (nie JSON).")


def ku_code(name, timeout=30):
    """Názov katastrálneho územia -> 6-miestny kód (prvý zásah kategórie 'katastrálne územie')."""
    j = _get(_SUGGEST, {"q": name}, timeout)
    for it in j.get("items", []):
        d = it.get("data", {})
        if d.get("category") == "katastrálne územie" and d.get("id"):
            return {"code": d["id"], "name": d.get("text", name),
                    "municipalityCode": d.get("municipalityCode")}
    return None


def search_parcels(number, ku, timeout=30):
    """
    Nájde kandidátov parciel pre číslo v okolí daného k.ú. (kód).
    Vracia zoznam: {id, number, ku_code, ku_name, category ('parcela-c'|'parcela-e'), route}.
    Search v jednom k.ú. môže vrátiť aj rovnomenné parcely zo susedných k.ú. -> disambiguuj podľa ku_name.
    """
    j = _get(_SEARCH.format(ku=ku), {"q": number}, timeout)
    out = []
    for it in j.get("items", []):
        d = it.get("data", {})
        cat = d.get("category", "")
        if cat not in _CATEGORY_LAYER or not d.get("id"):
            continue
        desc = d.get("description", "")            # napr. "k.ú. Veľká Bytča (807745)"
        code = None
        if "(" in desc and ")" in desc:
            code = desc[desc.rfind("(") + 1:desc.rfind(")")].strip()
        out.append({
            "id": str(d["id"]),
            "number": d.get("text", number),
            "ku_code": code,
            "ku_name": desc.replace("k.ú. ", "").split(" (")[0].strip() if desc else None,
            "category": cat,
            "route": d.get("route"),
        })
    return out


def parcel_detail(parcel_id, category="parcela-c", timeout=30):
    """objectId parcely -> verejné atribúty + geometria (bez osobných údajov)."""
    layer = _CATEGORY_LAYER.get(category, 1)
    fields = ("PARCEL_NUMBER,GEODETIC_AREA_OF_PARCEL,DESCRIPTIVE_AREA_OF_PARCEL,"
              "NATURE_OF_LAND_USE_ID,CADASTRAL_UNIT_ID,FOLIO_ID")
    j = _get(_VRM.format(layer=layer), {
        "objectIds": str(parcel_id),
        "outFields": fields,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }, timeout)
    feats = j.get("features") or []
    if not feats:
        return None
    a = feats[0].get("attributes", {})
    druh_id = a.get("NATURE_OF_LAND_USE_ID")
    try:
        druh_id = int(druh_id)
    except (TypeError, ValueError):
        druh_id = None
    return {
        "number": a.get("PARCEL_NUMBER"),
        "vymera": a.get("GEODETIC_AREA_OF_PARCEL"),       # geodetická (presná) výmera v m²
        "vymera_popisna": a.get("DESCRIPTIVE_AREA_OF_PARCEL"),
        "druh_id": druh_id,
        "druh": DRUH_POZEMKU.get(druh_id),
        "lv": a.get("FOLIO_ID"),                          # číslo/interné id listu vlastníctva
        "cadastral_unit_id": a.get("CADASTRAL_UNIT_ID"),
        "geometry": feats[0].get("geometry"),             # rings v EPSG:4326 (outSR)
    }


def deeplink(number, ku_code, category="parcela-c"):
    """
    Odkaz na oficiálny portál (tam používateľ vidí aj vlastníkov; reCAPTCHA rieši človek).
    Interná Angular route (`/kataster/parcela-c/{ku}/{num_}`) sa priamou navigáciou vždy
    NEotvorí do detailu — preto vraciame stabilnú vstupnú stránku katastra a číslo+k.ú.
    nesie appka zvlášť, nech ich používateľ dohľadá. (Presný deep-link doriešiť pri UI.)
    """
    return _ZBGIS + "/mkzbgis/sk/kataster"


def lookup(number, ku_name=None, ku_code_hint=None, timeout=30):
    """
    Hlavný vstup: parcelné číslo (+ názov ALEBO kód k.ú.) -> {ok, parcels:[...]}.
    Každá parcela nesie: číslo, výmera, druh, kat. územie, LV, geometria, deep-link.
    Bez k.ú. sa nedá vyhľadať (search potrebuje kontext k.ú.) -> vráti ok=False s hláškou.
    """
    code = ku_code_hint
    ku_display = None
    if not code and ku_name:
        ku = ku_code(ku_name, timeout)
        if ku:
            code, ku_display = ku["code"], ku["name"]
    if not code:
        return {"ok": False, "error": "Chýba katastrálne územie (názov alebo kód) — bez neho sa parcela nedá vyhľadať."}

    cands = search_parcels(number, code, timeout)
    if not cands:
        return {"ok": False, "error": "Parcela sa v okolí daného k.ú. nenašla.",
                "ku_code": code, "ku_name": ku_display}

    # ak poznáme názov/kód k.ú., ponechaj len presné zhody; inak vráť všetkých kandidátov
    def _match(c):
        if ku_code_hint:
            return c.get("ku_code") == str(ku_code_hint)
        if ku_name and c.get("ku_name"):
            return ku_name.strip().lower() in c["ku_name"].lower()
        return True
    picked = [c for c in cands if _match(c)] or cands

    parcels = []
    for c in picked:
        det = parcel_detail(c["id"], c["category"], timeout) or {}
        parcels.append({
            "number": det.get("number") or c["number"],
            "ku_code": c["ku_code"],
            "ku_name": c["ku_name"],
            "category": c["category"],
            "vymera": det.get("vymera"),
            "druh_id": det.get("druh_id"),
            "druh": det.get("druh"),
            "lv": det.get("lv"),
            "geometry": det.get("geometry"),
            "deeplink": deeplink(det.get("number") or c["number"], c["ku_code"], c["category"]),
        })
    return {"ok": True, "ku_code": code, "ku_name": ku_display, "parcels": parcels}


if __name__ == "__main__":
    import sys
    num = sys.argv[1] if len(sys.argv) > 1 else "776/3"
    ku = sys.argv[2] if len(sys.argv) > 2 else "807745"
    hint = ku if ku.isdigit() else None
    res = lookup(num, ku_name=None if hint else ku, ku_code_hint=hint)
    print(json.dumps(res, ensure_ascii=False, indent=1))
