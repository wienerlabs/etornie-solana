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
    "eu": "european union (eu)",
    "eutm": "european union (eu)",
    "euipo": "european union (eu)",
    "avrupa birligi": "european union (eu)",
    "european union": "european union (eu)",
    "abd": "united states of america",
    "abd'de": "united states of america",
    "usa": "united states of america",
    "america": "united states of america",
    "united states": "united states of america",
    "uk": "united kingdom",
    "ingiltere": "united kingdom",
    "england": "united kingdom",
    "britain": "united kingdom",
    "uae": "united arab emirates",
    "bae": "united arab emirates",
    "cin": "china",
    "china": "china",
    "almanya": "germany",
    "germany": "germany",
    "fransa": "france",
    "france": "france",
    "italya": "italy",
    "italy": "italy",
    "ispanya": "spain",
    "spain": "spain",
    "japonya": "japan",
    "japan": "japan",
    "kanada": "canada",
    "canada": "canada",
    "rusya": "russia",
    "russia": "russia",
    "brezilya": "brazil",
    "brazil": "brazil",
    "hindistan": "india",
    "india": "india",
    "guney kore": "south korea",
    "south korea": "south korea",
    "kuzey kore": "north korea",
    "north korea": "north korea",
    "suudi arabistan": "saudi arabia",
    "saudi arabia": "saudi arabia",
    "misir": "egypt",
    "egypt": "egypt",
    "avustralya": "australia",
    "australia": "australia",
    "yeni zelanda": "new zealand",
    "new zealand": "new zealand",
    "guney afrika": "south africa",
    "south africa": "south africa",
    "meksika": "mexico",
    "mexico": "mexico",
    "arjantin": "argentina",
    "argentina": "argentina",
    "kolombiya": "colombia",
    "colombia": "colombia",
    "hollanda": "benelux (belgium, netherlands, luxembourg)",
    "netherlands": "benelux (belgium, netherlands, luxembourg)",
    "belcika": "benelux (belgium, netherlands, luxembourg)",
    "belgium": "benelux (belgium, netherlands, luxembourg)",
    "isvicre": "switzerland",
    "switzerland": "switzerland",
    "norvec": "norway",
    "norway": "norway",
    "isvec": "sweden",
    "sweden": "sweden",
    "danimarka": "denmark",
    "denmark": "denmark",
    "finlandiya": "finland",
    "finland": "finland",
    "polonya": "poland",
    "poland": "poland",
    "portekiz": "portugal",
    "portugal": "portugal",
    "yunanistan": "greece",
    "greece": "greece",
    "israil": "israel",
    "israel": "israel",
    "iran": "iran",
    "irak": "iraq",
    "iraq": "iraq",
    "fas": "morocco",
    "morocco": "morocco",
    "tunus": "tunisia",
    "tunisia": "tunisia",
    "kenya": "kenya",
    "nijerya": "nigeria",
    "nigeria": "nigeria",
    "hong kong": "hong kong (china)",
    "tayvan": "taiwan",
    "taiwan": "taiwan",
    "singapur": "singapore",
    "singapore": "singapore",
    "malezya": "malaysia",
    "malaysia": "malaysia",
    "tayland": "thailand",
    "thailand": "thailand",
    "vietnam": "vietnam",
    "endonezya": "indonesia",
    "indonesia": "indonesia",
    "filipinler": "philippines",
    "philippines": "philippines",
    "pakistan": "pakistan",
    "ukrayna": "ukraine",
    "ukraine": "ukraine",
    "romanya": "romania",
    "romania": "romania",
    "macaristan": "hungary",
    "hungary": "hungary",
    "cek cumhuriyeti": "czech republic",
    "czech republic": "czech republic",
    "sirbistan": "serbia",
    "serbia": "serbia",
    "hirvatistan": "croatia",
    "croatia": "croatia",
    "bulgaristan": "bulgaria",
    "bulgaria": "bulgaria",
    "irlanda": "ireland",
    "ireland": "ireland",
    "avusturya": "austria",
    "austria": "austria",
    "azerbaycan": "azerbaijan",
    "azerbaijan": "azerbaijan",
    "gurcistan": "georgia",
    "georgia": "georgia",
    "kazakistan": "kazakhstan",
    "kazakhstan": "kazakhstan",
    "ozbekistan": "uzbekistan",
    "uzbekistan": "uzbekistan",
    "katar": "qatar",
    "qatar": "qatar",
    "kuveyt": "kuwait",
    "kuwait": "kuwait",
    "bahreyn": "bahrain",
    "bahrain": "bahrain",
    "umman": "oman",
    "oman": "oman",
    "urdun": "jordan",
    "jordan": "jordan",
    "lubnan": "lebanon",
    "lebanon": "lebanon",
    "suriye": "syria",
    "syria": "syria",
    "kibris": "cyprus",
    "cyprus": "cyprus",
    "kktc": "northern cyprus",
    "kosova": "kosovo",
    "kosovo": "kosovo",
    "arnavutluk": "albania",
    "albania": "albania",
    "makedonya": "makedonya",
    "macedonia": "makedonya",
    "bosna hersek": "bosnia and herzegovina",
    "bosnia": "bosnia and herzegovina",
    "karadag": "montenegro",
    "montenegro": "montenegro",
    "izlanda": "iceland",
    "iceland": "iceland",
    "estonya": "estonia",
    "estonia": "estonia",
    "letonya": "latvia",
    "latvia": "latvia",
    "litvanya": "lithuania",
    "lithuania": "lithuania",
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
        code = entry.get("country_code")
        if code and isinstance(code, str) and len(code) <= 10:
            code_upper = code.strip().upper()
            if code_upper not in _by_code:
                _by_code[code_upper] = []
            _by_code[code_upper].append(entry)

        name = entry.get("country", "")
        if name:
            normalized = _normalize(name)
            _by_name[normalized] = entry

            # Also index the base name without parentheses
            # e.g. "Anguilla (United Kingdom)" -> also index "anguilla"
            if "(" in normalized:
                base_name = normalized.split("(")[0].strip()
                if base_name and len(base_name) >= 3 and base_name not in _by_name:
                    _by_name[base_name] = entry


