import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urlparse, urlunparse

import requests
import streamlit as st
from openai import OpenAI
from streamlit_local_storage import LocalStorage


# =========================================================
# SEITE
# =========================================================

st.set_page_config(
    page_title="Wohnungs-Finder Schweiz",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 Wohnungs-Finder Schweiz")
st.write(
    "Direkte Wohnungsinserate aus einer geprüften Flatfox-Momentaufnahme. "
    "Die laufend aktuelle Suche ist unten verlinkt."
)

st.subheader("Direkte Wohnungsinserate in Reinach BL")
st.caption(
    "Am 19.09.2026 direkt auf Flatfox gefunden: 2½–3½ Zimmer, "
    "angezeigte Miete bis CHF 1’800. Diese Liste ist eine Momentaufnahme und "
    "wird nicht automatisch aktualisiert. Preis und Verfügbarkeit im Inserat prüfen."
)
VERIFIZIERTE_DIREKTLINKS = [
    ("Fleischbachstr. 28", "2½", 1290, False, "https://flatfox.ch/de/wohnung/fleischbachstr-28-4153-reinach-bl/86317823/"),
    ("Mischelistrasse 55", "3", 1360, False, "https://flatfox.ch/de/wohnung/mischelistrasse-55-4153-reinach-bl/86208640/"),
    ("Christoph Merian-Ring 9", "2½", 1380, False, "https://flatfox.ch/de/wohnung/christoph-merian-ring-9-4153-reinach/86318495/"),
    ("Baselstrasse 96", "2½", 1400, True, "https://flatfox.ch/de/wohnung/baselstrasse-96-4153-reinach/86365175/"),
    ("Reichensteinerstrasse 10", "2½", 1425, True, "https://flatfox.ch/de/wohnung/reichensteinerstrasse-10-4153-reinach/86362731/"),
    ("Alemannenstrasse 1", "3", 1520, False, "https://flatfox.ch/de/wohnung/alemannenstrasse-1-4153-reinach-bl/86358915/"),
    ("Schönenbachstrasse 12", "3½", 1530, False, "https://flatfox.ch/de/wohnung/schonenbachstrasse-12-4153-reinach-bl/86308151/"),
    ("Adresse im Suchresultat nicht angegeben", "2½", 1586, False, "https://flatfox.ch/de/wohnung/4153-reinach-bl/86319129/"),
    ("Brühlgasse 5", "3", 1590, False, "https://flatfox.ch/de/wohnung/bruhlgasse-5-4153-reinach/86320280/"),
    ("Sonnenweg 28", "2½", 1700, True, "https://flatfox.ch/de/wohnung/sonnenweg-28-4153-reinach-bl/86351738/"),
]
for adresse, zimmer, miete, priority, url in VERIFIZIERTE_DIREKTLINKS:
    zusatz = " · Flatfox Priority" if priority else ""
    st.markdown(f"- **{adresse}** · {zimmer} Zimmer · CHF {miete:,}/Monat{zusatz} · [Inserat öffnen]({url})")
st.markdown(
    "[Laufend aktuelle Inserate direkt auf Flatfox ansehen]"
    "(https://flatfox.ch/de/search/?query=Reinach%20BL)"
)

st.divider()
st.stop()


# =========================================================
# KONSTANTEN
# =========================================================

STEUERFUESSE_BL_2026 = {
    "Aesch": 56.0,
    "Allschwil": 58.0,
    "Arlesheim": 47.0,
    "Binningen": 49.0,
    "Frenkendorf": 57.0,
    "Liestal": 65.0,
    "Münchenstein": 60.0,
    "Muttenz": 56.0,
    "Pratteln": 58.5,
    "Reinach": 58.5,
}

MERKLISTE_KEY = "wohnungs_finder_merkliste_v1"

localS = LocalStorage()


# =========================================================
# HILFSFUNKTIONEN
# =========================================================

def sichere_float_zahl(wert):
    try:
        if wert is None:
            return None

        if isinstance(wert, str):
            wert = wert.replace("'", "")
            wert = wert.replace("’", "")
            wert = wert.replace("CHF", "")
            wert = wert.strip()
            if re.fullmatch(r"\d{1,3}(?:[., ]\d{3})+", wert):
                wert = re.sub(r"[., ]", "", wert)
            else:
                wert = wert.replace(",", ".")

        return float(wert)

    except (ValueError, TypeError):
        return None


def sichere_int_zahl(wert, standard=0):
    try:
        return int(wert)
    except (ValueError, TypeError):
        return standard


def quelle_aus_url(url):
    try:
        domain = urlparse(url).netloc.lower()
        return domain.replace("www.", "")
    except Exception:
        return ""


def normalisiere_text(text):
    if text is None:
        return ""

    text = str(text).lower().strip()

    text = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("é", "e")
        .replace("è", "e")
        .replace("à", "a")
    )

    text = text.replace("strasse", "str")
    text = text.replace("straße", "str")

    text = re.sub(
        r"[^a-z0-9]",
        "",
        text,
    )

    return text


