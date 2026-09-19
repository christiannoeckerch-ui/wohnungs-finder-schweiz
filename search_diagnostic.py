"""Transparent Tavily search and extraction diagnostic for Swiss rentals.

Run with: streamlit run search_diagnostic.py
"""

from __future__ import annotations

import os
import re
from html import unescape
from collections import defaultdict
from urllib.parse import urljoin, urlsplit

import requests
import streamlit as st
from bs4 import BeautifulSoup


SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
PORTALS = ("homegate.ch", "immoscout24.ch", "newhome.ch", "flatfox.ch")
SWISS_SITES = PORTALS + ("comparis.ch", "home.ch", "homematch.ch", "realadvisor.ch", "alle-immobilien.ch", "immostreet.ch")
FIELDS = ("Strasse + Hausnummer", "PLZ / Gemeinde", "Zimmer", "sichtbare Miete", "Nettomiete", "Nebenkosten", "Bruttomiete")
FLATFOX_REINACH_SEARCH = "https://flatfox.ch/de/search/?query=Reinach%20BL"


def probe_flatfox() -> dict:
    """One no-cost check of whether server-side HTTP exposes direct listing cards."""
    try:
        response = requests.get(FLATFOX_REINACH_SEARCH, timeout=20,
                                headers={"User-Agent": "Mozilla/5.0 (compatible; Wohnungs-Suchtest/1.0)",
                                         "Accept": "text/html"})
        soup = BeautifulSoup(response.text, "html.parser")
        urls = list(dict.fromkeys(a.get("href", "") for a in soup.select('a[href*="/de/wohnung/"]')))
        return {"HTTP-Status": response.status_code, "HTML-Zeichen": len(response.text),
                "Direktlinks im Server-HTML": len(urls), "Beispiel-URLs": urls[:5],
                "Hinweis": "Im Server-HTML gefunden" if urls else "Keine Inserat-Links im Server-HTML; möglicherweise werden sie erst im Browser geladen."}
    except requests.RequestException as exc:
        return {"Fehler": str(exc)}


