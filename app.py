"""Wohnungs-Finder Schweiz V12.9. Run with: streamlit run app.py"""
import json
import html
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests
import streamlit as st
from streamlit_local_storage import LocalStorage


POSTCODES = {"Reinach": "4153", "Münchenstein": "4142", "Aesch": "4147", "Muttenz": "4132", "Liestal": "4410", "Frenkendorf": "4402", "Arlesheim": "4144", "Pratteln": "4133", "Binningen": "4102", "Allschwil": "4123"}
DOMAINS = ("homegate.ch", "immoscout24.ch", "flatfox.ch", "newhome.ch")

def number(value):
    if value is None: return None
    match = re.search(r"\d[\d'’.,\s]*", str(value))
    if not match: return None
    s = match.group().strip().replace("'", "").replace("’", "").replace(" ", "")
    if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}[.,]\d{3}", s): s = s.replace(".", "").replace(",", "")
    else: s = s.replace(",", ".")
    try: return float(s)
    except ValueError: return None

def canonical_town(town):
    return re.sub(r"\s+(BL|Basel-Landschaft)$", "", str(town).strip(), flags=re.I)

def listing_url(url):
    p = urlparse(url or "")
    host = p.netloc.lower().removeprefix("www.")
    if not any(host == d or host.endswith("." + d) for d in DOMAINS): return False
    path = p.path.lower()
    if "trefferliste" in path or "ort-" in path or "suche" in path: return False
    if host.endswith("flatfox.ch"):
        return bool(re.fullmatch(r"/de/wohnung/[^/]+/\d{7,12}/?", path))
    if host.endswith("newhome.ch"):
        return bool(re.search(r"/(?:details?|mieten)/[^?]*\d{6,}/?$", path))
    return bool(re.fullmatch(r"/mieten/\d{7,12}/?", path) if host.endswith("homegate.ch") else
                re.fullmatch(r"/de/d/[^/]+/\d{7,12}/?", path) if host.endswith("immoscout24.ch") else False)

def parse_result(raw):
    """Use one search hit only. Reject ambiguous multi-apartment snippets."""
    url = raw.get("url", "")
    if not listing_url(url): return None
    title = str(raw.get("title") or "")
    content = str(raw.get("content") or "")[:1600]
    if re.search(r"\b(?:gewerbe|büro|buero|laden|praxis|lager|verkauf|kaufen|kaufobjekt|"
                 r"eigentumswohnung|einzelzimmer|wg[ -]?zimmer|tiefgaragenplatz)\b",
                 title, re.I): return None
    # Search snippets often contain recommendations. The title and first address block
    # are safer than searching the entire snippet for arbitrary values.
    lead = (title + " " + content[:450]).replace("\u00a0", " ")
    addresses = re.findall(r"([\wÀ-ÿ][\wÀ-ÿ .'-]{2,55}?\s+\d+[a-zA-Z]?),\s*(\d{4})\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ -]+?)(?=\s+(?:CHF|\d(?:[.,]\d)?\s*Zimmer|Top|Premium)|[.;|]|$)", lead, re.I)
    if len({(a[0].casefold(), a[1]) for a in addresses}) > 1: return None
    postcode = re.search(r"\b(\d{4})\s+([A-ZÀ-ÿ][A-Za-zÀ-ÿ-]+)(?:\s+BL)?\b", lead)
    flatfox = "flatfox.ch" in urlparse(url).netloc.lower()
    slug_postcode = re.search(r"-(\d{4})-(?:[a-z-]+?)/\d+/?$", urlparse(url).path, re.I) if flatfox else None
    postal = slug_postcode.group(1) if slug_postcode else postcode.group(1) if postcode else None
    if not postal: return None
    known_town = next((name for name, code in POSTCODES.items() if code == postal), None)
    town = known_town or (postcode.group(2).capitalize() if postcode else None)
    if not town: return None
    if postcode and postcode.group(1) != postal: return None
    rooms = re.search(r"\b(\d(?:[.,]5)?|\d\s*½)\s*(?:-|\s*)Zimmer\b|"
                      r"\bZimmer\s*[.:\-]?\s*(\d(?:[.,]5)?|\d\s*½)\b", lead, re.I)
    if not rooms: return None
    room_text = (rooms.group(1) or rooms.group(2)).replace("½", ".5").replace(" ", "")
    room_value = number(room_text)
    if room_value is None: return None
    # Prefer a price in the title or directly beside this listing's address.
    # Wider snippets can contain recommendations with unrelated prices.
    title_prices = re.findall(r"CHF\s*([\d'’.,]+)", title, re.I)
    price = number(title_prices[0]) if len(title_prices) == 1 else None
    if price is None and addresses:
        address_end = lead.find(addresses[0][0]) + len(addresses[0][0])
        near_address = lead[address_end:address_end + 90]
        adjacent = re.search(rf"^\s*,?\s*{re.escape(postal)}\s+{re.escape(town)}\b"
                             r"[^\d]{0,25}\bCHF\s*([\d'’.,]+)", near_address, re.I)
        if adjacent:
            price = number(adjacent.group(1))
    if price is None:
        prices = re.findall(r"CHF\s*([\d'’.,]+)", lead, re.I)
        price = number(prices[0]) if len(prices) == 1 else None
    if price is not None and price > 20000: return None
    if price is not None and price < 500: price = None
    address = None
    if addresses and postcode:
        a = addresses[0]
        if a[1] == postcode.group(1): address = a[0].strip()
    if address:
        address = re.sub(r"^.*?\b(?:Zimmer\s+Wohnung|Wohnung\s+an\s+der)\s+", "", address, flags=re.I)
        if re.search(r"\bStandort\s*[.:]", address, re.I):
            address = re.split(r"\bStandort\s*[.:]\s*", address, flags=re.I)[-1].strip()
    if "flatfox.ch" in url:
        slug = urlparse(url).path.strip("/").split("/")[-2]
        slug = re.sub(r"-\d{4}-.*$", "", slug)
        if re.search(r"\d", slug): address = slug.replace("-", " ").title()
    return {"url": url, "title": title, "address": address, "town": town,
            "postcode": postal,
            "rooms": room_value, "visible_price": price, "price_kind": "sichtbare Miete" if price else None,
            "source": urlparse(url).netloc, "detail": None}