def normalisiere_ort(text):
    """
    Macht aus z.B.
    '4153 Reinach BL'
    'Reinach'

    und aus
    'Reinach BL'
    ebenfalls
    'Reinach'.
    """

    if not text:
        return ""

    text = str(text).strip()

    # PLZ entfernen
    text = re.sub(
        r"^\s*\d{4}\s+",
        "",
        text,
    )

    # Kantonskürzel am Ende entfernen
    text = re.sub(
        r"\s+(BL|BS|AG|SO|ZH|BE|LU|TI|SG|GR|TG|SH|SZ|ZG|UR|NW|OW|GL|FR|VD|VS|NE|JU|GE|AR|AI)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return text.strip()


def ort_ist_erlaubt(
    wohnungsort,
    suchorte,
):
    """
    Version 9.8:
    Eine Wohnung wird nur übernommen,
    wenn ihr Ort wirklich zu den gewählten
    Suchorten gehört.
    """

    wohnort = normalisiere_text(
        normalisiere_ort(
            wohnungsort
        )
    )

    if not wohnort:
        return False

    for suchort in suchorte:
        erlaubt = normalisiere_text(
            normalisiere_ort(
                suchort
            )
        )

        if wohnort == erlaubt:
            return True

    return False


def gemeinde_aus_text(text):
    if not text:
        return None

    text_klein = str(text).lower()

    for gemeinde in STEUERFUESSE_BL_2026:
        if gemeinde.lower() in text_klein:
            return gemeinde

    return None


def normalisiere_gemeinde(text):
    return normalisiere_ort(text)


def adresse_anzeigen(
    strasse,
    ort,
):
    teile = []

    if strasse:
        teile.append(
            str(strasse).strip()
        )

    if ort:
        teile.append(
            str(ort).strip()
        )

    return ", ".join(teile)


def brauchbare_strasse(strasse):
    if not strasse:
        return False

    text = str(strasse).strip()

    if len(text) < 3:
        return False

    # Hausnummer muss vorhanden sein
    if not re.search(
        r"\d",
        text,
    ):
        return False

    # Nur PLZ ist keine Strasse
    if re.fullmatch(
        r"\d{4}",
        text,
    ):
        return False

    return True


def wohnungs_schluessel(
    wohnung,
):
    """
    Version 9.8:
    Gleiche Strasse + Ort = gleiche Wohnung.

    Dadurch verschwinden Dubletten,
    auch wenn zwei Portale leicht
    unterschiedliche Angaben liefern.
    """

    return (
        normalisiere_text(
            wohnung.get("strasse")
        ),
        normalisiere_text(
            wohnung.get("ort")
        ),
    )


# =========================================================
# STEUERFUSS
# =========================================================

def steuervergleich(
    wohnort,
    suchorte,
):
    gemeinde = gemeinde_aus_text(
        wohnort
    )

    if gemeinde is None:
        return None

    steuerfuss = (
        STEUERFUESSE_BL_2026.get(
            gemeinde
        )
    )

    if steuerfuss is None:
        return None

    vergleichswerte = []

    for ort in suchorte:
        normalisiert = (
            normalisiere_gemeinde(
                ort
            )
        )

        if (
            normalisiert
            in STEUERFUESSE_BL_2026
        ):
            vergleichswerte.append(
                STEUERFUESSE_BL_2026[
                    normalisiert
                ]
            )

    if not vergleichswerte:
        return {
            "gemeinde": gemeinde,
            "steuerfuss": steuerfuss,
            "vergleich": "kein Vergleich",
            "guenstig": None,
        }

    durchschnitt = (
        sum(vergleichswerte)
        / len(vergleichswerte)
    )

    if steuerfuss < durchschnitt - 1:
        vergleich = "eher tiefer"
        guenstig = True

    elif steuerfuss > durchschnitt + 1:
        vergleich = "eher höher"
        guenstig = False

    else:
        vergleich = "mittlerer Bereich"
        guenstig = True

    return {
        "gemeinde": gemeinde,
        "steuerfuss": steuerfuss,
        "vergleich": vergleich,
        "durchschnitt": durchschnitt,
        "guenstig": guenstig,
    }


# =========================================================
# TAVILY
# =========================================================

@st.cache_data(ttl=1200, show_spinner=False)
def tavily_suche(
    suchtext,
    max_results=10,
):
    api_key = st.secrets.get(
        "TAVILY_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY fehlt in "
            "den Streamlit Secrets."
        )

    payload = {
        "api_key": api_key,
        "query": suchtext,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }

    response = requests.post(
        "https://api.tavily.com/search",
        json=payload,
        timeout=35,
    )

    response.raise_for_status()

    return response.json().get(
        "results",
        [],
    )


@st.cache_data(ttl=1200, show_spinner=False)
def inserate_suchen(orte, min_zimmer, max_zimmer):
    """Mehrere konkrete Inserat-Suchen, 20 Minuten zwischengespeichert."""
    suchtexte = []
    for ort in orte:
        gemeinde = normalisiere_ort(ort)
        suchtexte.append(
            f'"{gemeinde}" Mietwohnung Inserat {min_zimmer:g} bis '
            f'{max_zimmer:g} Zimmer Strasse Hausnummer CHF'
        )
    ergebnisse = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        auftraege = [pool.submit(tavily_suche, q, 10) for q in suchtexte]
        for auftrag in as_completed(auftraege):
            ergebnisse.extend(auftrag.result())
    return sorted(ergebnisse, key=lambda t: t.get("url") or ""), time.time()


# =========================================================
# KI
# =========================================================

def ki_extrahiere_paket(
    treffer_liste,
):
    client = OpenAI(
        api_key=st.secrets[
            "OPENAI_API_KEY"
        ]
    )

    kompakte_treffer = []

    for treffer in treffer_liste:
        text = (
            treffer.get(
                "raw_content"
            )
            or treffer.get(
                "content"
            )
            or ""
        )

        text = text[:2600]

        kompakte_treffer.append(
            {
                "treffer_id":
                    treffer[
                        "_interne_id"
                    ],
                "titel":
                    treffer.get(
                        "title",
                        "",
                    ),
                "url":
                    treffer.get(
                        "url",
                        "",
                    ),
                "text":
                    text,
            }
        )

    daten_text = json.dumps(
        kompakte_treffer,
        ensure_ascii=False,
    )

    prompt = f"""
Du analysierst Schweizer Mietwohnungsinserate.

Ein Suchtreffer kann eine einzelne Wohnung oder
eine Seite mit mehreren Wohnungen enthalten.

Extrahiere alle eindeutig erkennbaren einzelnen
Wohnungen.

SEHR WICHTIG BEI PREISEN:

Beispiel:

Net rent: CHF 1,420
Add'l expenses: CHF 180
Rent: CHF 1,600

Dann MUSST du liefern:

nettomiete = 1420
nebenkosten = 180
bruttomiete_ohne_parkplatz = 1600
angegebene_miete = 1600
mietpreis_art = "brutto"

Wenn ein Parkplatz separat z.B. CHF 120 kostet:

parkplatz_kosten = 120

Der Parkplatzpreis darf NICHT mit Nebenkosten
verwechselt werden.

Wenn im Inserat Nettomiete und Nebenkosten
vorhanden sind, müssen beide separat ausgegeben
werden. Suche ausdrücklich auch nach den Begriffen
"Netto Miete", "Nettomiete", "Nebenkosten", "NK",
"Bruttomiete", "Miete", "Net rent" und "Add'l expenses".
Beispiel: Netto Miete CHF 1'343 + Nebenkosten CHF 250 +
Miete CHF 1'593 => nettomiete=1343, nebenkosten=250,
bruttomiete_ohne_parkplatz=1593, angegebene_miete=1593.

Keine Daten verschiedener Wohnungen vermischen.
Keine Angaben erfinden.

Antworte ausschließlich als gültiges JSON:

{{
  "wohnungen": [
    {{
      "treffer_id": 1,
      "titel": null,
      "strasse": null,
      "ort": null,
      "zimmer": null,
      "angegebene_miete": null,
      "mietpreis_art": "unbekannt",
      "nettomiete": null,
      "nebenkosten": null,
      "bruttomiete_ohne_parkplatz": null,
      "parkplatz_kosten": null,
      "nicht_erdgeschoss": null,
      "balkon": null,
      "modern": null,
      "ruhig": null,
      "parkplatz": null,
      "begehbare_dusche": null,
      "badewanne": null,
      "gute_oev": null,
      "einzelwohnung_sicher": true
    }}
  ]
}}

REGELN:

strasse:
Nur Strasse und Hausnummer.

ort:
PLZ und Gemeinde.

zimmer:
Nur die Zimmerzahl dieser Wohnung.

angegebene_miete:
Die im Inserat als "Miete", "Rent",
"Bruttomiete" oder Gesamtmiete ausgewiesene
monatliche Miete.

mietpreis_art:
"netto"
"brutto"
"inkl_nebenkosten"
"unbekannt"

nettomiete:
Nur reine Nettomiete.

nebenkosten:
Nur monatliche Nebenkosten.

bruttomiete_ohne_parkplatz:
Nettomiete + Nebenkosten,
wenn eindeutig bekannt.

parkplatz_kosten:
Monatliche Parkplatz-/Garagenkosten.

Bei Ja/Nein-Feldern:

true = eindeutig bestätigt
false = eindeutig verneint
null = unbekannt

nicht_erdgeschoss:
true bei 1., 2., 3. Stock usw.
false bei Erdgeschoss, EG, Parterre, Hochparterre oder ground floor.
WICHTIG: Wenn bei den Eckdaten "Geschoss nicht verfügbar" steht,
aber in der Beschreibung "Parterre", "Erdgeschoss" oder "EG",
gilt nicht_erdgeschoss trotzdem als false.

balkon:
true bei Balkon oder Terrasse.

modern:
true bei modern, renoviert, saniert,
neuwertig, Neubau oder hochwertigem Ausbau.

ruhig:
true nur bei ausdrücklich ruhiger Lage.

parkplatz:
true bei Parkplatz, Garage,
Einstellplatz oder Autoabstellplatz.

begehbare_dusche:
true nur bei begehbarer,
bodenebener oder Walk-in-Dusche.

badewanne:
true wenn Badewanne vorhanden.
false nur wenn ausdrücklich keine vorhanden.

gute_oev:
true bei guter ÖV-Anbindung oder nahe
Bus-, Tram- oder Bahnhaltestelle.

TREFFER:

{daten_text}
"""

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )

    output = (
        response.output_text
        .replace(
            "```json",
            "",
        )
        .replace(
            "```",
            "",
        )
        .strip()
    )

    daten = json.loads(
        output
    )

    return daten.get(
        "wohnungen",
        [],
    )


# =========================================================
# SCHNELLE TEXTKONTROLLE
# =========================================================

def lokale_textkontrolle(analyse, original):
    """
    Version 9.8:
    Einfache, eindeutige Begriffe werden direkt im
    gelieferten Seitentext geprüft. Das ist schneller
    und robuster als dafür nochmals KI aufzurufen.
    """
    text = wohnungsspezifischer_text(analyse, original)
    if not text:
        return analyse
    text = text.lower()

    # Erdgeschoss / Parterre
    eg_muster = [
        r"\bparterre\b",
        r"\berdgeschoss\b",
        r"\bhochparterre\b",
        r"\bground floor\b",
        r"\bim eg\b",
        r"\beg-wohnung\b",
    ]
    if any(re.search(m, text) for m in eg_muster):
        analyse["nicht_erdgeschoss"] = False

    # Eindeutige positive Hinweise – nur setzen, wenn KI noch nichts wusste.
    if analyse.get("balkon") is None:
        if re.search(r"\bbalkon\b|\bterrasse\b", text):
            analyse["balkon"] = True

    if analyse.get("parkplatz") is None:
        if re.search(
            r"\bparkplatz\b|\bautoabstellplatz\b|\beinstellplatz\b|"
            r"\btiefgaragenplatz\b|\bgaragenplatz\b",
            text,
        ):
            analyse["parkplatz"] = True

    if analyse.get("begehbare_dusche") is None:
        if re.search(
            r"\bwalk[- ]?in[- ]?dusche\b|\bbodengleiche dusche\b|"
            r"\bbodenebene dusche\b|\bbegehbare dusche\b",
            text,
        ):
            analyse["begehbare_dusche"] = True

    if analyse.get("badewanne") is None:
        if re.search(r"\bbadewanne\b|\bbad mit wanne\b", text):
            analyse["badewanne"] = True

    if analyse.get("modern") is None:
        if re.search(
            r"\bneubau\b|\bneuwertig\b|\bmodern\b|\bsaniert\b|"
            r"\brenoviert\b|\bhochwertig", text
        ):
            analyse["modern"] = True

    if analyse.get("ruhig") is None:
        if re.search(
            r"\bruhige lage\b|\bruhig gelegen\b|\bruhige wohnlage\b",
            text,
        ):
            analyse["ruhig"] = True

    if analyse.get("gute_oev") is None:
        if re.search(
            r"\böffentliche verkehr\b|\bö[vV]\b|\bbushaltestelle\b|"
            r"\btramhaltestelle\b|\bbahnhof\b",
            text,
        ):
            analyse["gute_oev"] = True

    if analyse.get("lift") is None:
        if re.search(r"\b(?:kein|ohne)\s+(?:lift|aufzug)\b", text):
            analyse["lift"] = False
        elif re.search(r"\b(?:lift|aufzug)\b", text):
            analyse["lift"] = True
    if analyse.get("stockwerk") is None:
        m = re.search(r"\b(\d{1,2})\.?\s*(?:stock|etage|geschoss)\b", text)
        if m:
            analyse["stockwerk"] = int(m.group(1))
            analyse["nicht_erdgeschoss"] = int(m.group(1)) > 0
    return analyse


