"""Country data lookup from countries_parsed.json.

Loads data once at import time and provides lookup by country name or code.
"""

import json
import os
import re
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "countries_parsed.json"

# Loaded once at module level
_countries: list[dict] = []
_by_code: dict[str, list[dict]] = {}
_by_name: dict[str, dict] = {}

# Common aliases: search term -> canonical name in dataset
_ALIASES: dict[str, str] = {
    "abd": "amerika birlesik devletleri",
    "abd'de": "amerika birlesik devletleri",
    "usa": "amerika birlesik devletleri",
    "america": "amerika birlesik devletleri",
    "united states": "amerika birlesik devletleri",
    "uk": "birlesik krallik",
    "ingiltere": "birlesik krallik",
    "england": "birlesik krallik",
    "britain": "birlesik krallik",
    "uae": "birlesik arap emirlikleri",
    "bae": "birlesik arap emirlikleri",
    "cin": "cin",
    "china": "cin",
    "almanya": "almanya",
    "germany": "almanya",
    "fransa": "fransa",
    "france": "fransa",
    "italya": "italya",
    "italy": "italya",
    "ispanya": "ispanya",
    "spain": "ispanya",
    "japonya": "japonya",
    "japan": "japonya",
    "kanada": "kanada",
    "canada": "kanada",
    "rusya": "rusya",
    "russia": "rusya",
    "brezilya": "brezilya",
    "brazil": "brezilya",
    "hindistan": "hindistan",
    "india": "hindistan",
    "guney kore": "guney kore",
    "south korea": "guney kore",
    "kuzey kore": "kuzey kore",
    "north korea": "kuzey kore",
    "suudi arabistan": "suudi arabistan",
    "saudi arabia": "suudi arabistan",
    "misir": "misir",
    "egypt": "misir",
    "avustralya": "avustralya",
    "australia": "avustralya",
    "yeni zelanda": "yeni zelanda",
    "new zealand": "yeni zelanda",
    "guney afrika": "guney afrika",
    "south africa": "guney afrika",
    "meksika": "meksika",
    "mexico": "meksika",
    "arjantin": "arjantin",
    "argentina": "arjantin",
    "kolombiya": "kolombiya",
    "colombia": "kolombiya",
    "hollanda": "benelux(belcika, hollanda, luksemburg)",
    "netherlands": "benelux(belcika, hollanda, luksemburg)",
    "belcika": "benelux(belcika, hollanda, luksemburg)",
    "belgium": "benelux(belcika, hollanda, luksemburg)",
    "isvicre": "isvicre",
    "switzerland": "isvicre",
    "norvec": "norvec",
    "norway": "norvec",
    "isvec": "isvec",
    "sweden": "isvec",
    "danimarka": "danimarka",
    "denmark": "danimarka",
    "finlandiya": "finlandiya",
    "finland": "finlandiya",
    "polonya": "polonya",
    "poland": "polonya",
    "portekiz": "portekiz",
    "portugal": "portekiz",
    "yunanistan": "yunanistan",
    "greece": "yunanistan",
    "israil": "israil",
    "israel": "israil",
    "iran": "iran",
    "irak": "irak",
    "iraq": "irak",
    "fas": "fas",
    "morocco": "fas",
    "tunus": "tunus",
    "tunisia": "tunus",
    "kenya": "kenya",
    "nijerya": "nijerya",
    "nigeria": "nijerya",
    "hong kong": "hong kong(cin)",
    "tayvan": "tayvan",
    "taiwan": "tayvan",
    "singapur": "singapur",
    "singapore": "singapur",
    "malezya": "malezya",
    "malaysia": "malezya",
    "tayland": "tayland",
    "thailand": "tayland",
    "vietnam": "vietnam",
    "endonezya": "endonezya",
    "indonesia": "endonezya",
    "filipinler": "filipinler",
    "philippines": "filipinler",
    "pakistan": "pakistan",
    "ukrayna": "ukrayna",
    "ukraine": "ukrayna",
    "romanya": "romanya",
    "romania": "romanya",
    "macaristan": "macaristan",
    "hungary": "macaristan",
    "cek cumhuriyeti": "cek cumhuriyeti",
    "czech republic": "cek cumhuriyeti",
    "sirbistan": "sirbistan",
    "serbia": "sirbistan",
    "hirvatistan": "hirvatistan",
    "croatia": "hirvatistan",
    "bulgaristan": "bulgaristan",
    "bulgaria": "bulgaristan",
    "irlanda": "irlanda",
    "ireland": "irlanda",
    "avusturya": "avusturya",
    "austria": "avusturya",
    "azerbaycan": "azerbaycan",
    "azerbaijan": "azerbaycan",
    "gurcistan": "gurcistan",
    "georgia": "gurcistan",
    "kazakistan": "kazakistan",
    "kazakhstan": "kazakistan",
    "ozbekistan": "ozbekistan",
    "uzbekistan": "ozbekistan",
    "katar": "katar",
    "qatar": "katar",
    "kuveyt": "kuveyt",
    "kuwait": "kuveyt",
    "bahreyn": "bahreyn",
    "bahrain": "bahreyn",
    "umman": "umman",
    "oman": "umman",
    "urdun": "urdun",
    "jordan": "urdun",
    "lubnan": "lubnan",
    "lebanon": "lubnan",
    "suriye": "suriye",
    "syria": "suriye",
    "kibris": "guney kibris rum yonetimi",
    "cyprus": "guney kibris rum yonetimi",
    "kktc": "kuzey kibris turk cumhuriyeti",
    "kosova": "kosova",
    "kosovo": "kosova",
    "arnavutluk": "arnavutluk",
    "albania": "arnavutluk",
    "makedonya": "makedonya",
    "macedonia": "makedonya",
    "bosna hersek": "bosna hersek",
    "bosnia": "bosna hersek",
    "karadag": "karadag",
    "montenegro": "karadag",
    "izlanda": "izlanda",
    "iceland": "izlanda",
    "estonya": "estonya",
    "estonia": "estonya",
    "letonya": "letonya",
    "latvia": "letonya",
    "litvanya": "litvanya",
    "lithuania": "litvanya",
}


