"""Translate countries_parsed.json from Turkish to English field names and values."""

import json
import os
import re

JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "countries_parsed.json")

# ── Field name mapping: Turkish → English ──
FIELD_MAP = {
    "numara": "number",
    "ulke": "country",
    "ulke_kodu": "country_code",
    "madrid": "madrid",
    "ulkesel": "national",
    "eutm": "eutm",
    "oapi": "oapi",
    "aripo": "aripo",
    "benzerlik_incelemesi": "similarity_examination",
    "itiraz_suresi": "opposition_period",
    "tescil_suresi": "registration_period",
    "koruma_suresi": "protection_period",
    "kullanmama_iptal": "non_use_cancellation",
    "itiraz_mercii": "opposition_authority",
    "temyiz_mercii": "appeal_authority",
    "iptal_mercii": "cancellation_authority",
    "kullanim_beyani": "declaration_of_use",
    "ozel_notlar": "special_notes",
    "zorunlu_evraklar": "required_documents",
    "legal_provisions": "legal_provisions",
}

# ── Turkish country name → English country name ──
COUNTRY_NAME_MAP = {
    "ABHAZİA": "Abkhazia",
    "AFGANİSTAN": "Afghanistan",
    "ALMANYA": "Germany",
    "AMERİKA BİRLEŞİK DEVLETLERİ": "United States of America",
    "ANDORRA": "Andorra",
    "ANGOLA": "Angola",
    "ANGUİLLA, İNGİLTERE": "Anguilla (United Kingdom)",
    "ANTİGUA VE BARBUDA": "Antigua and Barbuda",
    "ARJANTİN": "Argentina",
    "ARNAVUTLUK": "Albania",
    "ARUBA(Hollanda)": "Aruba (Netherlands)",
    "ARUBA, HOLLANDA": "Aruba (Netherlands)",
    "AVUSTRALYA": "Australia",
    "AVUSTURYA": "Austria",
    "AZERBAYCAN": "Azerbaijan",
    "Anguilla (Birleşik Krallık)": "Anguilla (United Kingdom)",
    "Ashmore ve Cartier Adaları (Avustralya)": "Ashmore and Cartier Islands (Australia)",
    "Ağrotur ve Dikelya (Birleşik Krallık)": "Akrotiri and Dhekelia (United Kingdom)",
    "AVRUPA BİRLİĞİ (EUTM)": "European Union (EUTM)",
    "AVRUPA BİRLİĞİ (EUTM - EUIPO)": "European Union (EUTM - EUIPO)",
    "BAHAMA ADALARI": "Bahamas",
    "BAHREYN": "Bahrain",
    "BANGLADEŞ": "Bangladesh",
    "BARBADOS": "Barbados",
    "BATI SAHRA": "Western Sahara",
    "BATI ŞERİA(Filistin)": "West Bank (Palestine)",
    "BELİZE": "Belize",
    "BENELUX(BELÇİKA, HOLLANDA, LÜKSEMBURG)": "Benelux (Belgium, Netherlands, Luxembourg)",
    "BENİN": "Benin",
    "BERMUDA, İNGİLTERE": "Bermuda (United Kingdom)",
    "BEYAZ RUSYA": "Belarus",
    "BHUTAN": "Bhutan",
    "BOLİVYA": "Bolivia",
    "BONAIRE, SINT EUSTATIUS AND SABA": "Bonaire, Sint Eustatius and Saba",
    "BOSNA HERSEK": "Bosnia and Herzegovina",
    "BOTSWANA": "Botswana",
    "BOUVET ISLAND (Norveç)": "Bouvet Island (Norway)",
    "BREZİLYA": "Brazil",
    "BRUNEI DARUSSALAM": "Brunei Darussalam",
    "BULGARİSTAN": "Bulgaria",
    "BURKİNA FASO": "Burkina Faso",
    "BURUNDİ": "Burundi",
    "Bermuda (Birleşik Krallık)": "Bermuda (United Kingdom)",
    "Britanya Hint Okyanusu Toprakları (Birleşik Krallık)": "British Indian Ocean Territory (United Kingdom)",
    "Britanya Virjin Adaları (Birleşik Krallık)": "British Virgin Islands (United Kingdom)",
    "BİRLEŞİK ARAP EMİRLİKLERİ": "United Arab Emirates",
    "BİRLEŞİK KRALLIK": "United Kingdom",
    "BİRMANYA (MYANMAR)": "Myanmar",
    "CAPE VERDE(Yeşil Burun Adaları, CABO VERDE)": "Cape Verde",
    "CAYMAN ADALARI, İNGİLTERE": "Cayman Islands (United Kingdom)",
    "CEZAYİR": "Algeria",
    "CHRİSTMAS ADASI , AVUSTURALYA": "Christmas Island (Australia)",
    "COOK ISLANDS": "Cook Islands",
    "CURACAO": "Curaçao",
    "Cayman Adaları (Birleşik Krallık)": "Cayman Islands (United Kingdom)",
    "Cebelitarık (Birleşik Krallık)": "Gibraltar (United Kingdom)",
    "Christmas Adası (Avustralya)": "Christmas Island (Australia)",
    "Cocos Adaları (Avustralya)": "Cocos Islands (Australia)",
    "Cook Adaları (Yeni Zelanda)": "Cook Islands (New Zealand)",
    "CİBUTİ": "Djibouti",
    "DANİMARKA": "Denmark",
    "DEMOCRATIC PEOPLE'S REPUBLIC OF KOREA": "North Korea",
    "DOMİNİK CUMHURİYETİ": "Dominican Republic",
    "DOMİNİKA": "Dominica",
    "EKVADOR": "Ecuador",
    "EKVATOR GİNESİ": "Equatorial Guinea",
    "EL SALVADOR": "El Salvador",
    "ENDONEZYA": "Indonesia",
    "ERİTRE": "Eritrea",
    "ERMENİSTAN": "Armenia",
    "ESTONYA": "Estonia",
    "ESWATINI(Eski Swaziland)": "Eswatini",
    "ETİYOPYA": "Ethiopia",
    "Falkland Adaları (Birleşik Krallık)": "Falkland Islands (United Kingdom)",
    "FAS": "Morocco",
    "FİJİ": "Fiji",
    "FİLDİŞİ SAHİLİ": "Côte d'Ivoire",
    "FİLİPİNLER": "Philippines",
    "FİNLANDİYA": "Finland",
    "FRANSA": "France",
    "Fransız Güney Toprakları (Fransa)": "French Southern Territories (France)",
    "Fransız Polinezyası (Fransa)": "French Polynesia (France)",
    "GABON": "Gabon",
    "GANA": "Ghana",
    "GAMBİYA": "Gambia",
    "GRENADA": "Grenada",
    "GUATEMALA": "Guatemala",
    "GUYANA": "Guyana",
    "Guadeloupe (Fransa)": "Guadeloupe (France)",
    "Guam (ABD)": "Guam (USA)",
    "Guernsey (Birleşik Krallık)": "Guernsey (United Kingdom)",
    "Guyane (Fransa)": "French Guiana (France)",
    "GİNE": "Guinea",
    "GİNE BİSSAU": "Guinea-Bissau",
    "GÜNEY AFRİKA": "South Africa",
    "GÜNEY KIBRIS RUM YÖNETİMİ": "Cyprus",
    "GÜNEY KORE": "South Korea",
    "HAİTİ": "Haiti",
    "HINDİSTAN": "India",
    "HIRVATİSTAN": "Croatia",
    "HONDURAS": "Honduras",
    "HONG KONG(Çin)": "Hong Kong (China)",
    "IRAK": "Iraq",
    "Jersey (Birleşik Krallık)": "Jersey (United Kingdom)",
    "JAMAIKA": "Jamaica",
    "JAMAİKA": "Jamaica",
    "JAPONYA": "Japan",
    "KAMBOÇYA": "Cambodia",
    "KAMERUN": "Cameroon",
    "KANADA": "Canada",
    "KARADAĞ": "Montenegro",
    "KATAR": "Qatar",
    "KAZAKİSTAN": "Kazakhstan",
    "KENYA": "Kenya",
    "KIRGIZİSTAN": "Kyrgyzstan",
    "KİRİBATİ": "Kiribati",
    "KOLOMBİYA": "Colombia",
    "KOMORLAR": "Comoros",
    "KONGO": "Congo",
    "KONGO DEMOKRATİK CUMHURİYETİ": "Democratic Republic of the Congo",
    "KOSOVA": "Kosovo",
    "KOSTA RİKA": "Costa Rica",
    "KUVEYT": "Kuwait",
    "KUZEY KIBRIS TÜRK CUMHURİYETİ": "Northern Cyprus",
    "KUZEY KORE": "North Korea",
    "KUZEY MAKEDONYA": "North Macedonia",
    "KÜBA": "Cuba",
    "LAO PEOPLE'S DEMOCRATIC REPUBLIC": "Laos",
    "LESOTHO": "Lesotho",
    "LETONYA": "Latvia",
    "LÜBNAN": "Lebanon",
    "LİBERYA": "Liberia",
    "LİBYA": "Libya",
    "LİHTENŞTAYN": "Liechtenstein",
    "LİTVANYA": "Lithuania",
    "MACARİSTAN": "Hungary",
    "MADAGASKAR": "Madagascar",
    "MALAVİ": "Malawi",
    "MALDİVLER": "Maldives",
    "MALEZYA": "Malaysia",
    "MALİ": "Mali",
    "MALTA": "Malta",
    "Man Adası (Birleşik Krallık)": "Isle of Man (United Kingdom)",
    "MARSHALL ADALARI": "Marshall Islands",
    "Martinique (Fransa)": "Martinique (France)",
    "MAURİTİUS(REPUBLIC OF MAURITUS)": "Mauritius",
    "Mayotte (Fransa)": "Mayotte (France)",
    "MEKSİKA": "Mexico",
    "MISIR": "Egypt",
    "MİKRONEZYA": "Micronesia",
    "MOLDOVA": "Moldova",
    "MONAKO": "Monaco",
    "MOĞOLİSTAN": "Mongolia",
    "MORİTANYA": "Mauritania",
    "MOZAMBİK": "Mozambique",
    "NAMİBYA": "Namibia",
    "NAURU": "Nauru",
    "NEPAL": "Nepal",
    "Niue (Yeni Zelanda)": "Niue (New Zealand)",
    "NİJER": "Niger",
    "NİJERYA": "Nigeria",
    "NİKARAGUA": "Nicaragua",
    "NORFOLK ADALARI, AVUSTRALYA": "Norfolk Island (Australia)",
    "NORTH MARIANA ISLANDS(ABD)": "Northern Mariana Islands (USA)",
    "NORVEÇ": "Norway",
    "HOLLANDA": "Netherlands",
    "OAPI": "OAPI",
    "UMMAN": "Oman",
    "ÖZBEKİSTAN": "Uzbekistan",
    "PAKİSTAN": "Pakistan",
    "PALAU ADALARI": "Palau",
    "PANAMA": "Panama",
    "PAPUA YENİ GİNE": "Papua New Guinea",
    "PARAGUAY": "Paraguay",
    "PERU": "Peru",
    "POLONYA": "Poland",
    "PORTEKİZ": "Portugal",
    "Pitcairn Adaları (Birleşik Krallık)": "Pitcairn Islands (United Kingdom)",
    "ROMANYA": "Romania",
    "RUANDA": "Rwanda",
    "RUSYA": "Russia",
    "Réunion (Fransa)": "Réunion (France)",
    "SAINT PIERRE VE MIQUELON (Fransa)": "Saint Pierre and Miquelon (France)",
    "SAMOA": "Samoa",
    "SAN MARİNO": "San Marino",
    "SANTA KİTTS VE NEVİS": "Saint Kitts and Nevis",
    "SANTA LUCİA": "Saint Lucia",
    "SANTA VİNCENT VE GRENADİNLER": "Saint Vincent and the Grenadines",
    "SAO TOME VE PRİNCİPE": "São Tomé and Príncipe",
    "SAİNT HELENA, İNGİLTERE": "Saint Helena (United Kingdom)",
    "SENEGAL": "Senegal",
    "SEYŞELLER": "Seychelles",
    "SIRBİSTAN": "Serbia",
    "SLOVAKYA": "Slovakia",
    "SLOVENYA": "Slovenia",
    "SOLOMON ADALARI": "Solomon Islands",
    "SOMALIALAND": "Somaliland",
    "SOMALİ": "Somalia",
    "SOUTH SUDAN": "South Sudan",
    "SRİ LANKA": "Sri Lanka",
    "SUDAN": "Sudan",
    "SURİNAM": "Suriname",
    "SURINAM": "Suriname",
    "SURİYE": "Syria",
    "SUUDİ ARABİSTAN": "Saudi Arabia",
    "SVALBARD, NORVEÇ": "Svalbard (Norway)",
    "SYRIAN ARAB REPUBLIC": "Syria",
    "Saint Barthélemy (Fransa)": "Saint Barthélemy (France)",
    "Saint Helena (Birleşik Krallık)": "Saint Helena (United Kingdom)",
    "SiERRA LEONE": "Sierra Leone",
    "Sint Maarten (Hollanda)": "Sint Maarten (Netherlands)",
    "SİNGAPUR": "Singapore",
    "TACİKİSTAN": "Tajikistan",
    "TANGİER": "Tangier",
    "TANZANYA(UNITED REPUBLIC OF TANZANIA)": "Tanzania",
    "TAYLAND": "Thailand",
    "TAYVAN": "Taiwan",
    "THE BAHAMAS": "Bahamas",
    "TIMOR - LESTE": "Timor-Leste",
    "TOGO": "Togo",
    "TONGA": "Tonga",
    "Tokelau (Yeni Zelanda)": "Tokelau (New Zealand)",
    "TRİNİDAD VE TOBAGO": "Trinidad and Tobago",
    "TUNUS": "Tunisia",
    "TURKS VE CAİCOS ADALARI, İNGİLTERE": "Turks and Caicos Islands (United Kingdom)",
    "TUVALU(Birleşik Krallık)": "Tuvalu (United Kingdom)",
    "Turks ve Caicos Adaları (Birleşik Krallık)": "Turks and Caicos Islands (United Kingdom)",
    "TÜRKİYE": "Turkey",
    "TÜRKMENİSTAN": "Turkmenistan",
    "UGANDA": "Uganda",
    "UKRAYNA": "Ukraine",
    "URUGUAY": "Uruguay",
    "VALLİS VE FUTUNA (Fransa)": "Wallis and Futuna (France)",
    "VANUATU": "Vanuatu",
    "VATICAN": "Vatican City",
    "VENEZUELA": "Venezuela",
    "VİETNAM": "Vietnam",
    "VİRGİN ADALARI, AMERİKA": "US Virgin Islands",
    "VİRGİN ADALARI, İNGİLTERE": "British Virgin Islands",
    "WAKE ADALARI, AMERİKA": "Wake Island (USA)",
    "YEMEN": "Yemen",
    "YEMEN (ADEN)": "Yemen (Aden)",
    "YEMEN (SANA)": "Yemen (Sana'a)",
    "YENİ KALEDONYA (Fransa)": "New Caledonia (France)",
    "YENİ ZELANDA": "New Zealand",
    "YUNANİSTAN": "Greece",
    "ZAMBİYA": "Zambia",
    "ZIMBABVE": "Zimbabwe",
    "ÇAD": "Chad",
    "ÇEK CUMHURİYETİ": "Czech Republic",
    "ÇİN": "China",
    "ÜRDÜN": "Jordan",
    "İRAN": "Iran",
    "İRLANDA": "Ireland",
    "İSPANYA": "Spain",
    "İSRAİL": "Israel",
    "İSVEÇ": "Sweden",
    "İSVİÇRE": "Switzerland",
    "İTALYA": "Italy",
    "İZLANDA": "Iceland",
    "ŞİLİ": "Chile",
}