# =========================================================
# VERSION 10.0 – LOKALE PREISPRÜFUNG
# =========================================================

def wohnungsspezifischer_text(analyse, original):
    """Nur lokale Angaben einer eindeutig einzelnen Wohnung übernehmen."""
    strasse = str(analyse.get("strasse") or "").strip()
    if not brauchbare_strasse(strasse):
        return ""
    title = str(original.get("title") or "")
    content = str(original.get("content") or "")
    raw = str(original.get("raw_content") or "")
    text = " ".join((title, content, raw))
    if strasse.casefold() not in text.casefold():
        return ""
    # Auf Listen können Preise und Eigenschaften benachbarter Inserate stehen.
    # Ein weiteres Strassen-/Hausnummer-Muster macht lokale Overrides unsicher.
    adressen = re.findall(
        r"\b[A-ZÄÖÜ][\wäöüÄÖÜß.\- ]{2,45}?"
        r"(?:strasse|straße|weg|gasse|allee|platz|ring)\s+\d+[a-zA-Z]?\b",
        text, flags=re.IGNORECASE,
    )
    fremde = [a for a in adressen if strasse.casefold() not in a.casefold()
              and a.casefold() not in strasse.casefold()]
    if fremde:
        return ""
    # Mehrere unterschiedliche Mieten auf derselben Seite sind ein Listenhinweis.
    mietwerte = re.findall(
        r"(?:netto\s*miete|nettomiete|bruttomiete|gesamtmiete|"
        r"miete\s+inkl\.?\s*nebenkosten)\s*[:\-]?\s*(?:CHF)?\s*"
        r"([0-9][0-9'’., ]*)", text, flags=re.IGNORECASE,
    )
    if len({sichere_float_zahl(x) for x in mietwerte if sichere_float_zahl(x)}) > 2:
        return ""
    return text[:6000]


def preis_aus_text(text, muster):
    m = re.search(muster, text, flags=re.IGNORECASE)
    if not m:
        return None
    return sichere_float_zahl(m.group(1))


def lokale_preiskontrolle(analyse, original):
    ausschnitt = wohnungsspezifischer_text(analyse, original)
    if not ausschnitt:
        return analyse
    zahl = r"([0-9][0-9'’., ]*)"
    netto = preis_aus_text(ausschnitt, rf"(?:mietpreis\s*exkl\.?\s*(?:nk|nebenkosten)|netto\s*miete|nettomiete|net\s*rent)\s*[:\-]?\s*(?:chf)?\s*{zahl}")
    nk = preis_aus_text(ausschnitt, rf"(?:nebenkosten|add['’]?l\s*expenses|additional\s*expenses)\s*[:\-]?\s*(?:chf)?\s*{zahl}")
    if nk is None:
        nk = preis_aus_text(ausschnitt, rf"\bNK\b\s*[:\-]?\s*(?:chf)?\s*{zahl}")
    brutto = preis_aus_text(ausschnitt, rf"(?:bruttomiete|gesamtmiete|miete\s+inkl\.?\s*nebenkosten|mietpreis(?!\s*exkl))\s*[:\-]?\s*(?:chf)?\s*{zahl}")
    park = preis_aus_text(ausschnitt, rf"(?:parkplatz|einstellplatz|autoabstellplatz|garagenplatz|tiefgaragenplatz)[^0-9]{{0,80}}(?:chf)\s*{zahl}")
    if netto is not None:
        analyse["nettomiete"] = netto
    if nk is not None:
        analyse["nebenkosten"] = nk
    if netto is not None and nk is not None:
        analyse["bruttomiete_ohne_parkplatz"] = netto + nk
        analyse["angegebene_miete"] = netto + nk
        analyse["mietpreis_art"] = "brutto"
    elif brutto is not None:
        analyse["bruttomiete_ohne_parkplatz"] = brutto
        analyse["angegebene_miete"] = brutto
        analyse["mietpreis_art"] = "brutto"
    if park is not None and 20 <= park <= 500:
        analyse["parkplatz_kosten"] = park
        analyse["parkplatz"] = True
    return analyse


def direkte_links_suchen(ergebnisse):
    if not ergebnisse:
        return ergebnisse
    api_key = st.secrets.get("TAVILY_API_KEY")
    if not api_key:
        return ergebnisse
    adressen = []
    for w in ergebnisse[:10]:
        a = adresse_anzeigen(w.get("strasse"), w.get("ort"))
        if a:
            adressen.append(f'"{a}"')
    if not adressen:
        return ergebnisse
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": "Mietwohnung Inserat Schweiz " + " OR ".join(adressen),
                "search_depth": "advanced",
                "max_results": 15,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=25,
        )
        response.raise_for_status()
        kandidaten = response.json().get("results", [])
    except Exception:
        return ergebnisse
    for w in ergebnisse:
        s = normalisiere_text(w.get("strasse"))
        o = normalisiere_text(normalisiere_ort(w.get("ort")))
        bester, punkte_best = None, 0
        for k in kandidaten:
            u = k.get("url", "")
            ptxt = normalisiere_text(f"{k.get('title','')} {k.get('content','')} {u}")
            punkte = (3 if s and s in ptxt else 0) + (1 if o and o in ptxt else 0)
            if punkte > punkte_best:
                bester, punkte_best = k, punkte
        if bester is not None and punkte_best >= 3:
            kandidat_url = bester.get("url", "")
            pfad = urlparse(kandidat_url).path.strip("/")
            # Such- und Startseiten sind keine individuellen Inserate.
            listenpfade = {"", "search", "suche", "mieten", "rent", "immobilien"}
            direkt_pfad = bool(re.search(
                r"(?:/|\b)(?:detail|details|listing|inserat|objekt|object)/|"
                r"/[0-9]{5,}(?:[/?-]|$)", kandidat_url, flags=re.IGNORECASE,
            ))
            adress_slug = normalisiere_text(pfad)
            if s and s in adress_slug:
                direkt_pfad = True
            if pfad.casefold() not in listenpfade and direkt_pfad and not any(
                x in kandidat_url.casefold() for x in ("/search?", "/suche?", "/list?")
            ):
                w["url"] = kandidat_url
                w["quelle"] = quelle_aus_url(w["url"])
                w["direktlink"] = True
            else:
                w["direktlink"] = False
        else:
            w["direktlink"] = False
    return ergebnisse


class InseratText(HTMLParser):
    """Sichtbaren Text einer einzelnen Inseratseite einsammeln."""
    def __init__(self):
        super().__init__()
        self.teile = []
        self.verbergen = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.verbergen += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.verbergen = max(0, self.verbergen - 1)

    def handle_data(self, data):
        if not self.verbergen and data.strip():
            self.teile.append(data.strip())


def ist_direktlink(url, strasse=""):
    pfad = urlparse(url or "").path.strip("/").lower()
    if not pfad or pfad in {"search", "suche", "mieten", "rent", "immobilien"}:
        return False
    slug = normalisiere_text(pfad)
    adresse = normalisiere_text(strasse)
    return bool(
        re.search(r"(?:detail|listing|inserat|objekt|object|angebot)/|\d{5,}", pfad)
        or (adresse and adresse in slug)
    )


def detailseite_laden(wohnung):
    """Direkte Seite lesen; Listen und fremde Inserate nicht zuordnen."""
    url = wohnung.get("url") or ""
    if not ist_direktlink(url, wohnung.get("strasse")):
        return "", "kein sicherer Direktlink"
    try:
        antwort = requests.get(
            url, timeout=(4, 9), headers={"User-Agent": "Mozilla/5.0"},
        )
        antwort.raise_for_status()
        if "html" not in antwort.headers.get("Content-Type", "").lower():
            return "", "kein HTML"
        parser = InseratText()
        parser.feed(antwort.text[:750000])
        text = " ".join(parser.teile)
        text = re.sub(r"\s+", " ", text)
        if normalisiere_text(wohnung.get("strasse")) not in normalisiere_text(text):
            return "", "Adresse auf Detailseite nicht gefunden"
        if normalisiere_text(normalisiere_ort(wohnung.get("ort"))) not in normalisiere_text(text):
            return "", "Ort auf Detailseite nicht bestätigt"
        if not wohnungsspezifischer_text(wohnung, {"title": "", "content": text}):
            return "", "Detailseite enthält mehrere Wohnungen"
        return text[:18000], "Detailseite gelesen"
    except (requests.RequestException, ValueError) as exc:
        return "", f"Detailseite nicht lesbar: {type(exc).__name__}"


@st.cache_data(ttl=1200, show_spinner=False)
def schnelle_wohnungen(treffer):
    """Kleiner KI-Aufruf nur für die erste Trefferliste."""
    daten = [
        {"treffer_id": t["_interne_id"], "titel": t.get("title", ""),
         "url": t.get("url", ""), "text": (t.get("content") or "")[:1100]}
        for t in (json.loads(x) for x in treffer)
    ]
    antwort = OpenAI(api_key=st.secrets["OPENAI_API_KEY"]).responses.create(
        model="gpt-5-mini",
        input=(
            "Extrahiere nur einzelne Schweizer Mietwohnungen. Übersichtsseiten mit mehreren Wohnungen überspringen. "
            "Nur Angaben aus demselben konkreten Inserat; Adresse, Ort und Miete müssen gemeinsam belegt sein. Nichts erfinden oder mischen. "
            "Antworte nur als JSON mit Wohnungen als Liste. Felder: treffer_id, "
            "titel, strasse, ort, zimmer, angegebene_miete, mietpreis_art "
            "(brutto/netto/unbekannt), einzelwohnung_sicher. "
            "Eine unbekannte Preisart bleibt unbekannt. TREFFER: "
            + json.dumps(daten, ensure_ascii=False)
        ),
    )
    return json.loads(antwort.output_text.strip().removeprefix("```json").removesuffix("```").strip()).get("wohnungen", [])