def budget(detail, visible_price, maximum):
    detail = detail or {}
    gross = detail.get("gross")
    net = detail.get("net")
    charges = detail.get("charges")
    parking = detail.get("parking_cost")
    if gross is None and net is not None and charges is not None: gross = net + charges
    # A visible rent can be net or gross, but the monthly total cannot be lower.
    if visible_price is not None and visible_price > maximum:
        return "budget", visible_price, False
    if net is not None and net > maximum:
        return "budget", net, False
    if gross is not None and gross > maximum: return "budget", gross, False
    if gross is not None and parking is not None and gross + parking > maximum:
        return "budget", gross + parking, False
    total = gross + parking if gross is not None and parking is not None else None
    return None, total, total is None

def filter_listings(items, towns, min_rooms, max_rooms, maximum):
    allowed = {canonical_town(x).casefold() for x in towns}
    counts = {"ort": 0, "zimmer": 0, "budget": 0}
    out = []
    seen = set()
    for item in items:
        if item.get("town") and canonical_town(item["town"]).casefold() not in allowed: counts["ort"] += 1; continue
        if item.get("rooms") is not None and not min_rooms <= item["rooms"] <= max_rooms: counts["zimmer"] += 1; continue
        reason, _, _ = budget(item.get("detail"), item.get("visible_price"), maximum)
        if reason: counts["budget"] += 1; continue
        # Search engines may return the same flat via several listing IDs.
        address = item.get("address")
        if address:
            address_key = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", address)
                                 .encode("ascii", "ignore").decode("ascii").casefold())
            key = (item.get("postcode"), address_key, item.get("rooms"), item.get("visible_price"))
            if key in seen: continue
            seen.add(key)
        out.append(item)
    return out, counts

