"""Parse WIPO trademark law PDFs and add legal_provisions to countries_parsed.json."""

import json
import os
import re
import sys
import unicodedata

from PyPDF2 import PdfReader

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "wipo main IP laws_TRADEMARK")
JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "countries_parsed.json")

# ── Mapping from PDF filename (without .pdf) to country name in JSON ──
# Keys are normalized PDF names, values are the "country" field in JSON.
# Only needed when the PDF name doesn't match the JSON name directly.
FILENAME_TO_COUNTRY = {
    "afghanistan": "Afghanistan",
    "albania": "Albania",
    "algeria": "Algeria",
    "andorra": "Andorra",
    "angola": "Angola",
    "antigua and barbuda": "Antigua and Barbuda",
    "argentina": "Argentina",
    "armenia": "Armenia",
    "australia": "Australia",
    "austria": "Austria",
    "azerbaijan": "Azerbaijan",
    "bahamas": "Bahamas",
    "bahrain": "Bahrain",
    "bangladesh": "Bangladesh",
    "belarus": "Belarus",
    "belgium": "Benelux (Belgium, Netherlands, Luxembourg)",
    "bolivia": "Bolivia",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "brazil": "Brazil",
    "brunei darussalam": "Brunei Darussalam",
    "bulgaria": "Bulgaria",
    "cabo verde": "Cape Verde (Cabo Verde)",
    "cambodia": "Cambodia",
    "cameroon": "Cameroon",
    "canada": "Canada",
    "chad": "Chad",
    "chile": "Chile",
    "china": "China",
    "colombia": "Colombia",
    "comoros": "Comoros",
    "congo": "Congo",
    "cook islands": "Cook Islands",
    "costa rica": "Costa Rica",
    "côte d'ivoire": "Ivory Coast",
    "croatia": "Croatia",
    "cuba": "Cuba",
    "cyprus": "Cyprus",
    "czech republic": "Czech Republic",
    "democratic people's republic of korea": "Democratic People's Republic of Korea",
    "democratic republic of the congo": "Democratic Republic of the Congo",
    "denmark": "Denmark",
    "djibouti": "Djibouti",
    "dominica": "Dominica",
    "dominican republic": "Dominican Republic",
    "ecuador": "Ecuador",
    "egypt": "Egypt",
    "el salvador": "El Salvador",
    "equatorial guinea": "Equatorial Guinea",
    "eritrea": "Eritrea",
    "estonia": "Estonia",
    "eswatini": "Eswatini",
    "ethiopia": "Ethiopia",
    "european union (eu)": "European Union (EU)",
    "finland": "Finland",
    "france": "France",
    "gambia": "Gambia",
    "germany": "Germany",
    "ghana": "Ghana",
    "greece": "Greece",
    "guatemala": "Guatemala",
    "guinea-bissau": "Guinea-Bissau",
    "guinea": "Guinea",
    "holy see": "Vatican",
    "honduras": "Honduras",
    "hong kong, china": "Hong Kong (China)",
    "hungary": "Hungary",
    "iceland": "Iceland",
    "india": "India",
    "indonesia": "Indonesia",
    "iran (islamic republic of)": "Iran",
    "iraq": "Iraq",
    "ireland": "Ireland",
    "israel": "Israel",
    "italy": "Italy",
    "jamaica": "Jamaica",
    "japan": "Japan",
    "jordan": "Jordan",
    "kazakhstan": "Kazakhstan",
    "kuwait": "Kuwait",
    "kyrgyzstan": "Kyrgyzstan",
    "lao people's democratic republic": "Lao People's Democratic Republic",
    "latvia": "Latvia",
    "lebanon": "Lebanon",
    "liberia": "Liberia",
    "libya": "Libya",
    "liechtenstein": "Liechtenstein",
    "lithuania": "Lithuania",
    "luxembourg": "Benelux (Belgium, Netherlands, Luxembourg)",
    "madagascar": "Madagascar",
    "malawi": "Malawi",
    "malaysia": "Malaysia",
    "maldives": "Maldives",
    "mali": "Mali",
    "marshall islands": "Marshall Islands",
    "mauritania": "Mauritania",
    "mauritius": "Mauritius",
    "mexico": "Mexico",
    "micronesia (federated states of)": "Micronesia",
    "monaco": "Monaco",
    "mongolia": "Mongolia",
    "montenegro": "Montenegro",
    "morocco": "Morocco",
    "mozambique": "Mozambique",
    "myanmar": "Myanmar",
    "namibia": "Namibia",
    "nauru": "Nauru",
    "nepal": "Nepal",
    "netherlands (kingdom of the)": "Netherlands",
    "new zealand": "New Zealand",
    "nicaragua": "Nicaragua",
    "niger": "Niger",
    "nigeria": "Nigeria",
    "north macedonia": "North Macedonia",
    "norway": "Norway",
    "oapi": None,  # Regional body
    "oman": "Oman",
    "pakistan": "Pakistan",
    "palau": "Palau",
    "panama": "Panama",
    "papua new guinea": "Papua New Guinea",
    "peru": "Peru",
    "philippines": "Philippines",
    "poland": "Poland",
    "portugal": "Portugal",
    "qatar": "Qatar",
    "republic of korea": "South Korea",
    "republic of moldova": "Moldova",
    "romania": "Romania",
    "russian federation": "Russia",
    "rwanda": "Rwanda",
    "saint kitts and nevis": "Saint Kitts and Nevis",
    "saint lucia": "Saint Lucia",
    "saint vincent and the grenadines": "Saint Vincent and the Grenadines",
    "samoa": "Samoa",
    "san marino": "San Marino",
    "sao tome and principe": "Sao Tome and Principe",
    "saudi arabia": "Saudi Arabia",
    "senegal": "Senegal",
    "serbia": "Serbia",
    "seychelles": "Seychelles",
    "sierra leone": "Sierra Leone",
    "singapore": "Singapore",
    "slovakia": "Slovakia",
    "slovenia": "Slovenia",
    "solomon islands": "Solomon Islands",
    "somalia": "Somalia",
    "south africa": "South Africa",
    "south sudan": "South Sudan",
    "spain": "Spain",
    "sri lanka": "Sri Lanka",
    "sudan": "Sudan",
    "suriname": "Suriname",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "syrian arab republic": "Syria",
    "tajikistan": "Tajikistan",
    "thailand": "Thailand",
    "timor-leste": "Timor-Leste",
    "trinidad and tobago": "Trinidad and Tobago",
    "tunisia": "Tunisia",
    "turkmenistan": "Turkmenistan",
    "türkiye": "Turkiye",
    "ukraine": "Ukraine",
    "united arab emirates": "United Arab Emirates",
    "united kingdom": "United Kingdom",
    "united republic of tanzania": "Tanzania",
    "united states of america": "United States of America",
    "uzbekistan": "Uzbekistan",
    "viet nam": "Vietnam",
    "venezuela (bolivarian republic of)": "Venezuela",
    "yemen": "Yemen",
    "zambia": "Zambia",
    "zimbabwe": "Zimbabwe",
    # Regional bodies - skip
    "andean community": None,
}