# VERSION 10.0.1 – Kandidaten zuerst ohne Detail-KI erkennen.
ADRESS_MUSTER = re.compile(
    r"\b([A-ZÄÖÜ][A-Za-zÄÖÜäöüßéèà.\-]*"
    r"(?:strasse|straße|str\.?|weg|gasse|allee|platz|ring)\s*\d+[a-zA-Z]?)\b",
    re.IGNORECASE,
)
ZIMMER_MUSTER = re.compile(r"\b(\d(?:[.,]5|\s*½)?)\s*(?:[- ]?zimmer|zi\.?\b|rooms?\b)", re.IGNORECASE)
CHF_MUSTER = re.compile(r"\bCHF\s*([1-9]\d{0,3}(?:['’., ]\d{3})?)\b", re.IGNORECASE)


def einzeltext_der_quelle(quelle):
    """Nutzt Rohtext nur, wenn Titel und Snippet keine Adresse belegen."""
    kern = " ".join(str(quelle.get(k) or "") for k in ("title", "content"))
    kern_adressen = {normalisiere_text(m.group(1)) for m in ADRESS_MUSTER.finditer(kern)}
    if len(kern_adressen) > 1:
        return ""
    if len(kern_adressen) == 1:
        return kern
    raw = str(quelle.get("raw_content") or "")[:3500]
    raw_adressen = {normalisiere_text(m.group(1)) for m in ADRESS_MUSTER.finditer(raw)}
    return " ".join((kern, raw)) if len(raw_adressen) == 1 else ""


def kandidaten_aus_snippets(quellen, suchorte):
    """Extrahiert nur eine Wohnung pro eindeutigem Suchtreffer.

    Listen mit mehreren Adressen werden übersprungen; ihre Preise und
    Gemeinden dürfen nie miteinander kombiniert werden.
    """
    kandidaten = []
    for quelle in quellen:
        titel = str(quelle.get("title") or "")
        inhalt = str(quelle.get("content") or "")
        text = einzeltext_der_quelle(quelle)
        raw = str(quelle.get("raw_content") or "")[:3500] if text != " ".join((titel, inhalt)) else ""
        adressen = {normalisiere_text(m.group(1)): m.group(1).strip()
                    for m in ADRESS_MUSTER.finditer(text)}
        if len(adressen) != 1:
            continue
        strasse = next(iter(adressen.values()))
        if not ist_direktlink(quelle.get("url", ""), strasse):
            continue
        # Ort muss am selben Adressvorkommen stehen. Auch nicht ausgewählte
        # Gemeinden erkennen, damit z.B. Arlesheim nie Reinach wird.
        ortsnamen = list(dict.fromkeys(
            [normalisiere_ort(o) for o in suchorte]
            + list(STEUERFUESSE_BL_2026)
        ))
        # Die erste Quelle
        # (Titel/Snippet) hat Vorrang vor längeren Seitentexten.
        ort = None
        for teil in (titel, inhalt, raw):
            for m in ADRESS_MUSTER.finditer(teil):
                if normalisiere_text(m.group(1)) != normalisiere_text(strasse):
                    continue
                # Der nächststehende Ort nach der Adresse ist massgeblich.
                # Ein anderer Ort weiter unten darf ihn nicht überschreiben.
                nach = teil[m.end():m.end()+65]
                ortspositionen = [(x.start(), normalisiere_ort(o)) for o in ortsnamen
                                 for x in re.finditer(r"\b" + re.escape(normalisiere_ort(o)) + r"\b",
                                                      nach, re.IGNORECASE)]
                if ortspositionen:
                    ort = min(ortspositionen)[1]
                    break
                vorher = teil[max(0, m.start()-55):m.start()]
                ortspositionen = [(len(vorher)-x.end(), normalisiere_ort(o)) for o in ortsnamen
                                 for x in re.finditer(r"\b" + re.escape(normalisiere_ort(o)) + r"\b",
                                                      vorher, re.IGNORECASE)]
                if ortspositionen:
                    ort = min(ortspositionen)[1]
                    break
            if ort:
                break
        if not ort:
            continue
        zimmer = ZIMMER_MUSTER.search(text)
        if not zimmer:
            continue
        zimmerwert = zimmer.group(1).replace("½", ".5").replace(" ", "")
        zimmerzahl = sichere_float_zahl(zimmerwert)
        # Nur Werte aus diesem einen Inserat. NK und Parkplatz nie als
        # Wohnmiete interpretieren; ein einzelner CHF-Wert ist sichtbar.
        mietwerte = []
        for m in CHF_MUSTER.finditer(text):
            davor = text[max(0, m.start()-65):m.start()].lower()
            alle_label = list(re.finditer(
                r"(?:netto\s*|brutto\s*|gesamt\s*)?(?:miete|mietzins|rent|preis|price)"
                r"|(?:parkplatz|garage|einstellplatz|nebenkosten|\bnk\b)", davor))
            label = alle_label[-1] if alle_label else None
            if label and m.start() - (max(0, m.start()-65) + label.end()) <= 22:
                preis = sichere_float_zahl(m.group(1))
                bezeichnung = label.group(0)
                if (preis is not None
                        and re.search(r"miete|mietzins|rent|preis|price", bezeichnung)
                        and not re.search(r"netto|exkl|without", bezeichnung)):
                    mietwerte.append(preis)
        alle_preise = [sichere_float_zahl(m.group(1)) for m in CHF_MUSTER.finditer(text)]
        alle_preise = [p for p in alle_preise if p is not None]
        preis = mietwerte[0] if len(set(mietwerte)) == 1 else None
        if preis is None and len(set(alle_preise)) == 1:
            if not re.search(r"\b(?:parkplatz|garage|einstellplatz|nebenkosten|nk)\b[^.]{0,25}CHF", text, re.I):
                preis = alle_preise[0]
        kandidaten.append({
            "treffer_id": quelle["_interne_id"], "titel": titel,
            "strasse": strasse, "ort": ort, "zimmer": zimmerzahl,
            "angegebene_miete": preis,
            "mietpreis_art": "unbekannt", "einzelwohnung_sicher": True,
        })
    return kandidaten


def stufe1_kandidaten(quellen, suchorte):
    """Stufe 1 ist vollständig deterministisch und benötigt keinen OpenAI-Schlüssel."""
    original_nach_id = {t["_interne_id"]: t for t in quellen}

    def belegte_liste(liste):
        if not isinstance(liste, list):
            return []
        belegt = []
        for w in liste:
            if not isinstance(w, dict) or not w.get("einzelwohnung_sicher"):
                continue
            try:
                quelle = original_nach_id[int(w.get("treffer_id"))]
            except (KeyError, ValueError, TypeError):
                continue
            if belegter_einzelner_treffer(w, quelle):
                belegt.append(w)
        return belegt

    parser = belegte_liste(kandidaten_aus_snippets(quellen, suchorte))
    return parser, len(parser), 0, 0


def belegter_einzelner_treffer(analyse, quelle):
    """Reject list pages and claims not actually present in the same result."""
    text = einzeltext_der_quelle(quelle)
    addr = normalisiere_text(analyse.get("strasse"))
    town = normalisiere_text(normalisiere_ort(analyse.get("ort")))
    norm = normalisiere_text(text)
    if not addr or addr not in norm or not town or town not in norm:
        return False
    # The municipality must be tied to this address, not another result on
    # the same page.
    address_at = norm.find(addr)
    if town not in norm[max(0, address_at - 70):address_at + len(addr) + 70]:
        return False
    # Eine direkt an der Adresse stehende Gemeinde hat Vorrang vor
    # Ortsnamen aus Überschrift, Navigation oder einem anderen Inserat.
    address_match = re.search(re.escape(str(analyse.get("strasse"))), text, re.IGNORECASE)
    if address_match:
        direkt_danach = text[address_match.end():address_match.end()+55]
        lokale_orte = [(m.start(), normalisiere_text(g))
                       for g in STEUERFUESSE_BL_2026
                       for m in re.finditer(r"\b" + re.escape(g) + r"\b", direkt_danach, re.IGNORECASE)]
        if lokale_orte and min(lokale_orte)[1] != town:
            return False
    addresses = {normalisiere_text(m.group(1)) for m in ADRESS_MUSTER.finditer(text)}
    if len(addresses) > 1:
        return False
    price = sichere_float_zahl(analyse.get("angegebene_miete"))
    if price is not None:
        digits = str(int(price))
        if not re.search(r"(?<!\d)" + r"[\s'’.,]*".join(digits) + r"(?!\d)", text):
            return False
    return True