def domain(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.") or "unbekannt"


def classify(url: str, title: str = "", snippet: str = "") -> tuple[str, str]:
    """Conservative URL-first heuristic; content is only supporting evidence."""
    path = urlsplit(url).path.lower().rstrip("/")
    query = urlsplit(url).query.lower()
    if "/anbieterverzeichnis/" in path or "/anbieterprofil/" in path:
        return "wahrscheinlich Übersichtsseite", "Anbieterprofil mit mehreren Angeboten, kein einzelnes Wohnungsinserat"
    overview_query = re.search(r"(?:^|&)(?:location|rooms|price|maxrent|sort|page|pagenum)=", query)
    overview_path = re.search(r"(?:/search|/suche|/suchen|/results?|/angebote)(?:/|$)|/(?:city|plz|ort|region)-[^/]+$|/in-[^/]+$", path)
    overview_title = re.search(r"\b\d+\s+(?:wohnung(?:en)?|apartments?|flats?|immobilien|treffer|angebote)\b|\b(?:seite|page)\s*\d+\b", title, re.I)
    if overview_query or overview_path or overview_title or path in ("", "/"):
        return "wahrscheinlich Übersichtsseite", "Such-/Orts-URL oder Titel nennt eine Trefferliste"
    identifier = re.search(r"/(?:[1-9]\d{6,})(?:$|[/?])|(?:listing|object|property|id)=[1-9]\d{5,}", path + "?" + query)
    if identifier:
        return "wahrscheinlich Einzelinserat", "URL enthält eine konkrete Objekt-ID"
    if re.search(r"\b(?:wohnung|zimmer|chf|miete)\b", title + " " + snippet, re.I):
        return "unklar", "Wohnungsbezug im Text, aber kein eindeutiger Objektpfad"
    return "unklar", "URL und Suchtext erlauben keine sichere Zuordnung"


def _money(value: str) -> str:
    return re.sub(r"[^\d]", "", re.split(r"[.,](?=\d{2}(?:\D|$))", value)[0])


def parse_fields(raw: str) -> dict[str, str]:
    """Extract visible evidence only; do not infer missing rent components."""
    text = re.sub(r"\s+", " ", raw)
    result = {key: "nicht erkannt" for key in FIELDS}
    street = re.search(r"\b([A-ZÄÖÜ][\wäöüÄÖÜéèàâêîôûÉÈÀÂÊÎÔÛ.' -]{2,55}?(?:strasse|straße|str\.?|weg|gasse|platz|allee|rain|ring|hof)\s*\d+[a-zA-Z]?)\b", text, re.I)
    if street:
        result["Strasse + Hausnummer"] = street.group(1).strip()
    place = re.search(r"\b([1-9]\d{3})\s+([A-ZÄÖÜ][a-zäöüéèàâêîôû-]+(?:\s+(?:BL|AG|BS|SO|ZH|BE|LU|SZ|ZG|SG|GR|TI|VD|GE|FR|NE|JU|TG|SH|AR|AI|GL|NW|OW|UR|VS))?)\b", text)
    if place:
        result["PLZ / Gemeinde"] = f"{place.group(1)} {place.group(2).strip()}"
    rooms = re.search(r"\b(\d(?:[.,]5|\s*½|\s+1/2)?)\s*(?:zimmer|zi\.?|rooms?)\b|\b(?:zimmer|zi\.?)\s*[:\-]?\s*(\d(?:[.,]5|\s*½|\s+1/2)?)\b", text, re.I)
    if rooms:
        value = (rooms.group(1) or rooms.group(2)).strip()
        result["Zimmer"] = re.sub(r"\s*(?:½|1/2)$", ".5", value).replace(",", ".")
    amount = r"(?:CHF\s*)?([1-9]\d{0,2}(?:['’ ]\d{3})+|[1-9]\d{2,4})(?:[.,]\d{2})?"
    labels = {
        "Nettomiete": r"(?:nettomiete|netto\s*miete)",
        "Nebenkosten": r"(?:nebenkosten|nk)",
        "Bruttomiete": r"(?:bruttomiete|brutto\s*miete|miete\s*inkl\.?\s*nebenkosten)",
    }
    for field, label in labels.items():
        match = re.search(rf"\b{label}\b\s*[:\-]?\s*{amount}", text, re.I)
        if match and 100 <= int(_money(match.group(1)) or 0) <= 100000:
            result[field] = f"CHF {_money(match.group(1))}"
    visible = re.search(rf"\b(?:miete|mietpreis|preis|CHF|Fr\.?)\b\s*[:\-]?\s*{amount}", text, re.I)
    if visible and 100 <= int(_money(visible.group(1)) or 0) <= 100000:
        result["sichtbare Miete"] = f"CHF {_money(visible.group(1))}"
    elif result["Bruttomiete"] != "nicht erkannt":
        result["sichtbare Miete"] = result["Bruttomiete"]
    elif result["Nettomiete"] != "nicht erkannt":
        result["sichtbare Miete"] = result["Nettomiete"]
    return result


def queries(gemeinde: str, minimum: float, maximum: float, price: int) -> list[tuple[str, list[str]]]:
    criteria = f'"{gemeinde}" Mietwohnung {minimum:g} {maximum:g} Zimmer bis {price} Franken'
    return [
        (f"{criteria} Inserat Adresse", list(SWISS_SITES)),
        (f'"{gemeinde}" Wohnung mieten {minimum:g} bis {maximum:g} Zimmer bis {price} Franken', list(SWISS_SITES)),
        *[(f"{criteria} Wohnung mieten", [portal]) for portal in PORTALS],
    ]


def post_tavily(endpoint: str, payload: dict, api_key: str) -> dict:
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Tavily lieferte keine JSON-Objektantwort")
    return data


def run_search(api_key: str, search_queries: list[tuple[str, list[str]]]) -> tuple[list[dict], list[dict], int]:
    results, calls, seen = [], [], set()
    for query, domains in search_queries:
        try:
            data = post_tavily(SEARCH_URL, {
                "query": query, "search_depth": "basic", "topic": "general",
                "max_results": 10, "include_answer": False, "include_raw_content": False,
                "include_usage": True, "include_domains": domains,
                "include_domains_mode": "restrict", "country": "switzerland",
                "exact_match": True,
            }, api_key)
            found = data.get("results") or []
            calls.append({"query": query, "Domains": ", ".join(domains), "returned": len(found), "usage": data.get("usage"), "error": ""})
            for hit in found:
                url = hit.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)  # Only identical URLs are deduplicated.
                category, reason = classify(url, hit.get("title", ""), hit.get("content", ""))
                results.append({"url": url, "domain": domain(url), "title": hit.get("title", ""),
                                "snippet": hit.get("content", ""), "category": category,
                                "reason": reason, "query": query, "extract": "nicht versucht",
                                "raw": "", "fields": None})
        except (requests.RequestException, ValueError) as exc:
            calls.append({"query": query, "Domains": ", ".join(domains), "returned": 0, "usage": None, "error": str(exc)})
    return results, calls, sum(call["returned"] for call in calls)