_load()


def _get_eutm_country_names() -> list[str]:
    """Return sorted list of EUTM member country names."""
    return sorted(
        e.get("country", "")
        for e in _countries
        if (e.get("eutm") or "").upper() == "YES" and e.get("country")
    )


# Virtual entry for EU/EUTM jurisdiction
_EU_ENTRY: dict | None = None


def _build_eu_entry() -> dict:
    """Build a virtual country entry for EU Trademark (EUTM) via EUIPO."""
    global _EU_ENTRY
    if _EU_ENTRY is not None:
        return _EU_ENTRY

    member_names = _get_eutm_country_names()
    members_text = ", ".join(member_names)

    _EU_ENTRY = {
        "country": "European Union (EUTM - EUIPO)",
        "country_code": "EU",
        "madrid": "YES",
        "national": "NO",
        "eutm": "YES",
        "opposition_period": "3 months",
        "registration_period": "4-6 months",
        "protection_period": "10 years",
        "special_notes": (
            f"EUTM (European Union Trade Mark) allows a single application via EUIPO "
            f"valid in all EU member states. "
            f"Covered countries ({len(member_names)}): {members_text}"
        ),
        "required_documents": "Power of Attorney, Trademark specimen, Goods/Services list (Nice classification)",
    }
    return _EU_ENTRY


def find_country(query: str) -> dict | None:
    """Find a country by name, code, or alias.

    Returns the full country dict or None if not found.
    """
    if not query:
        return None

    q = query.strip()

    # 1. Handle EU/EUTM specially
    code_upper = q.upper()
    if code_upper in ("EU", "EUTM", "EUIPO"):
        return _build_eu_entry()

    # 2. Try exact code match
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
    "nice", "nice classification", "aripo", "madrid", "madrid system",
    "madrid protocol", "oapi", "eutm", "wipo", "pct", "patent",
    "trademark", "registration", "design", "copyright", "class", "classification",
    "application", "protection", "power of attorney", "goods", "services",
}


def detect_country_from_question(question: str) -> dict | None:
    """Try to detect a country mentioned in a question.

    Only returns a match when there is high confidence that the user
    is asking about a specific country. General IP terms are ignored.
    """
    normalized = _normalize(question)

    # If the question is dominated by general IP terms, skip detection
    words_in_q = set(normalized.split())
    if words_in_q and words_in_q.issubset(_IGNORE_TERMS | {"what", "is", "how", "does", "do", "the", "a", "an", "in", "for", "about", "which", "are", "can", "it", "take", "long"}):
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
        "country": "Country",
        "country_code": "Country Code",
        "madrid": "Madrid System",
        "national": "National Application",
        "eutm": "EUTM",
        "oapi": "OAPI",
        "aripo": "ARIPO",
        "similarity_examination": "Similarity Examination",
        "opposition_period": "Opposition Period",
        "registration_period": "Registration Period",
        "protection_period": "Protection Period",
        "non_use_cancellation": "Non-Use Cancellation (years)",
        "opposition_authority": "Opposition Authority",
        "appeal_authority": "Appeal Authority",
        "cancellation_authority": "Cancellation Authority",
        "declaration_of_use": "Declaration of Use",
        "special_notes": "Special Notes",
        "required_documents": "Required Documents",
    }

    for key, label in field_labels.items():
        value = country.get(key)
        if value and str(value).strip():
            lines.append(f"{label}: {value}")

    return "\n".join(lines)


def get_all_country_names() -> list[str]:
    """Return list of all country names (for reference)."""
    return [e.get("country", "") for e in _countries if e.get("country")]


def get_all_countries() -> list[dict]:
    """Return the full list of country entries."""
    return _countries