def detailanalyse(wohnung, detailtext):
    """Teure Merkmalsanalyse nur für bereits angezeigte Wohnungen."""
    antwort = OpenAI(api_key=st.secrets["OPENAI_API_KEY"]).responses.create(
        model="gpt-5-mini",
        input=(
            "Analysiere nur dieses einzelne Inserat. Gib JSON zurück mit "
            "nettomiete, nebenkosten, bruttomiete_ohne_parkplatz, "
            "parkplatz_kosten und den Feldern nicht_erdgeschoss, balkon, "
            "parkplatz, begehbare_dusche, badewanne, modern, ruhig, gute_oev, lift, stockwerk, rollstuhlgängig. "
            "Ja/Nein-Felder sind true, false oder null. Zahlen nur bei eindeutiger "
            "monatlicher CHF-Angabe; unbekannt ist null. Keine Werte erfinden. "
            "Wohnung: " + json.dumps({k: wohnung.get(k) for k in ("strasse", "ort", "zimmer")}, ensure_ascii=False)
            + " Text: " + detailtext[:11000]
        ),
    )
    return json.loads(antwort.output_text.strip().removeprefix("```json").removesuffix("```").strip())


# =========================================================
# PREISE
# =========================================================

def preise_bereinigen(
    analyse,
):
    """
    Version 9.8:
    Preisangaben werden nach der KI
    nochmals logisch geprüft.
    """

    netto = sichere_float_zahl(
        analyse.get(
            "nettomiete"
        )
    )

    nk = sichere_float_zahl(
        analyse.get(
            "nebenkosten"
        )
    )

    brutto = sichere_float_zahl(
        analyse.get(
            "bruttomiete_ohne_parkplatz"
        )
    )

    angegeben = sichere_float_zahl(
        analyse.get(
            "angegebene_miete"
        )
    )

    park = sichere_float_zahl(
        analyse.get(
            "parkplatz_kosten"
        )
    )

    # Wenn Netto + NK vorhanden sind,
    # berechnen wir Brutto selbst.
    if (
        netto is not None
        and nk is not None
    ):
        berechnet = netto + nk

        # Selbst berechneter Wert ist
        # verlässlicher als KI-Brutto.
        brutto = berechnet

    # Wenn Brutto bekannt, ist dies
    # die relevante Wohnmiete.
    if brutto is not None:
        angegeben = brutto

    analyse["nettomiete"] = netto
    analyse["nebenkosten"] = nk
    analyse[
        "bruttomiete_ohne_parkplatz"
    ] = brutto
    analyse[
        "angegebene_miete"
    ] = angegeben
    analyse[
        "parkplatz_kosten"
    ] = park

    return analyse


def bekannte_wohnkosten(
    analyse,
):
    brutto = sichere_float_zahl(
        analyse.get(
            "bruttomiete_ohne_parkplatz"
        )
    )

    netto = sichere_float_zahl(
        analyse.get(
            "nettomiete"
        )
    )

    nk = sichere_float_zahl(
        analyse.get(
            "nebenkosten"
        )
    )

    angegeben = sichere_float_zahl(
        analyse.get(
            "angegebene_miete"
        )
    )

    mietpreis_art = analyse.get(
        "mietpreis_art"
    )

    if brutto is not None:
        return brutto

    if (
        netto is not None
        and nk is not None
    ):
        return netto + nk

    if (
        angegeben is not None
        and mietpreis_art in [
            "brutto",
            "inkl_nebenkosten",
        ]
    ):
        return angegeben

    return None


def gesamtpreis_berechnen(
    analyse,
    parkplatz_gewuenscht,
):
    wohnkosten = (
        bekannte_wohnkosten(
            analyse
        )
    )

    if wohnkosten is None:
        return None

    if parkplatz_gewuenscht:
        park = sichere_float_zahl(
            analyse.get(
                "parkplatz_kosten"
            )
        )

        # Parkplatz gewünscht:
        # Ist dessen Preis unbekannt,
        # kennen wir den echten Gesamtpreis
        # noch nicht.
        if park is None:
            return None

        return wohnkosten + park

    return wohnkosten


def ist_innerhalb_budget(
    analyse,
    max_miete,
    parkplatz_gewuenscht,
):
    """
    Harte Budgetgrenze.
    """

    angegeben = sichere_float_zahl(
        analyse.get(
            "angegebene_miete"
        )
    )
    netto = sichere_float_zahl(analyse.get("nettomiete"))

    brutto = bekannte_wohnkosten(
        analyse
    )

    park = sichere_float_zahl(
        analyse.get(
            "parkplatz_kosten"
        )
    )

    # Parkplatz ist ein Wunschmerkmal, kein harter Suchfilter.
    if ((brutto is not None and brutto > max_miete)
            or (angegeben is not None and angegeben > max_miete)
            or (netto is not None and netto > max_miete)):
        return False

    return True


# =========================================================
# BEWERTUNG
# =========================================================

def bewerte_wohnung(
    analyse,
    suchorte,
    max_miete,
    min_zimmer,
    max_zimmer,
    nicht_eg,
    balkon,
    modern,
    ruhig,
    parkplatz,
    dusche,
    keine_badewanne,
    oev,
    steuer,
    lift=False,
):
    punkte = 0
    beurteilbar = 0
    gesamt_wunschpunkte = 0
    bestaetigte_wunschpunkte = 0
    details = []

    gesamtpreis = (
        gesamtpreis_berechnen(
            analyse,
            parkplatz,
        )
    )

    angegebene_miete = (
        sichere_float_zahl(
            analyse.get(
                "angegebene_miete"
            )
        )
    )

    netto = sichere_float_zahl(
        analyse.get(
            "nettomiete"
        )
    )

    nk = sichere_float_zahl(
        analyse.get(
            "nebenkosten"
        )
    )

    park_kosten = sichere_float_zahl(
        analyse.get(
            "parkplatz_kosten"
        )
    )

    zimmer = sichere_float_zahl(
        analyse.get(
            "zimmer"
        )
    )

    # PREIS
    gesamt_wunschpunkte += 3

    if gesamtpreis is None:
        if angegebene_miete is not None:
            details.append(
                (
                    "❓",
                    "Gesamtpreis",
                    (
                        f"Bekannte Miete CHF "
                        f"{angegebene_miete:,.0f}; "
                        "Parkplatz oder Kosten noch offen"
                    ),
                )
            )
        else:
            details.append(
                (
                    "❓",
                    "Gesamtpreis",
                    "noch unbekannt",
                )
            )

    else:
        beurteilbar += 3

        if gesamtpreis <= max_miete:
            punkte += 3
            bestaetigte_wunschpunkte += 3

            details.append(
                (
                    "✅",
                    "Gesamtpreis",
                    f"CHF {gesamtpreis:,.0f}",
                )
            )

    # ZIMMER
    gesamt_wunschpunkte += 2

    if zimmer is None:
        details.append(
            (
                "❓",
                "Zimmer",
                "unbekannt",
            )
        )

    else:
        beurteilbar += 2

        if (
            min_zimmer
            <= zimmer
            <= max_zimmer
        ):
            punkte += 2
            bestaetigte_wunschpunkte += 2

            details.append(
                (
                    "✅",
                    "Zimmer",
                    f"{zimmer:g}",
                )
            )

    pruefungen = [
        ("Lift vorhanden", lift, analyse.get("lift"), False),
        (
            "Nicht Erdgeschoss",
            nicht_eg,
            analyse.get(
                "nicht_erdgeschoss"
            ),
            False,
        ),
        (
            "Balkon / Terrasse",
            balkon,
            analyse.get(
                "balkon"
            ),
            False,
        ),
        (
            "Moderner Ausbau",
            modern,
            analyse.get(
                "modern"
            ),
            False,
        ),
        (
            "Ruhige Lage",
            ruhig,
            analyse.get(
                "ruhig"
            ),
            False,
        ),
        (
            "Parkplatz",
            parkplatz,
            analyse.get(
                "parkplatz"
            ),
            False,
        ),
        (
            "Begehbare Dusche",
            dusche,
            analyse.get(
                "begehbare_dusche"
            ),
            False,
        ),
        (
            "Keine Badewanne",
            keine_badewanne,
            analyse.get(
                "badewanne"
            ),
            True,
        ),
        (
            "ÖV-Anbindung",
            oev,
            analyse.get(
                "gute_oev"
            ),
            False,
        ),
    ]

    for (
        name,
        gewuenscht,
        wert,
        umgekehrt,
    ) in pruefungen:

        if not gewuenscht:
            continue

        gesamt_wunschpunkte += 1

        if wert is None:
            details.append(
                (
                    "❓",
                    name,
                    "unbekannt",
                )
            )
            continue

        beurteilbar += 1

        if umgekehrt:
            erfuellt = (
                wert is False
            )
        else:
            erfuellt = (
                wert is True
            )

        if erfuellt:
            punkte += 1
            bestaetigte_wunschpunkte += 1

            details.append(
                (
                    "✅",
                    name,
                    "erfüllt",
                )
            )
        else:
            details.append(
                (
                    "❌",
                    name,
                    "nicht erfüllt",
                )
            )

    steuer_info = steuervergleich(
        analyse.get(
            "ort"
        ),
        suchorte,
    )

    if steuer:
        gesamt_wunschpunkte += 1

        if steuer_info is None:
            details.append(
                (
                    "❓",
                    "Steuerfuss",
                    "nicht verfügbar",
                )
            )

        else:
            guenstig = (
                steuer_info.get(
                    "guenstig"
                )
            )

            if guenstig is None:
                details.append(
                    (
                        "❓",
                        "Steuerfuss",
                        "unbekannt",
                    )
                )

            else:
                beurteilbar += 1

                if guenstig:
                    punkte += 1
                    bestaetigte_wunschpunkte += 1
                    symbol = "✅"
                else:
                    symbol = "❌"

                details.append(
                    (
                        symbol,
                        "Steuerfuss",
                        (
                            f"{steuer_info['steuerfuss']:g} % "
                            f"– {steuer_info['vergleich']}"
                        ),
                    )
                )

    if beurteilbar:
        match = round(
            punkte
            / beurteilbar
            * 100
        )
    else:
        match = 0

    if gesamt_wunschpunkte:
        bestaetigt = round(
            bestaetigte_wunschpunkte
            / gesamt_wunschpunkte
            * 100
        )
    else:
        bestaetigt = 0

    offen = sum(
        1
        for symbol, _, _ in details
        if symbol == "❓"
    )

    steuerfuss = None

    if steuer_info:
        steuerfuss = (
            steuer_info.get(
                "steuerfuss"
            )
        )

    if gesamtpreis is None:
        status = "Preis offen"

    elif match >= 85:
        status = "sehr passend"

    elif match >= 70:
        status = "teilweise passend"

    else:
        status = "weniger passend"

    return {
        "gesamtpreis": gesamtpreis,
        "angegebene_miete": angegebene_miete,
        "nettomiete": netto,
        "nebenkosten": nk,
        "parkplatz_kosten": park_kosten,
        "steuerfuss": steuerfuss,
        "match": match,
        "bestaetigt": bestaetigt,
        "offen": offen,
        "details": details,
        "status": status,
    }