def run_extract(api_key: str, results: list[dict], max_urls: int, advanced_limit: int, gemeinde: str) -> list[dict]:
    candidates = [row for row in results if row["category"] != "wahrscheinlich Übersichtsseite"]
    locality = gemeinde.casefold().replace(" ", "-")
    def priority(row: dict) -> tuple[int, int]:
        text = (row["url"] + " " + row["title"]).casefold()
        local = gemeinde.casefold() in text or locality in text
        if gemeinde == "Reinach BL":
            local = local or "4153" in text
        direct = row["category"] == "wahrscheinlich Einzelinserat"
        relevant_domain = any(row["domain"] == site or row["domain"].endswith("." + site) for site in SWISS_SITES)
        return (0 if relevant_domain else 1, 0 if direct and local else 1 if direct else 2 if local else 3)
    candidates.sort(key=priority)
    selected = candidates[:max_urls]
    for row in candidates[max_urls:]:
        row["extract"] = "nicht versucht: URL-Limit erreicht"
    calls = []

    def batch(rows: list[dict], depth: str) -> None:
        for start in range(0, len(rows), 20):
            chunk = rows[start:start + 20]
            urls = [row["url"] for row in chunk]
            try:
                data = post_tavily(EXTRACT_URL, {"urls": urls, "extract_depth": depth,
                    "format": "markdown", "include_usage": True}, api_key)
                by_url = {item.get("url"): item for item in data.get("results", [])}
                failed = {item.get("url"): item.get("error", "unbekannter Fehler")
                          for item in data.get("failed_results", [])}
                calls.append({"depth": depth, "urls": len(urls), "usage": data.get("usage"), "error": ""})
                for row in chunk:
                    item = by_url.get(row["url"])
                    raw = (item or {}).get("raw_content") or ""
                    if raw.strip():
                        row["extract"] = f"erfolgreich ({depth})"
                        row["raw"] = raw
                        row["fields"] = parse_fields(raw)
                    elif row["url"] in failed:
                        row["extract"] = f"Fehler ({depth}): {failed[row['url']]}"
                    else:
                        row["extract"] = f"leer/blockiert ({depth}); keine Rohdaten erhalten"
            except (requests.RequestException, ValueError) as exc:
                calls.append({"depth": depth, "urls": len(urls), "usage": None, "error": str(exc)})
                for row in chunk:
                    row["extract"] = f"API-Fehler ({depth}): {exc}"

    batch(selected, "basic")
    retry = [row for row in selected if not row["raw"]][:advanced_limit]
    if retry:
        batch(retry, "advanced")
    return calls


def markdown_links(raw: str, source_url: str) -> list[tuple[str, str]]:
    """Read linked URLs from Tavily markdown, including URLs with parentheses."""
    links = []
    pattern = re.compile(r"(?<!!)\[([^\]\n]{1,160})\]\(")
    for match in pattern.finditer(raw):
        start, depth = match.end(), 1
        cursor = start
        while cursor < len(raw) and depth:
            if raw[cursor] == "(":
                depth += 1
            elif raw[cursor] == ")":
                depth -= 1
            cursor += 1
        if depth:
            continue
        target = unescape(raw[start:cursor - 1].strip().split(' "', 1)[0])
        if not target or target.startswith(("#", "mailto:", "javascript:", "data:")):
            continue
        url = urljoin(source_url, target)
        if urlsplit(url).scheme in ("https", "http"):
            links.append((unescape(match.group(1)), url))
    return links