def parse_detail_text(text, item):
    """Extract only explicit statements from a confirmed individual apartment page."""
    normalize = lambda value: re.sub(
        r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(value))
        .encode("ascii", "ignore").decode("ascii").casefold())
    if item.get("address") and normalize(item["address"]) not in normalize(text): return None
    if item.get("postcode") and item["postcode"] not in text: return None
    if item.get("town") and canonical_town(item["town"]).casefold() not in text.casefold(): return None
    amount = r"([1-9]\d{0,2}(?:['’ ]\d{3})*|[1-9]\d{3,4})(?:[.,]\d{2})?"
    def money(label):
        m = re.search(label + r"\s*:?\s*(?:CHF\s*)?" + amount, text, re.I)
        return number(m.group(1)) if m else None
    net = money(r"(?:Mietpreis\s*exkl\.?\s*(?:NK|Nebenkosten)|Nettomiete(?:\s*\([^)]*\))?|Netto-Miete)")
    charges = money(r"(?:Nebenkosten|Additional expenses)")
    if charges is None:
        without_exkl = re.sub(r"Mietpreis\s*exkl\.?\s*NK", "", text, flags=re.I)
        m = re.search(r"\bNK\b\s*:?\s*(?:CHF\s*)?" + amount, without_exkl, re.I)
        charges = number(m.group(1)) if m else None
    gross = money(r"(?:Bruttomiete(?:\s*\([^)]*\))?|Brutto-Miete|Gesamtmiete|Mietpreis(?!\s*exkl)|\bMiete\b)")
    if net is not None and charges is not None:
        computed = net + charges
        gross = computed if gross is None or abs(gross - computed) <= 1 else None
    floor = re.search(r"\b(?:im\s+)?(\d+)\.\s*(?:Stock|Obergeschoss|OG|Etage)\b", text, re.I)
    patterns = {
        "Balkon / Terrasse": r"\b(?:Balkon|Terrasse)\b",
        "Parkplatz vorhanden": r"\b(?:Parkplatz|Einstellplatz|Garage)\b",
        "Moderner Ausbau": r"\b(?:modern\w*|renoviert\w*|saniert\w*|Neubau)\b",
        "Ruhige Lage": r"\b(?:ruhige Lage|ruhig gelegen|verkehrsarm)\b",
        "Begehbare Dusche": r"\b(?:begehbare|ebenerdige|bodenebene|walk.in)\s+Dusche\b",
        "Gute ÖV-Anbindung": r"\b(?:Tramhaltestelle|Bushaltestelle|Bahnhof|ÖV|öffentliche Verkehr)\b",
        "Lift": r"\b(?:Lift|Aufzug)\b",
    }
    features = {name: (True if re.search(pattern, text, re.I) else None)
                for name, pattern in patterns.items()}
    for label, negative in {
        "Lift": r"\b(?:kein|ohne)\s+(?:Lift|Aufzug)\b",
        "Parkplatz vorhanden": r"\b(?:kein|ohne)\s+(?:Parkplatz|Einstellplatz|Garage)\b",
        "Balkon / Terrasse": r"\b(?:kein|ohne)\s+(?:Balkon|Terrasse)\b",
    }.items():
        if re.search(negative, text, re.I): features[label] = False
    has_bath = bool(re.search(r"\bBadewanne\b", text, re.I))
    no_bath = bool(re.search(r"\b(?:keine|ohne)\s+Badewanne\b", text, re.I))
    features["Keine Badewanne"] = True if no_bath else False if has_bath else None
    floor_value = int(floor.group(1)) if floor else (0 if re.search(
        r"\b(?:Erdgeschoss|Parterre|im EG)\b", text, re.I) else None)
    features["Nicht Erdgeschoss"] = floor_value > 0 if floor_value is not None else None
    parking_cost = money(r"(?:Parkplatz|Einstellplatz|Einstellhallenplatz|Garagenplatz)\s*"
                         r"(?::\s*Optional)?\s*(?:/Monat|pro Monat|monatlich)?\s*(?:für|zu|ab)?")
    if parking_cost is not None and not 20 <= parking_cost <= 1000:
        parking_cost = None
    return {"status": "Detailseite geprüft", "net": net, "charges": charges,
            "gross": gross, "parking_cost": parking_cost,
            "floor": floor_value, "features": features}