# =========================================================
# MERKLISTE
# =========================================================

def merkliste_speichern():
    try:
        daten = json.dumps(
            st.session_state.merkliste,
            ensure_ascii=False,
        )

        localS.setItem(
            MERKLISTE_KEY,
            daten,
        )

    except Exception:
        pass


# =========================================================
# SESSION
# =========================================================

if "suchergebnisse" not in st.session_state:
    st.session_state.suchergebnisse = []

if "merkliste" not in st.session_state:
    st.session_state.merkliste = []

if "merkliste_geladen" not in st.session_state:
    st.session_state.merkliste_geladen = False


if not st.session_state.merkliste_geladen:
    try:
        gespeichert = localS.getItem(
            MERKLISTE_KEY
        )

        if gespeichert:
            if isinstance(
                gespeichert,
                str,
            ):
                gespeichert = json.loads(
                    gespeichert
                )

            if isinstance(
                gespeichert,
                list,
            ):
                st.session_state.merkliste = (
                    gespeichert
                )

    except Exception:
        pass

    st.session_state.merkliste_geladen = True


# =========================================================
# 1. SUCHPROFIL
# =========================================================

st.header("📍 1. Suchprofil")

standard_gemeinden = [
    "Reinach BL",
    "Münchenstein",
    "Aesch BL",
    "Muttenz",
    "Liestal",
    "Frenkendorf",
    "Pratteln",
    "Arlesheim",
    "Binningen",
    "Allschwil",
]

gemeinden = st.multiselect(
    "Gemeinden / Orte",
    options=standard_gemeinden,
    default=[
        "Reinach BL",
        "Münchenstein",
        "Aesch BL",
        "Muttenz",
        "Liestal",
        "Frenkendorf",
    ],
)

weitere_orte = st.text_input(
    "Weitere Orte",
    placeholder=(
        "z.B. Oberwil BL, Therwil, Sissach"
    ),
)

col1, col2, col3 = st.columns(
    3
)

with col1:
    max_miete = st.number_input(
        "Max. Gesamtpreis inkl. NK + Parkplatz (CHF)",
        min_value=500,
        max_value=10000,
        value=1800,
        step=50,
    )

with col2:
    min_zimmer = st.selectbox(
        "Mindestens Zimmer",
        [
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
            3.5,
            4.0,
            4.5,
            5.0,
        ],
        index=3,
    )

with col3:
    max_zimmer = st.selectbox(
        "Maximal Zimmer",
        [
            1.5,
            2.0,
            2.5,
            3.0,
            3.5,
            4.0,
            4.5,
            5.0,
            5.5,
            6.0,
        ],
        index=4,
    )


st.subheader(
    "Wunschkriterien"
)

col1, col2 = st.columns(
    2
)

with col1:
    nicht_eg = st.checkbox(
        "Nicht im Erdgeschoss",
        True,
    )

    balkon = st.checkbox(
        "Balkon / Terrasse",
        True,
    )

    modern = st.checkbox(
        "Moderner Ausbau",
        True,
    )

    ruhig = st.checkbox(
        "Ruhige Wohnlage",
        True,
    )

with col2:
    parkplatz = st.checkbox(
        "Autoabstellplatz / Parkplatz",
        True,
    )

    dusche = st.checkbox(
        "Begehbare Dusche",
        True,
    )

    keine_badewanne = st.checkbox(
        "Keine Badewanne",
        True,
    )

    oev = st.checkbox(
        "Gute ÖV-Anbindung",
        True,
    )

    lift = st.checkbox("Lift vorhanden", True)

steuer = st.checkbox(
    "Niedriger Steuerfuss bevorzugt",
    True,
)


# =========================================================
# SUCHORTE
# =========================================================

suchorte = list(
    gemeinden
)

if weitere_orte.strip():
    for ort in weitere_orte.split(
        ","
    ):
        ort = ort.strip()

        if (
            ort
            and ort not in suchorte
        ):
            suchorte.append(
                ort
            )


# =========================================================
# SUCHE
# =========================================================

st.subheader(
    "🔎 Wohnungen automatisch suchen"
)

st.caption(
    "Nur ausgewählte Orte und Wohnungen innerhalb "
    "der bekannten Budgetgrenze werden angezeigt."
)


if st.button("🔎 Wohnungen suchen", type="primary", use_container_width=True):
    if not suchorte:
        st.warning("Bitte mindestens einen Ort auswählen.")
    else:
        st.session_state.suchergebnisse = []
        st.session_state.detail_quellen = {}
        st.session_state.detail_optionen = {}
        st.session_state.detail_diagnose = ""
        beginn = time.monotonic()
        try:
            with st.spinner("Schnelle Wohnungssuche ..."):
                webtreffer, cache_zeit = inserate_suchen(
                    tuple(suchorte), min_zimmer, max_zimmer)
                eindeutig = {t.get("url"): t for t in webtreffer if t.get("url")}
                quellen = list(eindeutig.values())
                for nr, t in enumerate(quellen, 1):
                    t["_interne_id"] = nr
                suche_ende = time.monotonic()
                analysen, parser_anzahl, ki_anzahl, fallback_anzahl = stufe1_kandidaten(
                    quellen, suchorte)
                parser_ende = time.monotonic()

                original_nach_id = {t["_interne_id"]: t for t in quellen}
                ergebnisse, bekannt = [], set()
                deduplikate = 0
                ausschluss = {"adresse": sum(not einzeltext_der_quelle(t) for t in quellen),
                             "ort": 0, "zimmer": 0, "budget": 0}
                for analyse in analysen:
                    if not analyse.get("einzelwohnung_sicher", False):
                        continue
                    try:
                        original = original_nach_id[int(analyse.get("treffer_id"))]
                    except (KeyError, ValueError, TypeError):
                        continue
                    if not belegter_einzelner_treffer(analyse, original):
                        ausschluss["adresse"] += 1
                        continue
                    zimmer = sichere_float_zahl(analyse.get("zimmer"))
                    strasse, wohnort = analyse.get("strasse"), analyse.get("ort")
                    if not brauchbare_strasse(strasse):
                        ausschluss["adresse"] += 1
                        continue
                    if not wohnort or not ort_ist_erlaubt(wohnort, suchorte):
                        ausschluss["ort"] += 1
                        continue
                    if zimmer is None or not min_zimmer <= zimmer <= max_zimmer:
                        ausschluss["zimmer"] += 1
                        continue
                    analyse = lokale_preiskontrolle(analyse, original)
                    analyse = preise_bereinigen(analyse)
                    if not ist_innerhalb_budget(analyse, max_miete, parkplatz):
                        ausschluss["budget"] += 1
                        continue
                    schluessel = wohnungs_schluessel(analyse)
                    if schluessel in bekannt:
                        deduplikate += 1
                        continue
                    bekannt.add(schluessel)
                    bewertung = bewerte_wohnung(
                        analyse, suchorte, max_miete, min_zimmer, max_zimmer,
                        nicht_eg, balkon, modern, ruhig, parkplatz, dusche,
                        keine_badewanne, oev, steuer, lift)
                    url = original.get("url", "")
                    ergebnisse.append({
                        "titel": analyse.get("titel") or "Mietwohnung",
                        "strasse": strasse, "ort": wohnort, "zimmer": zimmer,
                        "angegebene_miete": bewertung["angegebene_miete"],
                        "nettomiete": bewertung["nettomiete"],
                        "nebenkosten": bewertung["nebenkosten"],
                        "parkplatz_kosten": bewertung["parkplatz_kosten"],
                        "gesamtpreis": bewertung["gesamtpreis"],
                        "steuerfuss": bewertung["steuerfuss"],
                        "match": bewertung["match"],
                        "bestaetigt": bewertung["bestaetigt"],
                        "offen": bewertung["offen"],
                        "details": bewertung["details"],
                        "status": bewertung["status"],
                        "url": url, "quelle": quelle_aus_url(url),
                        "direktlink": ist_direktlink(url, strasse),
                        "detail_status": "Detailprüfung ausstehend",
                    })
                    st.session_state.detail_quellen[schluessel] = original
                    st.session_state.detail_optionen[schluessel] = dict(analyse)
                st.session_state.suchergebnisse = ergebnisse
                st.session_state.diagnose = (
                    f"Quellen {len(quellen)}; rohe Kandidaten {parser_anzahl}; "
                    f"Deduplikate {deduplikate}; Ausschlüsse: Adresse {ausschluss['adresse']}, "
                    f"Ort {ausschluss['ort']}, Zimmer {ausschluss['zimmer']}, "
                    f"Budget {ausschluss['budget']}; finale Treffer {len(ergebnisse)}; "
                    f"Web {suche_ende-beginn:.1f} s, Parser {parser_ende-suche_ende:.1f} s, "
                    f"gesamt {time.monotonic()-beginn:.1f} s; Cachealter "
                    f"{max(0, time.time()-cache_zeit):.0f} s (TTL 1200 s)"
                )
            st.success(f"{len(ergebnisse)} Wohnung(en) gefunden. Die Treffer sind jetzt sichtbar.")
        except Exception as exc:
            st.error(f"Suche nicht möglich: {exc}")

