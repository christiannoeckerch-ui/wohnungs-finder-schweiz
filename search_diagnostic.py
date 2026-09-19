"""Transparent Tavily search and extraction diagnostic for Swiss rentals.

Run with: streamlit run search_diagnostic.py
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from urllib.parse import urlsplit

import requests
import streamlit as st


SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
PORTALS = ("homegate.ch", "immoscout24.ch", "newhome.ch", "flatfox.ch")
FIELDS = ("Strasse + Hausnummer", "PLZ / Gemeinde", "Zimmer", "sichtbare Miete", "Nettomiete", "Nebenkosten", "Bruttomiete")


def domain(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.") or "unbekannt"


def classify(url: str, title: str = "", snippet: str = "") -> tuple[str, str]:
    """Conservative URL-first heuristic; content is only supporting evidence."""
    path = urlsplit(url).path.lower().rstrip("/")
    query = urlsplit(url).query.lower()
    listing = re.search(r"/(?:rent|mieten|wohnung-mieten|immobilien|objekt|property|listing|expose|angebot)/[^/]+", path)
    identifier = re.search(r"(?:/|[-_])\d{5,}(?:$|[/?-])|(?:listing|object|property|id)=\d+", path + "?" + query)
    overview = re.search(r"/(?:search|suche|suchen|result|results|angebote|mieten|rent)(?:/)?$", path)
    overview_query = re.search(r"(?:location|rooms|price|maxrent|sort|page)=", query)
    if identifier or (listing and path.count("/") >= 2):
        return "wahrscheinlich Einzelinserat", "URL enthält einen Objektpfad oder eine Objekt-ID"
    if overview or overview_query or path in ("", "/"):
        return "wahrscheinlich Übersichtsseite", "URL wirkt wie Suche, Ergebnisliste oder Portalstartseite"
    if re.search(r"\b(?:wohnung|zimmer|chf|miete)\b", title + " " + snippet, re.I):
        return "unklar", "Wohnungsbezug im Text, aber kein eindeutiger Objektpfad"
    return "unklar", "URL und Suchtext erlauben keine sichere Zuordnung"


def _money(value: str) -> str:
    return re.sub(r"[^\d]", "", value)


def parse_fields(raw: str) -> dict[str, str]:
    """Extract visible evidence only; do not infer missing rent components."""
    text = re.sub(r"\s+", " ", raw)
    result = {key: "nicht erkannt" for key in FIELDS}
    street = re.search(r"\b([A-ZÄÖÜ][\wäöüÄÖÜéèàâêîôûÉÈÀÂÊÎÔÛ.' -]{2,55}?(?:strasse|straße|str\.?|weg|gasse|platz|allee|rain|ring|hof)\s*\d+[a-zA-Z]?)\b", text, re.I)
    if street:
        result["Strasse + Hausnummer"] = street.group(1).strip()
    place = re.search(r"\b([1-9]\d{3})\s+([A-ZÄÖÜ][a-zäöüéèàâêîôû-]+(?:\s+[A-ZÄÖÜ][a-zäöüéèàâêîôû-]+){0,2})\b", text)
    if place:
        result["PLZ / Gemeinde"] = f"{place.group(1)} {place.group(2).strip()}"
    rooms = re.search(r"\b(\d(?:[.,]5)?)\s*(?:zimmer|zi\.?|rooms?)\b|\b(?:zimmer|zi\.?)\s*[:\-]?\s*(\d(?:[.,]5)?)\b", text, re.I)
    if rooms:
        result["Zimmer"] = (rooms.group(1) or rooms.group(2)).replace(",", ".")
    amount = r"(?:CHF\s*)?([\d'’ .]{3,8})(?:\s*(?:CHF|Fr\.?|/\s*(?:Mt\.?|Monat)))?"
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


def queries(gemeinde: str, minimum: float, maximum: float, price: int) -> list[str]:
    criteria = f'"{gemeinde}" Mietwohnung {minimum:g} {maximum:g} Zimmer CHF {price}'
    return [
        f"{criteria} Inserat Adresse",
        f'"{gemeinde}" Wohnung mieten {minimum:g} bis {maximum:g} Zimmer bis {price} Franken',
        *[f"site:{portal} {criteria} Wohnung mieten" for portal in PORTALS],
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


def run_search(api_key: str, search_queries: list[str]) -> tuple[list[dict], list[dict], int]:
    results, calls, seen = [], [], set()
    for query in search_queries:
        try:
            data = post_tavily(SEARCH_URL, {
                "query": query, "search_depth": "basic", "topic": "general",
                "max_results": 10, "include_answer": False, "include_raw_content": False,
                "include_usage": True,
            }, api_key)
            found = data.get("results") or []
            calls.append({"query": query, "returned": len(found), "usage": data.get("usage"), "error": ""})
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
            calls.append({"query": query, "returned": 0, "usage": None, "error": str(exc)})
    return results, calls, sum(call["returned"] for call in calls)


def run_extract(api_key: str, results: list[dict], max_urls: int, advanced_limit: int) -> list[dict]:
    candidates = [row for row in results if row["category"] != "wahrscheinlich Übersichtsseite"]
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


def portal_summary(results: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in results:
        groups[row["domain"]].append(row)
    output = []
    for portal, rows in sorted(groups.items()):
        individual = sum(row["category"] == "wahrscheinlich Einzelinserat" for row in rows)
        extracted = sum(row["extract"].startswith("erfolgreich") for row in rows)
        address = sum(bool(row["fields"] and row["fields"]["Strasse + Hausnummer"] != "nicht erkannt"
                           and row["fields"]["PLZ / Gemeinde"] != "nicht erkannt") for row in rows)
        rooms = sum(bool(row["fields"] and row["fields"]["Zimmer"] != "nicht erkannt") for row in rows)
        price = sum(bool(row["fields"] and row["fields"]["sichtbare Miete"] != "nicht erkannt") for row in rows)
        output.append({"Domain": portal, "Suchresultate": len(rows), "wahrscheinlich Einzelinserate": individual,
                       "Extract erfolgreich": extracted, "Adresse erkannt": address,
                       "Zimmer erkannt": rooms, "Preis erkannt": price,
                       "brauchbare Direktlinks": f"{individual / len(rows):.0%}"})
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
    gemeinde = st.selectbox("Gemeinde", ["Reinach BL", "Basel", "Allschwil", "Binningen", "Münchenstein", "Muttenz"], index=0)
    left, middle, right = st.columns(3)
    minimum = left.number_input("Zimmer von", min_value=1.0, max_value=10.0, value=2.5, step=0.5)
    maximum = middle.number_input("Zimmer bis", min_value=1.0, max_value=10.0, value=3.5, step=0.5)
    price = right.number_input("Max. CHF/Monat", min_value=100, max_value=20000, value=1800, step=100)
    with st.expander("API-Aufwand begrenzen", expanded=False):
        max_urls = st.slider("Maximal mit Extract zu prüfende URLs", 0, 60, 20)
        advanced_limit = st.slider("Davon bei Fehler/Leere mit advanced erneut prüfen", 0, 5, 2)
        st.caption("6 Search-Aufrufe mit je höchstens 10 Treffern. Basic-Extract in Paketen bis 20 URLs; advanced nur für ausgewählte Fehlschläge. Tatsächliche Credits stehen unten, wenn Tavily sie liefert.")
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
        extract_calls = run_extract(api_key, results, max_urls, advanced_limit)
    st.subheader("API-Aufwand und Suchanfragen")
    st.write(f"{len(search_calls)} Search-Aufrufe · {returned} rohe Treffer · {len(results)} eindeutige exakte URLs · {len(extract_calls)} Extract-Aufrufe")
    st.dataframe(search_calls, use_container_width=True, hide_index=True)
    st.dataframe(extract_calls, use_container_width=True, hide_index=True)
    reported = [call["usage"].get("credits") for call in search_calls + extract_calls
                if isinstance(call.get("usage"), dict) and isinstance(call["usage"].get("credits"), (int, float))]
    st.write(f"Von Tavily gemeldete Credits: {sum(reported)}" if reported else "Tavily hat keine Credit-Zahl geliefert; Aufrufzahlen stehen oben.")
    st.subheader("Portal-Zusammenfassung")
    st.caption("Brauchbare Direktlinks = Anteil der anhand der URL wahrscheinlich konkreten Inserate; keine Bestätigung der Aktualität oder Extrahierbarkeit.")
    st.dataframe(portal_summary(results), use_container_width=True, hide_index=True)
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
                for field, value in row["fields"].items():
                    st.write(f"**{field}:** {value}")
                st.text_area("Rohtext-Ausschnitt (erste 3000 Zeichen)", row["raw"][:3000], height=180, key=f"raw_{index}")
            elif row["extract"].startswith(("Fehler", "leer", "API-Fehler")):
                st.write("**Rohtext:** nicht verfügbar")


if __name__ == "__main__":
    main()