st.set_page_config(page_title="Wohnungs-Finder Schweiz", page_icon="🏠", layout="wide")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Outfit:wght@500;600;700&display=swap');
:root { --ink:#18384a; --teal:#087f79; --mint:#e9f7f2; --line:#d9e8e5; }
.stApp { background:linear-gradient(180deg,#eaf5f2 0,#f6faf9 350px,#f8faf9 100%); color:var(--ink); font-family:'DM Sans',sans-serif; }
.block-container { max-width:1120px; padding-top:2rem; padding-bottom:4rem; }
h1,h2,h3 { font-family:'Outfit',sans-serif !important; color:var(--ink) !important; letter-spacing:-.025em; }
.hero { background:linear-gradient(115deg,#075c62,#087f79 64%,#189c81); color:white; border-radius:25px; padding:34px 42px; box-shadow:0 16px 42px rgba(4,91,89,.15); margin-bottom:26px; }
.hero .eyebrow { font-size:.76rem; letter-spacing:.16em; font-weight:700; text-transform:uppercase; color:#c8f6e7; margin-bottom:12px; }
.hero h1 { color:white !important; font-size:clamp(2rem,4vw,3.15rem); line-height:1.12; margin:0 0 12px; }
.hero p { margin:0; color:#e1f5ee; font-size:1.04rem; }
div[data-testid='stVerticalBlockBorderWrapper'] { border-color:var(--line) !important; border-radius:20px !important; background:white; box-shadow:0 8px 28px rgba(20,67,66,.055); }
div[data-testid='stButton'] button[kind='primary'] { background:#087f79; border-color:#087f79; border-radius:11px; font-weight:700; min-height:45px; }
div[data-testid='stButton'] button[kind='secondary'], div[data-testid='stLinkButton'] a { border-radius:10px; border-color:#cbded9; color:#145450; font-weight:600; }
.section-title { font:700 1.65rem 'Outfit',sans-serif; color:#18384a; margin:29px 0 5px; }
.section-note { color:#637b80; margin-bottom:16px; }
.listing-head { display:grid; grid-template-columns:minmax(230px,2.5fr) minmax(90px,.65fr) minmax(115px,.8fr) minmax(140px,1fr); align-items:center; gap:12px; margin:0 0 10px; }
.listing-name { font:700 1.15rem 'Outfit',sans-serif; color:#18384a; line-height:1.3; }
.listing-place { color:#607b7d; font-size:.83rem; margin-top:2px; }
.listing-price { color:#086b65; font-weight:700; white-space:nowrap; }
.listing-meta { color:#607b7d; font-size:.82rem; }
.listing-status { font-size:.82rem; color:#607b7d; }
.listing-status.checked { color:#146746; }
.listing-status.expired { color:#a54c2c; }
@media(max-width:650px) { .hero{padding:26px 23px} .block-container{padding-left:1rem;padding-right:1rem} .listing-head{grid-template-columns:1fr 1fr;gap:7px} .listing-name{grid-column:1 / -1} }
</style>""", unsafe_allow_html=True)
st.markdown("""<div class="hero"><div class="eyebrow">Dein Wohnungsagent · Region Basel</div>
<h1>Finde ein Zuhause,<br>das zu dir passt.</h1>
<p>Wohnungen entdecken, Details prüfen und Favoriten sammeln.</p></div>""", unsafe_allow_html=True)

TAX = {"Aesch": 56.0, "Allschwil": 58.0, "Arlesheim": 47.0, "Binningen": 49.0,
       "Frenkendorf": 57.0, "Liestal": 65.0, "Münchenstein": 60.0, "Muttenz": 56.0,
       "Pratteln": 58.5, "Reinach": 58.5}
KEY = "wohnungs_finder_merkliste_v1"
DEFAULT = ["Reinach BL", "Münchenstein", "Aesch BL", "Muttenz", "Liestal", "Frenkendorf"]
storage = LocalStorage()

def queries(town):
    name = canonical_town(town)
    postal = POSTCODES.get(name, "")
    place = f"{postal} {name}" if postal else name
    return [f'"{place}" Wohnung mieten site:flatfox.ch/de/wohnung/',
            f'"{place}" Wohnung mieten site:homegate.ch/mieten/',
            f'"{place}" "2.5 Zimmer" Wohnung site:homegate.ch/mieten/',
            f'"{place}" Wohnung mieten site:immoscout24.ch/de/d/',
            f'"{place}" Wohnung mieten site:newhome.ch/']

@st.cache_data(ttl=1200, show_spinner=False)
def tavily(query, api_key):
    response = requests.post("https://api.tavily.com/search", json={
        "api_key": api_key, "query": query, "search_depth": "basic", "max_results": 20,
        "include_answer": False, "include_raw_content": False}, timeout=25)
    response.raise_for_status()
    return response.json().get("results", [])

def search(towns, api_key):
    tasks = [q for town in towns for q in queries(town)]
    all_raw = []
    errors = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(tavily, q, api_key) for q in tasks]
        for future in as_completed(futures):
            try: all_raw.extend(future.result())
            except requests.RequestException: errors += 1
    if errors == len(tasks): raise RuntimeError("Alle Suchabfragen sind fehlgeschlagen.")
    unique = {r.get("url"): r for r in all_raw if r.get("url")}
    parsed = [x for raw in unique.values() if (x := parse_result(raw))]
    return len(all_raw), len(unique), len(parsed), errors, parsed

class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"): self.hidden += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header"): self.hidden = max(0, self.hidden - 1)
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)

def page_text(url, timeout=15):
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    parser = VisibleText(); parser.feed(response.text)
    return re.sub(r"\s+", " ", " ".join(parser.parts))[:16000]

def quick_price(item):
    """Check one exact listing for rent without slowing search with Extract calls."""
    try:
        text = page_text(item["url"], timeout=5)
        if re.search(r"Dieses Objekt ist leider gerade nicht verfügbar|"
                     r"Inserat ist nicht mehr verfügbar|Objekt wurde deaktiviert", text, re.I):
            return item["url"], None
        detail = parse_detail_text(text, item)
        if detail and (detail.get("gross") is not None or
                       detail.get("net") is not None and detail.get("charges") is not None):
            detail["status"] = "Detailseite geprüft (Originalseite)"
            return item["url"], detail
    except (requests.RequestException, ValueError):
        pass
    return item["url"], None

def quick_prices(items):
    missing = [item for item in items if item.get("visible_price") is None]
    checked = {}
    if not missing:
        return checked
    with ThreadPoolExecutor(max_workers=10) as pool:
        for future in as_completed([pool.submit(quick_price, item) for item in missing]):
            url, detail = future.result()
            if detail:
                checked[url] = detail
    return checked

@st.cache_data(ttl=1200, show_spinner=False)
def tavily_extract(url, api_key):
    response = requests.post("https://api.tavily.com/extract", json={
        "api_key": api_key, "urls": [url], "extract_depth": "advanced",
        "include_images": False}, timeout=30)
    response.raise_for_status()
    results = response.json().get("results", [])
    return str(results[0].get("raw_content") or "") if results else ""

def detail_for(item):
    texts = []
    try:
        direct_text = page_text(item["url"])
        if re.search(r"Dieses Objekt ist leider gerade nicht verfügbar|"
                     r"Inserat ist nicht mehr verfügbar|Objekt wurde deaktiviert",
                     direct_text, re.I):
            return {"status": "Inserat nicht mehr verfügbar", "unavailable": True}
        texts.append(("Originalseite", direct_text))
        direct_detail = parse_detail_text(direct_text, item)
        if direct_detail and direct_detail.get("net") is not None and direct_detail.get("charges") is not None:
            direct_detail["status"] = "Detailseite geprüft (Originalseite)"
            return direct_detail
    except requests.RequestException: pass
    key = st.secrets.get("TAVILY_API_KEY")
    if key:
        try: texts.append(("Tavily Extract", tavily_extract(item["url"], key)))
        except requests.RequestException: pass
    for source, text in texts:
        detail = parse_detail_text(text, item)
        if detail and any(detail.get(k) is not None for k in
                          ("net", "charges", "gross", "parking_cost", "floor")):
            detail["status"] = f"Detailseite geprüft ({source})"
            return detail
    for source, text in texts:
        detail = parse_detail_text(text, item)
        if detail and any(value is not None for value in detail["features"].values()):
            detail["status"] = f"Merkmale geprüft ({source}); Kostenangaben offen"
            return detail
    return {"status": "Inserattext enthält keine prüfbaren Details; Angaben offen"}

def load_saved():
    try:
        raw = storage.getItem(KEY)
        for _ in range(2):
            if isinstance(raw, str): raw = json.loads(raw)
        return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []
    except Exception: return []

def save_saved():
    storage.setItem(KEY, json.dumps(st.session_state.saved, ensure_ascii=False))

if "saved" not in st.session_state: st.session_state.saved = load_saved()
if "results" not in st.session_state: st.session_state.results = []
if "details" not in st.session_state: st.session_state.details = {}

st.markdown('<div class="section-title">🔎 Deine Suche</div><div class="section-note">Wähle Ort, Budget und Zimmerzahl.</div>', unsafe_allow_html=True)
towns = st.multiselect("Gemeinden", list(POSTCODES),
                       default=[canonical_town(x) for x in DEFAULT])
extra = st.text_input("Weitere Orte (kommagetrennt)",
                      placeholder="z. B. Oberwil BL, Therwil")
towns = list(dict.fromkeys(towns + [x.strip() for x in extra.split(",") if x.strip()]))
c1, c2, c3 = st.columns(3)
maximum = c1.number_input("Max. Gesamtpreis inkl. NK und Parkplatz (CHF)",
                          500, 10000, 1800, 50)
min_rooms = c2.selectbox("Mindestens Zimmer", [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0], index=3)
max_rooms = c3.selectbox("Maximal Zimmer", [2.5, 3.0, 3.5, 4.0, 4.5, 5.0], index=2)

WISHES = ["Nicht Erdgeschoss", "Balkon / Terrasse", "Lift", "Parkplatz vorhanden",
          "Moderner Ausbau", "Ruhige Lage", "Begehbare Dusche", "Keine Badewanne",
          "Gute ÖV-Anbindung"]
with st.expander("Wunschkriterien", expanded=False):
    cols = st.columns(3)
    wanted = {name: cols[i % 3].checkbox(name, value=True, key="wish_" + name)
              for i, name in enumerate(WISHES)}
    want_tax = st.checkbox("Niedrigen Steuerfuss bevorzugen", value=True)
st.caption("Wünsche bewerten geprüfte Inserate. Unbekannte Angaben schließen keine Wohnung aus.")

if st.button("🔎 Wohnungen suchen", type="primary", use_container_width=True):
    if min_rooms > max_rooms:
        st.error("Die Mindestzimmerzahl ist höher als die Höchstzimmerzahl.")
    elif not towns:
        st.error("Bitte mindestens eine Gemeinde wählen.")
    elif not st.secrets.get("TAVILY_API_KEY"):
        st.error("TAVILY_API_KEY fehlt in den Streamlit Secrets.")
    else:
        start = time.monotonic()
        with st.spinner("Inserate und fehlende Mietpreise werden geprüft ..."):
            try:
                raw_count, unique_count, parsed_count, errors, parsed = search(
                    towns, st.secrets["TAVILY_API_KEY"])
                results, excluded = filter_listings(parsed, towns, min_rooms,
                                                    max_rooms, maximum)
                checked = quick_prices(results)
                for item in results:
                    if item["url"] in checked:
                        item["detail"] = checked[item["url"]]
                results, rechecked = filter_listings(results, towns, min_rooms,
                                                     max_rooms, maximum)
                for reason in excluded:
                    excluded[reason] += rechecked[reason]
                st.session_state.results = results
                st.session_state.details = {item["url"]: checked[item["url"]]
                                            for item in results if item["url"] in checked}
                st.session_state.diagnostic = {
                    "seconds": round(time.monotonic() - start, 1),
                    "sources": raw_count, "unique": unique_count,
                    "direct": parsed_count, "excluded": excluded,
                    "shown": len(results), "errors": errors,
                    "prices_checked": len(checked),
                }
            except Exception as exc:
                st.error(f"Suche fehlgeschlagen: {exc}")

diag = st.session_state.get("diagnostic")
if st.session_state.results:
    st.session_state.results, _ = filter_listings(
        st.session_state.results, towns, min_rooms, max_rooms, maximum)
if diag:
    e = diag["excluded"]
    st.info(f"Suche {diag['seconds']:.1f} s · {diag['sources']} Webtreffer · "
            f"{diag['unique']} URLs · {diag['direct']} direkte Inserat-URLs · "
            f"{len(st.session_state.results)} angezeigt · Ausschlüsse Ort/Zimmer/Budget: "
            f"{e['ort']}/{e['zimmer']}/{e['budget']} · "
            f"fehlgeschlagene Suchabfragen: {diag['errors']}")

st.markdown('<div class="section-title">🏡 Gefundene Wohnungen</div><div class="section-note">Öffne die Details für verlässliche Kosten und Wohnungsmerkmale.</div>', unsafe_allow_html=True)
if not st.session_state.results:
    st.caption("Noch keine Wohnungen gefunden. Die Suche zeigt nur URLs konkreter Inserate.")

for index, item in enumerate(list(st.session_state.results)):
    url = item["url"]
    detail = st.session_state.details.get(url)
    name = item.get("address") or item.get("title") or "Adresse noch offen"
    place = " ".join(x for x in (item.get("postcode"), item.get("town")) if x)
    rooms = f"{item['rooms']:g} Zimmer" if item.get("rooms") is not None else "Zimmer offen"
    display_price = detail.get("gross") if detail and detail.get("gross") is not None else item.get("visible_price")
    visible = (f"CHF {display_price:,.0f}" if display_price is not None
               else "Miete offen")
    with st.container(border=True):
        status = detail.get("status", "") if detail else ""
        badge_class = "expired" if detail and detail.get("unavailable") else "checked" if "geprüft" in status else ""
        badge = "Nicht mehr verfügbar" if badge_class == "expired" else "Details geprüft" if badge_class == "checked" else "Details noch offen"
        safe = lambda value: html.escape(str(value))
        st.markdown(f'''<div class="listing-head"><div><div class="listing-name">🏠 {safe(name)}</div>
<div class="listing-place">📍 {safe(place)}</div></div><div class="listing-meta">🛏️ {safe(rooms)}</div>
<div class="listing-price">{safe(visible)}</div><div class="listing-status {badge_class}">{safe(badge)}<br>🌐 {safe(item['source'])}</div></div>''', unsafe_allow_html=True)
        actions = st.columns(3)
        if actions[0].button("🔍 Details prüfen", key="detail_" + url):
            with st.spinner("Originalinserat wird geprüft ..."):
                checked = detail_for(item)
            if "features" in checked:
                reason, _, _ = budget(checked, None, maximum)
                if reason:
                    st.session_state.results = [x for x in st.session_state.results
                                                if x["url"] != url]
                    st.session_state.details.pop(url, None)
                    st.warning("Sicher bekannte Kosten über dem Budget: Treffer entfernt.")
                    st.rerun()
            st.session_state.details[url] = checked
            st.rerun()
        if actions[1].button("☆ Merken", key="save_" + url):
            if not any(x.get("url") == url for x in st.session_state.saved):
                st.session_state.saved.append(item)
                save_saved()
            st.toast("In der Merkliste gespeichert")
        actions[2].link_button("🏠 Originalinserat öffnen", url)

        if detail:
            if detail.get("unavailable"):
                st.warning("Dieses Inserat ist laut Originalseite nicht mehr verfügbar.")
            else:
                st.write("**" + detail["status"] + "**")
            if "features" in detail:
                net, charges, gross, parking = (detail.get(k) for k in
                                                 ("net", "charges", "gross", "parking_cost"))
                def money(value):
                    return f"CHF {value:,.0f}" if value is not None else "❓ offen"
                if gross is None and net is not None and charges is not None:
                    gross = net + charges
                total = gross + parking if gross is not None and parking is not None else None
                st.markdown("**💰 Kosten pro Monat**")
                a, b, c, d = st.columns(4)
                a.metric("Nettomiete", money(net))
                b.metric("Nebenkosten", money(charges))
                c.metric("Miete inkl. NK", money(gross))
                d.metric("Parkplatz", money(parking))
                st.write("**Gesamt inkl. Parkplatz:** " + money(total))
                st.markdown("**Wohnungsmerkmale**")
                floor = detail.get("floor")
                st.write("Etage: " + ("Parterre / EG" if floor == 0 else
                         f"{floor}. Stock" if floor is not None else "❓ offen"))
                features = detail["features"]
                matched = sum(bool(features.get(k)) for k in WISHES if wanted[k])
                known = sum(features.get(k) is not None for k in WISHES if wanted[k])
                st.caption(f"Bestätigte Wünsche: {matched} von {known} prüfbaren")
                for label in WISHES:
                    value = features.get(label)
                    symbol = "✅" if value is True else "❌" if value is False else "❓"
                    st.write(f"{symbol} {label}")
                if want_tax and item.get("town") in TAX:
                    st.caption(f"Steuerfuss {item['town']}: {TAX[item['town']]:g} %")

st.markdown('<div class="section-title">♡ Deine Merkliste</div><div class="section-note">Gespeicherte Inserate bleiben in diesem Browser erhalten.</div>', unsafe_allow_html=True)
for i, item in enumerate(list(st.session_state.saved)):
    address = item.get("address") or item.get("strasse") or item.get("title") or "Wohnung"
    town = item.get("town") or item.get("ort") or ""
    left, middle, right = st.columns([4, 2, 1])
    left.write(f"{address} · {town}")
    if item.get("url"):
        middle.link_button("Inserat öffnen", item["url"], key=f"saved_link_{i}")
    if right.button("Entfernen", key=f"remove_{i}"):
        st.session_state.saved.pop(i)
        save_saved()
        st.rerun()

st.caption("Wohnungs-Finder Schweiz V12.9 · Angaben und Verfügbarkeit im Originalinserat prüfen.")