def einzelne_detailpruefung(wohnung, suchorte, max_miete, min_zimmer, max_zimmer,
                          nicht_eg, balkon, modern, ruhig, parkplatz, dusche,
                          keine_badewanne, oev, steuer, lift):
    beginn = time.monotonic()
    schluessel = wohnungs_schluessel(wohnung)
    analyse = dict(st.session_state.detail_optionen.get(schluessel, {}))
    if not wohnung.get("direktlink"):
        direkte_links_suchen([wohnung])
    text, status = detailseite_laden(wohnung)
    if not text:
        original = st.session_state.detail_quellen.get(schluessel, {})
        text = wohnungsspezifischer_text(wohnung, original)
        if text:
            status = "Einzelner Suchtreffer geprüft"
    geladen = time.monotonic()
    ki = 0
    if text:
        original = {"title": wohnung.get("titel", ""), "content": text, "raw_content": ""}
        analyse = lokale_preiskontrolle(analyse, original)
        analyse = lokale_textkontrolle(analyse, original)
        try:
            detail = detailanalyse(wohnung, text)
            for k, v in detail.items():
                if k in ("lift", "stockwerk", "rollstuhlgängig", "nicht_erdgeschoss",
                         "balkon", "parkplatz", "begehbare_dusche", "badewanne",
                         "modern", "ruhig", "gute_oev", "nettomiete", "nebenkosten",
                         "bruttomiete_ohne_parkplatz", "parkplatz_kosten") and v is not None and analyse.get(k) is None:
                    analyse[k] = v
            ki = 1
        except Exception:
            pass
    analyse = preise_bereinigen(analyse)
    bewertung = bewerte_wohnung(analyse, suchorte, max_miete, min_zimmer,
        max_zimmer, nicht_eg, balkon, modern, ruhig, parkplatz, dusche,
        keine_badewanne, oev, steuer, lift)
    for feld in ("angegebene_miete", "nettomiete", "nebenkosten", "parkplatz_kosten",
                 "gesamtpreis", "steuerfuss", "match", "bestaetigt", "offen", "details", "status"):
        wohnung[feld] = bewertung[feld]
    wohnung["detail_status"] = status
    wohnung["mietpreis_art"] = analyse.get("mietpreis_art")
    wohnung["stockwerk"] = analyse.get("stockwerk")
    wohnung["rollstuhlgängig"] = analyse.get("rollstuhlgängig")
    wohnung["budget_ueberschritten"] = not ist_innerhalb_budget(analyse, max_miete, parkplatz)
    st.session_state.detail_diagnose = (f"1 Inserat; Seite {geladen-beginn:.1f} s, "
        f"KI-Analysen {ki}, gesamt {time.monotonic()-beginn:.1f} s")
    return wohnung


if st.session_state.get("diagnose"):
    st.caption("Diagnose Stufe 1: " + st.session_state.diagnose)
if st.session_state.get("detail_diagnose"):
    st.caption("Diagnose Stufe 2: " + st.session_state.detail_diagnose)


# =========================================================
# 2. GEFUNDENE WOHNUNGEN
# =========================================================

st.divider()

st.header(
    "🏠 2. Gefundene Wohnungen"
)


if not st.session_state.suchergebnisse:
    st.info(
        "Noch keine passenden Wohnungen gefunden."
    )

else:
    st.write(
        f"**{len(st.session_state.suchergebnisse)} "
        "Wohnung(en) gefunden**"
    )

    for nummer, wohnung in enumerate(
        st.session_state.suchergebnisse,
        start=1,
    ):
        match = sichere_int_zahl(
            wohnung.get(
                "match"
            )
        )

        gesamtpreis = wohnung.get(
            "gesamtpreis"
        )

        angegebene_miete = wohnung.get(
            "angegebene_miete"
        )

        netto = wohnung.get(
            "nettomiete"
        )

        nk = wohnung.get(
            "nebenkosten"
        )

        park_kosten = wohnung.get(
            "parkplatz_kosten"
        )

        if gesamtpreis is None:
            symbol = "⚪"
            status_text = (
                "Gesamtpreis noch offen"
            )

        elif match >= 85:
            symbol = "🟢"
            status_text = (
                f"Match {match}%"
            )

        elif match >= 70:
            symbol = "🟡"
            status_text = (
                f"Match {match}%"
            )

        else:
            symbol = "🔴"
            status_text = (
                f"Match {match}%"
            )

        adresse = adresse_anzeigen(
            wohnung.get(
                "strasse"
            ),
            wohnung.get(
                "ort"
            ),
        )

        zimmer = wohnung.get(
            "zimmer"
        )

        if gesamtpreis is not None:
            preis_text = (
                f"Gesamt CHF "
                f"{gesamtpreis:,.0f}"
            )

        elif netto is not None and nk is not None:
            preis_text = (
                f"Netto CHF {netto:,.0f} + NK CHF {nk:,.0f} "
                f"= CHF {angegebene_miete:,.0f}; Parkplatz offen"
            )

        elif angegebene_miete is not None:
            preis_text = (
                f"Miete CHF "
                f"{angegebene_miete:,.0f} "
                f"+ offene Kosten"
            )

        else:
            preis_text = (
                "Preis offen"
            )

        kopf = (
            f"{symbol} {nummer}. "
            f"{adresse} – "
            f"{zimmer:g} Zimmer – "
            f"{preis_text}"
        )

        with st.expander(
            kopf
        ):
            col1, col2, col3 = (
                st.columns(
                    3
                )
            )

            with col1:
                if gesamtpreis is not None:
                    st.metric(
                        "Match",
                        f"{match}%",
                    )
                else:
                    st.metric(
                        "Match",
                        "noch offen",
                    )

            with col2:
                st.metric(
                    "Bestätigt",
                    (
                        f"{wohnung.get('bestaetigt', 0)}%"
                    ),
                )

            with col3:
                st.metric(
                    "Offene Punkte",
                    wohnung.get(
                        "offen",
                        0,
                    ),
                )

            st.write(
                f"**Status:** "
                f"{status_text}"
            )
            st.caption(wohnung.get("detail_status", "Detailprüfung ausstehend"))
            if st.button("🔍 Details prüfen", key=f"detail_{nummer}", use_container_width=True):
                einzelne_detailpruefung(wohnung, suchorte, max_miete, min_zimmer,
                    max_zimmer, nicht_eg, balkon, modern, ruhig, parkplatz, dusche,
                    keine_badewanne, oev, steuer, lift)
                if wohnung.get("budget_ueberschritten"):
                    st.session_state.suchergebnisse = [w for w in st.session_state.suchergebnisse
                        if w is not wohnung]
                    st.warning("Inserat überschreitet die Budgetgrenze und wurde entfernt.")
                st.rerun()

            st.write(
                f"**Strasse:** "
                f"{wohnung['strasse']}"
            )

            st.write(
                f"**Ort:** "
                f"{wohnung['ort']}"
            )

            st.write(
                f"**Zimmer:** "
                f"{zimmer:g}"
            )

            if wohnung.get("stockwerk") is not None:
                st.write(f"**Stockwerk:** {wohnung['stockwerk']}")
            if wohnung.get("rollstuhlgängig") is True:
                st.write("**Rollstuhlgängig:** Ja")

            # Preisaufschlüsselung
            st.write(
                "### 💰 Preis"
            )

            if netto is not None:
                st.write(
                    f"**Nettomiete:** "
                    f"CHF {netto:,.0f}"
                )

            if nk is not None:
                st.write(
                    f"**Nebenkosten:** "
                    f"CHF {nk:,.0f}"
                )

            if (
                angegebene_miete
                is not None
            ):
                st.write(
                    f"**Miete inkl. bekannten NK:** "
                    f"CHF "
                    f"{angegebene_miete:,.0f}"
                )

            if (
                park_kosten
                is not None
            ):
                st.write(
                    f"**Parkplatz:** "
                    f"CHF "
                    f"{park_kosten:,.0f}"
                )

            if gesamtpreis is not None:
                st.success(
                    f"Gesamt inkl. Parkplatz: "
                    f"CHF "
                    f"{gesamtpreis:,.0f}"
                )
            else:
                st.warning(
                    "Der endgültige Gesamtpreis "
                    "inkl. Parkplatz ist noch "
                    "nicht vollständig bekannt."
                )

            if (
                wohnung.get(
                    "steuerfuss"
                )
                is not None
            ):
                st.write(
                    f"**Steuerfuss:** "
                    f"{wohnung['steuerfuss']:g} %"
                )

            st.caption(
                f"Quelle: "
                f"{wohnung.get('quelle', '')}"
            )

            st.write(
                "**Kriterien:**"
            )

            for (
                detail_symbol,
                name,
                text,
            ) in wohnung.get(
                "details",
                [],
            ):
                st.write(
                    f"{detail_symbol} "
                    f"**{name}:** "
                    f"{text}"
                )

            link_text = (
                "🏠 Direktes Inserat öffnen"
                if wohnung.get("direktlink")
                else "🔎 Übersichtsseite / Quelle öffnen"
            )

            st.link_button(
                link_text,
                wohnung[
                    "url"
                ],
            )

            if st.button(
                "❤️ Wohnung merken",
                key=(
                    f"merken_{nummer}"
                ),
                use_container_width=True,
            ):
                vorhanden = any(
                    (
                        normalisiere_text(
                            x.get(
                                "strasse"
                            )
                        )
                        ==
                        normalisiere_text(
                            wohnung.get(
                                "strasse"
                            )
                        )
                        and
                        normalisiere_text(
                            x.get(
                                "ort"
                            )
                        )
                        ==
                        normalisiere_text(
                            wohnung.get(
                                "ort"
                            )
                        )
                    )
                    for x in
                    st.session_state.merkliste
                )

                if vorhanden:
                    st.warning(
                        "Diese Wohnung ist bereits "
                        "gespeichert."
                    )

                else:
                    st.session_state.merkliste.append(
                        {
                            "titel":
                                wohnung.get(
                                    "titel"
                                ),

                            "strasse":
                                wohnung.get(
                                    "strasse"
                                ),

                            "ort":
                                wohnung.get(
                                    "ort"
                                ),

                            "zimmer":
                                wohnung.get(
                                    "zimmer"
                                ),

                            "angegebene_miete":
                                wohnung.get(
                                    "angegebene_miete"
                                ),

                            "nettomiete":
                                wohnung.get(
                                    "nettomiete"
                                ),

                            "nebenkosten":
                                wohnung.get(
                                    "nebenkosten"
                                ),

                            "parkplatz_kosten":
                                wohnung.get(
                                    "parkplatz_kosten"
                                ),

                            "gesamtpreis":
                                wohnung.get(
                                    "gesamtpreis"
                                ),

                            "steuerfuss":
                                wohnung.get(
                                    "steuerfuss"
                                ),

                            "match":
                                wohnung.get(
                                    "match"
                                ),

                            "bestaetigt":
                                wohnung.get(
                                    "bestaetigt"
                                ),

                            "offen":
                                wohnung.get(
                                    "offen"
                                ),

                            "status":
                                wohnung.get(
                                    "status"
                                ),

                            "url":
                                wohnung.get(
                                    "url"
                                ),

                            "quelle":
                                wohnung.get(
                                    "quelle"
                                ),

                            "direktlink":
                                wohnung.get(
                                    "direktlink",
                                    False,
                                ),
                        }
                    )

                    merkliste_speichern()

                    st.success(
                        "❤️ Wohnung gespeichert."
                    )