# ── Value translations ──
VALUE_MAP = {
    "EVET": "YES",
    "HAYIR": "NO",
    "evet": "YES",
    "hayır": "NO",
    "Evet": "YES",
    "Hayır": "NO",
}

# Fields that should have YES/NO values
BOOLEAN_FIELDS = {"madrid", "national", "eutm", "oapi", "aripo",
                  "similarity_examination", "declaration_of_use"}

# Turkish text patterns to translate in free-text fields (exact matches for full values)
EXACT_VALUE_MAP = {
    "Yetkili Kurum": "Competent Authority",
    "Mahkeme": "Court",
    "Bilgi mevcut değil.": "Information not available.",
    "Bilgi mevcut değil": "Information not available.",
    "Detayli bilgi icin yetkili IP vekili ile iletisime geciniz.": "Contact an authorized IP attorney for details.",
    "Detaylı bilgi için yetkili IP vekili ile iletişime geçiniz.": "Contact an authorized IP attorney for details.",
}

# Regex-based replacements for duration patterns (word-boundary safe)
import re as _re
REGEX_REPLACEMENTS = [
    (_re.compile(r"(\d+)\s*yıl"), r"\1 years"),
    (_re.compile(r"(\d+)\s*ay\b"), r"\1 months"),
    (_re.compile(r"(\d+)\s*gün\b"), r"\1 days"),
]