def run_overview_extract(api_key: str, results: list[dict], max_pages: int,
                         gemeinde: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Extract a few search result lists and expose their actual linked object URLs."""
    overview = [row for row in results if row["category"] == "wahrscheinlich Übersichtsseite"]
    local = gemeinde.casefold()
    slug = local.replace(" ", "-")
    overview.sort(key=lambda row: (0 if local in (row["url"] + row["title"]).casefold()
                                    or slug in row["url"].casefold() else 1,
                                    0 if row["domain"] in PORTALS else 1))
    selected = overview[:max_pages]
    calls, discovered, seen = [], [], set()
    for start in range(0, len(selected), 20):
        chunk = selected[start:start + 20]
        urls = [row["url"] for row in chunk]
        try:
            data = post_tavily(EXTRACT_URL, {"urls": urls, "extract_depth": "basic",
                "format": "markdown", "include_usage": True}, api_key)
            by_url = {item.get("url"): item for item in data.get("results", [])}
            failed = {item.get("url"): item.get("error", "unbekannter Fehler")
                      for item in data.get("failed_results", [])}
            calls.append({"stage": "Übersichtsseiten", "depth": "basic", "urls": len(urls),
                          "usage": data.get("usage"), "error": ""})
            for row in chunk:
                raw = (by_url.get(row["url"]) or {}).get("raw_content") or ""
                row["overview_raw"] = raw
                row["overview_links"] = markdown_links(raw, row["url"])
                if raw.strip():
                    row["overview_extract"] = "erfolgreich (basic)"
                elif row["url"] in failed:
                    row["overview_extract"] = f"Fehler (basic): {failed[row['url']]}"
                else:
                    row["overview_extract"] = "leer/blockiert (basic); keine Rohdaten erhalten"
                for label, url in row["overview_links"]:
                    category, reason = classify(url, label)
                    if category != "wahrscheinlich Einzelinserat" or url in seen:
                        continue
                    seen.add(url)
                    discovered.append({"url": url, "domain": domain(url), "title": label,
                                       "snippet": "", "category": category, "reason": reason,
                                       "source": row["url"], "extract": "nicht versucht",
                                       "raw": "", "fields": None})
        except (requests.RequestException, ValueError) as exc:
            calls.append({"stage": "Übersichtsseiten", "depth": "basic", "urls": len(urls),
                          "usage": None, "error": str(exc)})
            for row in chunk:
                row["overview_extract"] = f"API-Fehler (basic): {exc}"
                row["overview_raw"], row["overview_links"] = "", []
    return selected, discovered, calls


def portal_summary(results: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in results:
        groups[row["domain"]].append(row)
    output = []
    for portal, rows in sorted(groups.items()):
        individual = sum(row["category"] == "wahrscheinlich Einzelinserat" for row in rows)
        extracted = sum(row["extract"].startswith("erfolgreich") for row in rows)
        address = sum(bool(row["category"] == "wahrscheinlich Einzelinserat" and row["fields"] and row["fields"]["Strasse + Hausnummer"] != "nicht erkannt"
                           and row["fields"]["PLZ / Gemeinde"] != "nicht erkannt") for row in rows)
        rooms = sum(bool(row["category"] == "wahrscheinlich Einzelinserat" and row["fields"] and row["fields"]["Zimmer"] != "nicht erkannt") for row in rows)
        price = sum(bool(row["category"] == "wahrscheinlich Einzelinserat" and row["fields"] and row["fields"]["sichtbare Miete"] != "nicht erkannt") for row in rows)
        usable = sum(bool(row["category"] == "wahrscheinlich Einzelinserat" and row["fields"]
                          and all(row["fields"][field] != "nicht erkannt" for field in
                                  ("Strasse + Hausnummer", "PLZ / Gemeinde", "Zimmer", "sichtbare Miete"))) for row in rows)
        output.append({"Domain": portal, "Suchresultate": len(rows), "wahrscheinlich Einzelinserate": individual,
                       "Extract erfolgreich": extracted, "Adresse erkannt": address,
                       "Zimmer erkannt": rooms, "Preis erkannt": price,
                       "brauchbare Direktlinks": f"{usable / len(rows):.0%}"})
    return output


def api_key_from_environment() -> str:
    key = os.getenv("TAVILY_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("TAVILY_API_KEY", "")
        except (FileNotFoundError, KeyError):
            pass
    return key


def main() -> None:
    st.set_page_config(page_title="Wohnungs-Suchtest V1", layout="wide")
    st.title("Wohnungs-Suchtest V1")
    st.caption("Tavily Search → URL-Sichtung → Tavily Extract. Keine Ergebnisfilterung nach Adresse, Zimmer oder Preis.")
    if st.button("Flatfox-Abruf ohne Tavily prüfen"):
        st.subheader("Flatfox-Server-Test")
        st.json(probe_flatfox())
    gemeinde = st.selectbox("Gemeinde", ["Reinach BL", "Basel", "Allschwil", "Binningen", "Münchenstein", "Muttenz"], index=0)
    left, middle, right = st.columns(3)
    minimum = left.number_input("Zimmer von", min_value=1.0, max_value=10.0, value=2.5, step=0.5)
    maximum = middle.number_input("Zimmer bis", min_value=1.0, max_value=10.0, value=3.5, step=0.5)
    price = right.number_input("Max. CHF/Monat", min_value=100, max_value=20000, value=1800, step=100)
    with st.expander("API-Aufwand begrenzen", expanded=False):
        max_urls = st.slider("Maximal mit Extract zu prüfende URLs", 0, 60, 20)
        advanced_limit = st.slider("Davon bei Fehler/Leere mit advanced erneut prüfen", 0, 5, 2)
        max_overviews = st.slider("Zusätzlich zu prüfende Übersichtsseiten", 0, 10, 2)
        max_discovered = st.slider("Gefundene Direktlinks mit Extract prüfen", 0, 20, 5)
        st.caption("6 Search-Aufrufe mit je höchstens 10 Treffern. Extract in Paketen bis 20 URLs; advanced nur für ausgewählte Fehlschläge. Tatsächliche Credits stehen unten, wenn Tavily sie liefert.")
    if not st.button("Diagnose starten", type="primary"):
        return
    if minimum > maximum:
        st.error("Die Zimmer-Untergrenze muss kleiner oder gleich der Obergrenze sein.")
        return
    api_key = api_key_from_environment()
    if not api_key:
        st.error("TAVILY_API_KEY fehlt in der Umgebung oder in Streamlit Secrets.")
        return
    with st.spinner("Tavily Search und Extract laufen …"):
        results, search_calls, returned = run_search(api_key, queries(gemeinde, minimum, maximum, price))
        overviews, discovered, overview_calls = run_overview_extract(api_key, results, max_overviews, gemeinde)
        extract_calls = run_extract(api_key, results, max_urls, advanced_limit, gemeinde)
        already = {row["url"] for row in results}
        new_discovered = [row for row in discovered if row["url"] not in already]
        discovered_calls = run_extract(api_key, new_discovered, max_discovered, 0, gemeinde)
        for call in extract_calls:
            call["stage"] = "Suchresultate"
        for call in discovered_calls:
            call["stage"] = "Gefundene Direktlinks"
        all_extract_calls = overview_calls + extract_calls + discovered_calls
    st.subheader("API-Aufwand und Suchanfragen")
    st.write(f"{len(search_calls)} Search-Aufrufe · {returned} rohe Treffer · {len(results)} eindeutige exakte URLs · {len(all_extract_calls)} Extract-Aufrufe")
    st.dataframe(search_calls, use_container_width=True, hide_index=True)
    if all_extract_calls:
        st.dataframe(all_extract_calls, use_container_width=True, hide_index=True)
    reported = [call["usage"].get("credits") for call in search_calls + all_extract_calls
                if isinstance(call.get("usage"), dict) and isinstance(call["usage"].get("credits"), (int, float))]
    st.write(f"Von Tavily gemeldete Credits: {sum(reported)}" if reported else "Tavily hat keine Credit-Zahl geliefert; Aufrufzahlen stehen oben.")
    st.subheader("Portal-Zusammenfassung")
    st.caption("Brauchbare Direktlinks = Anteil aller Suchresultate mit konkreter Objekt-URL, erfolgreichem Extract sowie erkannter Adresse, Zimmerzahl und Miete. Nur Indizien, keine Bestätigung der Aktualität.")
    st.dataframe(portal_summary(results), use_container_width=True, hide_index=True)
    st.subheader("Links aus Übersichtsseiten")
    st.caption("Nur tatsächlich im Tavily-Rohtext verlinkte Objekt-URLs. Feldwerte einer Trefferliste werden keiner einzelnen Wohnung zugeordnet.")
    st.write(f"{len(overviews)} Übersichtsseiten geprüft · {len(discovered)} verschiedene direkte Objekt-URLs gefunden · {len(new_discovered)} davon zuvor nicht als Suchresultat vorhanden")
    for index, row in enumerate(overviews, 1):
        with st.expander(f"{index}. [{row['domain']}] {row['title'] or '(ohne Titel)'} — {row['overview_extract']}"):
            st.write("**Exakte Quell-URL:**", row["url"])
            st.write("**Links im Rohtext:**", len(row["overview_links"]))
            st.write("**Davon Direktlink-Kandidaten:**", sum(item["source"] == row["url"] for item in discovered))
            if row["overview_raw"]:
                st.text_area("Rohtext-Ausschnitt der Übersicht (erste 3000 Zeichen)", row["overview_raw"][:3000],
                             height=180, key=f"overview_raw_{index}")
            else:
                st.write("**Rohtext:** nicht verfügbar")
    if discovered:
        st.caption("Portal-Zahlen für gefundene Direktlinks (Nenner: verlinkte Objekt-URLs, nicht alle Suchresultate).")
        st.dataframe(portal_summary(discovered), use_container_width=True, hide_index=True)
        st.write("**Gefundene Direktlink-Kandidaten:**")
        for index, row in enumerate(discovered, 1):
            with st.expander(f"{index}. [{row['domain']}] {row['title'] or '(ohne Linktext)'} — {row['extract']}"):
                st.write("**Exakte URL:**", row["url"])
                st.write("**Gefunden auf:**", row["source"])
                st.write("**Klassifikation:**", row["category"], "—", row["reason"])
                if row["url"] in already:
                    st.write("**Extract:** bereits unter Suchresultaten geprüft oder dort nicht ausgewählt")
                else:
                    st.write("**Extract:**", row["extract"])
                if row["fields"]:
                    for field, value in row["fields"].items():
                        st.write(f"**{field}:** {value}")
                    st.text_area("Rohtext-Ausschnitt (erste 3000 Zeichen)", row["raw"][:3000],
                                 height=180, key=f"discovered_raw_{index}")
                elif row["extract"].startswith(("Fehler", "leer", "API-Fehler")):
                    st.write("**Rohtext:** nicht verfügbar")
    st.subheader("Alle Suchresultate")
    if not results:
        st.warning("Keine Resultate. Fehler der einzelnen Suchanfragen stehen oben.")
    for index, row in enumerate(results, 1):
        with st.expander(f"{index}. [{row['domain']}] {row['title'] or '(ohne Titel)'} — {row['category']}"):
            st.write("**Exakte URL:**", row["url"])
            st.write("**Suchanfrage:**", row["query"])
            st.write("**Snippet:**", row["snippet"] or "(leer)")
            st.write("**Klassifikation:**", row["category"], "—", row["reason"])
            st.write("**Extract:**", row["extract"])
            if row["fields"]:
                st.caption("Feldwerte sind Texttreffer auf dieser Seite. Bei Übersichtsseiten können sie zu verschiedenen Wohnungen gehören.")
                for field, value in row["fields"].items():
                    st.write(f"**{field}:** {value}")
                st.text_area("Rohtext-Ausschnitt (erste 3000 Zeichen)", row["raw"][:3000], height=180, key=f"raw_{index}")
            elif row["extract"].startswith(("Fehler", "leer", "API-Fehler")):
                st.write("**Rohtext:** nicht verfügbar")


if __name__ == "__main__":
    main()