def _normalize(text: str) -> str:
    """Normalize text for matching: lowercase, strip accents/special chars."""
    # Handle Turkish İ/I before lowercasing
    text = text.replace("İ", "i").replace("I", "i")
    text = text.lower().strip()
    replacements = {
        "ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c",
        "â": "a", "î": "i", "û": "u", "é": "e", "è": "e", "ê": "e",
        "ä": "a", "ë": "e", "ï": "i", "\u0307": "",  # combining dot above
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _load() -> None:
    """Load and index country data."""
    global _countries, _by_code, _by_name

    if _countries:
        return

    if not _DATA_PATH.exists():
        return

    with open(_DATA_PATH, encoding="utf-8") as f:
        _countries = json.load(f)

    for entry in _countries:
        code = entry.get("ulke_kodu")
        if code and isinstance(code, str) and len(code) <= 10:
            code_upper = code.strip().upper()
            if code_upper not in _by_code:
                _by_code[code_upper] = []
            _by_code[code_upper].append(entry)

        name = entry.get("ulke", "")
        if name:
            normalized = _normalize(name)
            _by_name[normalized] = entry

            # Also index the base name without parentheses
            # e.g. "Anguilla (Birleşik Krallık)" -> also index "anguilla"
            if "(" in normalized:
                base_name = normalized.split("(")[0].strip()
                if base_name and len(base_name) >= 3 and base_name not in _by_name:
                    _by_name[base_name] = entry


_load()


def find_country(query: str) -> dict | None:
    """Find a country by name, code, or alias.

    Returns the full country dict or None if not found.
    """
    if not query:
        return None

    q = query.strip()

    # 1. Try exact code match
    code_upper = q.upper()
    if code_upper in _by_code:
        return _by_code[code_upper][0]

    # 2. Try alias
    normalized = _normalize(q)
    alias_target = _ALIASES.get(normalized)
    if alias_target:
        # Prefer exact match first
        if alias_target in _by_name:
            return _by_name[alias_target]
        # Then substring match
        for name_key, entry in _by_name.items():
            if alias_target in name_key:
                return entry

    # 3. Try exact normalized name match first
    if normalized in _by_name:
        return _by_name[normalized]

    # 4. Try substring match — prefer entries where the name starts with query
    best = None
    for name_key, entry in _by_name.items():
        if normalized in name_key:
            if name_key.startswith(normalized):
                return entry
            if best is None:
                best = entry
    if best is not None:
        return best

    return None


# Terms that should NOT trigger country detection.
# These are general IP terms that contain substrings matching country names/codes.
_IGNORE_TERMS = {
    "nice", "nice siniflandirmasi", "aripo", "madrid", "madrid sistemi",
    "madrid protokolu", "oapi", "eutm", "wipo", "pct", "patent",
    "marka", "tescil", "tasarim", "telif", "sinif", "siniflandirma",
    "basvuru", "koruma", "vekaletname", "emtia", "hizmet",
}


def detect_country_from_question(question: str) -> dict | None:
    """Try to detect a country mentioned in a question.

    Only returns a match when there is high confidence that the user
    is asking about a specific country. General IP terms are ignored.
    """
    normalized = _normalize(question)

    # If the question is dominated by general IP terms, skip detection
    words_in_q = set(normalized.split())
    if words_in_q and words_in_q.issubset(_IGNORE_TERMS | {"nedir", "ne", "neyi", "kapsar", "hakkinda", "bilgi", "ver", "nda", "da", "de", "mi", "nasil", "yapilir", "nelerdir"}):
        return None

    # 1. Check multi-word aliases first (most reliable, longest first)
    for alias, _ in sorted(_ALIASES.items(), key=lambda x: -len(x[0])):
        if len(alias) < 3:
            continue
        # Require word boundary: alias must not be part of a larger word
        pattern = r'(?:^|[\s\'\'\"\,\.\?\!])' + re.escape(alias) + r'(?:[\s\'\'\"\,\.\?\!\']|$)'
        if re.search(pattern, normalized):
            return find_country(alias)

    # 2. Check country names in DB (longest match first, min 4 chars to avoid false positives)
    for name_key in sorted(_by_name.keys(), key=len, reverse=True):
        if len(name_key) < 4:
            continue
        pattern = r'(?:^|[\s\'\'\"\,\.\?\!])' + re.escape(name_key) + r'(?:[\s\'\'\"\,\.\?\!\']|$)'
        if re.search(pattern, normalized):
            return _by_name[name_key]

    return None


def format_country_context(country: dict) -> str:
    """Format country data as context text for the LLM."""
    lines = []
    field_labels = {
        "ulke": "Ulke",
        "ulke_kodu": "Ulke Kodu",
        "madrid": "Madrid Sistemi",
        "ulkesel": "Ulkesel Basvuru",
        "eutm": "EUTM",
        "oapi": "OAPI",
        "aripo": "ARIPO",
        "benzerlik_incelemesi": "Benzerlik Incelemesi",
        "itiraz_suresi": "Itiraz Suresi",
        "tescil_suresi": "Tescil Suresi",
        "koruma_suresi": "Koruma Suresi",
        "kullanmama_iptal": "Kullanmama Nedeniyle Iptal (yil)",
        "itiraz_mercii": "Itiraz Mercii",
        "temyiz_mercii": "Temyiz Mercii",
        "iptal_mercii": "Iptal Mercii",
        "kullanim_beyani": "Kullanim Beyani",
        "ozel_notlar": "Ozel Notlar",
        "zorunlu_evraklar": "Zorunlu Evraklar",
    }

    for key, label in field_labels.items():
        value = country.get(key)
        if value and str(value).strip():
            lines.append(f"{label}: {value}")

    return "\n".join(lines)


def get_all_country_names() -> list[str]:
    """Return list of all country names (for reference)."""
    return [e.get("ulke", "") for e in _countries if e.get("ulke")]