def translate_value(key: str, value):
    """Translate a value based on its field."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        # Check YES/NO mapping
        if stripped in VALUE_MAP:
            return VALUE_MAP[stripped]
        # Check exact value matches
        if stripped in EXACT_VALUE_MAP:
            return EXACT_VALUE_MAP[stripped]
        # Apply regex replacements for durations (word-boundary safe)
        result = value
        for pattern, replacement in REGEX_REPLACEMENTS:
            result = pattern.sub(replacement, result)
        return result
    return value


def translate_country_name(name: str) -> str:
    """Translate a Turkish country name to English."""
    if name in COUNTRY_NAME_MAP:
        return COUNTRY_NAME_MAP[name]
    # Try case-insensitive
    for tk, en in COUNTRY_NAME_MAP.items():
        if tk.upper() == name.upper():
            return en
    return name  # Keep original if no mapping found


def translate_entry(entry: dict) -> dict:
    """Translate a single country entry."""
    result = {}
    for old_key, value in entry.items():
        new_key = FIELD_MAP.get(old_key, old_key)

        if old_key == "ulke" and isinstance(value, str):
            result[new_key] = translate_country_name(value)
        elif old_key == "legal_provisions":
            result[new_key] = value  # Keep as-is (already English)
        else:
            result[new_key] = translate_value(new_key, value)

    return result


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Translating {len(data)} country entries...")

    translated = [translate_entry(entry) for entry in data]

    # Check for untranslated country names (still Turkish)
    untranslated = []
    for entry in translated:
        name = entry.get("country", "")
        # Simple heuristic: if name contains Turkish chars like İ, Ş, Ç, Ü, Ö, Ğ
        if any(c in name for c in "İŞÇÜÖĞışçüöğ") and name not in {"São Tomé and Príncipe", "Curaçao", "Côte d'Ivoire"}:
            untranslated.append(name)

    if untranslated:
        print(f"\nWARNING: {len(untranslated)} entries may still have Turkish names:")
        for n in untranslated[:20]:
            print(f"  - {n}")

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Saved {len(translated)} entries.")

    # Show sample
    sample = translated[0]
    print("\nSample entry:")
    print(json.dumps(sample, indent=2, ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