# =========================================================
# 3. MERKLISTE
# =========================================================

st.divider()

st.header(
    "❤️ 3. Merkliste & Vergleich"
)

st.caption(
    "Die Merkliste wird lokal in diesem "
    "Browser gespeichert."
)


if not st.session_state.merkliste:
    st.info(
        "Noch keine Wohnung gespeichert."
    )

else:
    st.write(
        f"**{len(st.session_state.merkliste)} "
        "Wohnung(en) gespeichert**"
    )

    sortierung = st.selectbox(
        "Sortieren nach",
        [
            "Reihenfolge gespeichert",
            "Höchster Match",
            "Höchste Bestätigung",
            "Tiefster Gesamtpreis",
            "Tiefster Steuerfuss",
        ],
    )

    wohnungen_sortiert = list(
        st.session_state.merkliste
    )

    if sortierung == "Höchster Match":
        wohnungen_sortiert.sort(
            key=lambda x: (
                x.get(
                    "match"
                )
                or 0
            ),
            reverse=True,
        )

    elif (
        sortierung
        == "Höchste Bestätigung"
    ):
        wohnungen_sortiert.sort(
            key=lambda x: (
                x.get(
                    "bestaetigt"
                )
                or 0
            ),
            reverse=True,
        )

    elif (
        sortierung
        == "Tiefster Gesamtpreis"
    ):
        wohnungen_sortiert.sort(
            key=lambda x: (
                x.get(
                    "gesamtpreis"
                )
                if x.get(
                    "gesamtpreis"
                )
                is not None
                else float(
                    "inf"
                )
            )
        )

    elif (
        sortierung
        == "Tiefster Steuerfuss"
    ):
        wohnungen_sortiert.sort(
            key=lambda x: (
                x.get(
                    "steuerfuss"
                )
                if x.get(
                    "steuerfuss"
                )
                is not None
                else float(
                    "inf"
                )
            )
        )

    tabellen_daten = []

    for nummer, wohnung in enumerate(
        wohnungen_sortiert,
        start=1,
    ):
        gesamtpreis = wohnung.get(
            "gesamtpreis"
        )

        angegeben = wohnung.get(
            "angegebene_miete"
        )

        zimmer = wohnung.get(
            "zimmer"
        )

        steuerwert = wohnung.get(
            "steuerfuss"
        )

        if gesamtpreis is not None:
            preis_text = (
                f"CHF "
                f"{gesamtpreis:,.0f}"
            )

        elif angegeben is not None:
            preis_text = (
                f"CHF "
                f"{angegeben:,.0f} + ?"
            )

        else:
            preis_text = "❓"

        tabellen_daten.append(
            {
                "Nr.": nummer,

                "Strasse":
                    wohnung.get(
                        "strasse"
                    )
                    or "—",

                "Ort":
                    wohnung.get(
                        "ort",
                        "",
                    ),

                "Zimmer":
                    (
                        f"{zimmer:g}"
                        if zimmer
                        is not None
                        else "❓"
                    ),

                "Gesamtpreis":
                    preis_text,

                "Steuerfuss":
                    (
                        f"{steuerwert:g} %"
                        if steuerwert
                        is not None
                        else "❓"
                    ),

                "Match":
                    (
                        f"{wohnung.get('match', 0)}%"
                    ),

                "Bestätigt":
                    (
                        f"{wohnung.get('bestaetigt', 0)}%"
                    ),

                "Offen":
                    wohnung.get(
                        "offen",
                        0,
                    ),
            }
        )

    st.dataframe(
        tabellen_daten,
        use_container_width=True,
        hide_index=True,
    )

    st.subheader(
        "Gespeicherte Wohnungen"
    )

    for nummer, wohnung in enumerate(
        st.session_state.merkliste,
        start=1,
    ):
        adresse = adresse_anzeigen(
            wohnung.get(
                "strasse"
            ),
            wohnung.get(
                "ort"
            ),
        )

        titel = (
            adresse
            or wohnung.get(
                "titel"
            )
            or f"Wohnung {nummer}"
        )

        with st.expander(
            f"{nummer}. {titel}"
        ):
            if wohnung.get(
                "strasse"
            ):
                st.write(
                    f"**Strasse:** "
                    f"{wohnung['strasse']}"
                )

            if wohnung.get(
                "ort"
            ):
                st.write(
                    f"**Ort:** "
                    f"{wohnung['ort']}"
                )

            if wohnung.get(
                "zimmer"
            ) is not None:
                st.write(
                    f"**Zimmer:** "
                    f"{wohnung['zimmer']:g}"
                )

            if wohnung.get(
                "gesamtpreis"
            ) is not None:
                st.write(
                    f"**Gesamtpreis:** "
                    f"CHF "
                    f"{wohnung['gesamtpreis']:,.0f}"
                )
            else:
                st.write(
                    "**Gesamtpreis:** "
                    "❓ noch offen"
                )

            if wohnung.get(
                "url"
            ):
                gespeicherter_link_text = (
                    "🏠 Direktes Inserat öffnen"
                    if wohnung.get("direktlink")
                    else "🔎 Übersichtsseite / Quelle öffnen"
                )

                st.link_button(
                    gespeicherter_link_text,
                    wohnung[
                        "url"
                    ],
                    key=(
                        f"link_{nummer}"
                    ),
                )

            if st.button(
                "🗑️ Entfernen",
                key=(
                    f"delete_{nummer}"
                ),
            ):
                st.session_state.merkliste.pop(
                    nummer - 1
                )

                merkliste_speichern()

                st.rerun()

    if st.button(
        "🗑️ Ganze Merkliste löschen"
    ):
        st.session_state.merkliste = []

        merkliste_speichern()

        st.rerun()


st.divider()

st.caption(
    "Wohnungs-Finder Schweiz – Version 10.0.1 – automatische "
    "Websuche mit Tavily und KI-Auswertung. "
    "Nur ausgewählte Orte werden berücksichtigt. "
    "Sicher bekannte Wohnmiete über dem Maximalbudget "
    "wird ausgeschlossen. "
    "Angaben immer im Originalinserat überprüfen."
)