def _normalize(text: str) -> str:
    """Normalize text for comparison (lowercase, strip accents for matching)."""
    text = text.lower().strip()
    # Normalize Turkish İ/I
    text = text.replace("İ", "i").replace("I", "ı")
    # Remove combining characters
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _find_country_in_json(pdf_name: str, countries: list[dict]) -> dict | None:
    """Find a country entry in JSON by PDF filename."""
    lower_name = pdf_name.lower().strip()

    # Check explicit mapping first
    if lower_name in FILENAME_TO_COUNTRY:
        target = FILENAME_TO_COUNTRY[lower_name]
        if target is None:
            return None  # Skip regional/non-country entries
        for c in countries:
            if c.get("country", "").strip() == target:
                return c
        return None

    # Try direct match on country field
    norm_pdf = _normalize(pdf_name)
    for c in countries:
        country = c.get("country", "")
        norm_country = _normalize(country)
        if norm_country == norm_pdf:
            return c
        # Also match base name (before parentheses)
        base = country.split("(")[0].strip()
        if _normalize(base) == norm_pdf:
            return c

    return None


# ── Article parsing patterns ──
# Different countries use different article formats

ARTICLE_PATTERNS = [
    # "Article 1:", "Article 1.", "Article 1 -", "Article 1\n"
    re.compile(
        r"^(Article\s+\d+[\w.-]*)\s*[:.\-–—]?\s*(.*?)$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # "Art. 1:", "Art. 1."
    re.compile(
        r"^(Art\.?\s+\d+[\w.-]*)\s*[:.\-–—]?\s*(.*?)$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # "Section 1:", "Section 1."
    re.compile(
        r"^(Section\s+\d+[\w.-]*)\s*[:.\-–—]?\s*(.*?)$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # "§ 1", "§1"
    re.compile(
        r"^(§\s*\d+[\w]*)\s*[:.\-–—]?\s*(.*?)$",
        re.MULTILINE,
    ),
    # "Artículo 1" (Spanish)
    re.compile(
        r"^(Art[ií]culo\s+\d+[\w.-]*)\s*[:.\-–—]?\s*(.*?)$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # "Articolo 1" (Italian)
    re.compile(
        r"^(Articolo\s+\d+[\w.-]*)\s*[:.\-–—]?\s*(.*?)$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # "Artikel 1" (German/Dutch)
    re.compile(
        r"^(Artikel\s+\d+[\w.-]*)\s*[:.\-–—]?\s*(.*?)$",
        re.MULTILINE | re.IGNORECASE,
    ),
]


def extract_text_from_pdf(path: str) -> str:
    """Extract all text from a PDF file."""
    reader = PdfReader(path)
    pages_text = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages_text.append(text)
    return "\n".join(pages_text)


def parse_articles(text: str) -> list[dict]:
    """Parse articles/sections from the extracted text."""
    # Find which pattern matches best
    best_matches = []
    best_pattern = None

    for pattern in ARTICLE_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) > len(best_matches):
            best_matches = matches
            best_pattern = pattern

    if not best_matches or not best_pattern:
        return []

    articles = []
    for i, match in enumerate(best_matches):
        article_id = match.group(1).strip()
        title_hint = match.group(2).strip() if match.group(2) else ""

        # Content is between this match and the next
        start = match.end()
        end = best_matches[i + 1].start() if i + 1 < len(best_matches) else len(text)
        content = text[start:end].strip()

        # Clean up: remove excessive whitespace
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = content.strip()

        # Extract article number
        num_match = re.search(r"\d+[\w.-]*", article_id)
        article_num = num_match.group(0) if num_match else article_id

        # Title: use the hint from the same line, or first line of content
        title = title_hint
        if not title and content:
            first_line = content.split("\n")[0].strip()
            if len(first_line) < 200:
                title = first_line

        # Truncate very long content to avoid bloating JSON
        if len(content) > 5000:
            content = content[:5000] + "..."

        articles.append({
            "number": article_num,
            "title": title[:300] if title else "",
            "content": content,
        })

    return articles


def main() -> None:
    # Load existing JSON
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        countries = json.load(f)

    pdf_dir = os.path.abspath(PDF_DIR)
    if not os.path.isdir(pdf_dir):
        print(f"ERROR: PDF directory not found: {pdf_dir}")
        sys.exit(1)

    pdf_files = sorted(f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf"))
    print(f"Found {len(pdf_files)} PDFs to process")

    stats = {"matched": 0, "new": 0, "skipped": 0, "errors": 0}

    for pdf_file in pdf_files:
        pdf_name = pdf_file.replace(".pdf", "")
        pdf_path = os.path.join(pdf_dir, pdf_file)

        try:
            # Find matching country
            country = _find_country_in_json(pdf_name, countries)

            # Extract and parse PDF
            text = extract_text_from_pdf(pdf_path)
            articles = parse_articles(text)

            if not articles:
                print(f"  SKIP {pdf_name}: no articles parsed")
                stats["skipped"] += 1
                continue

            legal_provisions = {
                "source": "WIPO",
                "law_type": "trademark",
                "total_articles": len(articles),
                "articles": articles,
            }

            if country is not None:
                # Update existing country
                country["legal_provisions"] = legal_provisions
                stats["matched"] += 1
                print(f"  OK   {pdf_name} -> {country.get('country', '?')} ({len(articles)} articles)")
            else:
                # Check if we should skip (e.g., regional bodies)
                lower_name = pdf_name.lower().strip()
                if lower_name in FILENAME_TO_COUNTRY and FILENAME_TO_COUNTRY[lower_name] is None:
                    print(f"  SKIP {pdf_name}: regional/non-country entry")
                    stats["skipped"] += 1
                    continue

                # Create new country entry
                new_entry = {
                    "number": len(countries) + 1,
                    "country": pdf_name,
                    "country_code": None,
                    "madrid": None,
                    "national": None,
                    "eutm": None,
                    "oapi": None,
                    "aripo": None,
                    "similarity_examination": None,
                    "opposition_period": None,
                    "registration_period": None,
                    "protection_period": None,
                    "non_use_cancellation": None,
                    "opposition_authority": None,
                    "appeal_authority": None,
                    "cancellation_authority": None,
                    "declaration_of_use": None,
                    "special_notes": None,
                    "required_documents": None,
                    "legal_provisions": legal_provisions,
                }
                countries.append(new_entry)
                stats["new"] += 1
                print(f"  NEW  {pdf_name} ({len(articles)} articles)")

        except Exception as e:
            print(f"  ERR  {pdf_name}: {e}")
            stats["errors"] += 1

    # Save updated JSON
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(countries, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Matched: {stats['matched']}, New: {stats['new']}, "
          f"Skipped: {stats['skipped']}, Errors: {stats['errors']}")
    print(f"Total countries in JSON: {len(countries)}")


if __name__ == "__main__":
    main()
