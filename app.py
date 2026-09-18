import json
from urllib.parse import urlparse

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
    "Aktuelle Mietwohnungen automatisch suchen, "
    "mit KI prüfen und interessante Wohnungen vergleichen."
)

st.divider()


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


def gemeinde_aus_text(text):
    if not text:
        return None

    text_klein = str(text).lower()

    for gemeinde in STEUERFUESSE_BL_2026:
        if gemeinde.lower() in text_klein:
            return gemeinde

    return None


def normalisiere_gemeinde(text):
    text = str(text).strip()

    if text.endswith(" BL"):
        text = text[:-3]

    return text.strip()


def adresse_anzeigen(strasse, ort):
    teile = []

    if strasse:
        teile.append(str(strasse).strip())

    if ort:
        teile.append(str(ort).strip())

    return ", ".join(teile)


def wohnungs_schluessel(wohnung):
    strasse = str(
        wohnung.get("strasse") or ""
    ).lower().strip()

    ort = str(
        wohnung.get("ort") or ""
    ).lower().strip()

    zimmer = str(
        wohnung.get("zimmer") or ""
    ).lower().strip()

    preis = str(
        wohnung.get("angegebene_miete") or ""
    ).lower().strip()

    return (
        strasse,
        ort,
        zimmer,
        preis,
    )


# =========================================================
# STEUERFUSS
# =========================================================

def steuervergleich(wohnort, suchorte):
    gemeinde = gemeinde_aus_text(
        wohnort
    )

    if gemeinde is None:
        return None

    steuerfuss = STEUERFUESSE_BL_2026.get(
        gemeinde
    )

    if steuerfuss is None:
        return None

    vergleichswerte = []

    for ort in suchorte:
        normalisiert = normalisiere_gemeinde(
            ort
        )

        if normalisiert in STEUERFUESSE_BL_2026:
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

def tavily_suche(
    suchtext,
    max_results=15,
):
    api_key = st.secrets.get(
        "TAVILY_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY fehlt in den "
            "Streamlit Secrets."
        )

    payload = {
        "api_key": api_key,
        "query": suchtext,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": True,
    }

    response = requests.post(
        "https://api.tavily.com/search",
        json=payload,
        timeout=40,
    )

    response.raise_for_status()

    return response.json().get(
        "results",
        [],
    )


# =========================================================
# KI: AUS SUCHSEITEN EINZELNE WOHNUNGEN EXTRAHIEREN
# =========================================================

def ki_extrahiere_wohnungen(
    treffer_liste,
):
    client = OpenAI(
        api_key=st.secrets[
            "OPENAI_API_KEY"
        ]
    )

    kompakte_treffer = []

    for nummer, treffer in enumerate(
        treffer_liste,
        start=1,
    ):
        text = (
            treffer.get("raw_content")
            or treffer.get("content")
            or ""
        )

        # Genug Inhalt für mehrere Inserate,
        # aber trotzdem Token/Kosten begrenzen.
        text = text[:9000]

        kompakte_treffer.append(
            {
                "treffer_id": nummer,
                "titel": treffer.get(
                    "title",
                    "",
                ),
                "url": treffer.get(
                    "url",
                    "",
                ),
                "text": text,
            }
        )

    daten_text = json.dumps(
        kompakte_treffer,
        ensure_ascii=False,
    )

    prompt = f"""
Du analysierst Web-Suchergebnisse für Mietwohnungen
in der Schweiz.

WICHTIGE ÄNDERUNG:

Ein Webtreffer kann entweder

A) ein einzelnes Wohnungsinserat

oder

B) eine Übersichts-/Suchseite mit mehreren Wohnungen

sein.

Bei einer Übersichtsseite sollst du die EINZELNEN
Wohnungen, die im gelieferten Text eindeutig erkennbar
sind, separat extrahieren.

Beispiel:

Wenn eine Seite enthält:

1.5 Zimmer
Hauptstrasse 9
4147 Aesch
CHF 1'300

und

2.5 Zimmer
Eichbergweg 47
4147 Aesch
CHF 1'700

dann gib ZWEI Wohnungen zurück.

NIEMALS Daten verschiedener Wohnungen vermischen.

Antworte ausschließlich mit gültigem JSON:

{{
  "wohnungen": [
    {{
      "treffer_id": 1,
      "titel": null,
      "strasse": null,
      "ort": null,
      "zimmer": null,

      "angegebene_miete": null,
      "mietpreis_art": null,

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

1. Jede zurückgegebene Zeile muss genau EINE
   konkrete Wohnung darstellen.

2. Wenn eine Suchseite mehrere Wohnungen enthält,
   erzeuge mehrere Einträge.

3. Keine Angaben zwischen Wohnungen vermischen.

4. Wenn nicht klar ist, welche Adresse, Zimmerzahl
   und welcher Preis zusammengehören, diese Wohnung
   NICHT zurückgeben.

5. strasse:
   Nur Strasse und Hausnummer.

   Beispiel:
   "Eichbergweg 47"

6. ort:
   PLZ und Gemeinde, wenn vorhanden.

   Beispiel:
   "4147 Aesch BL"

7. zimmer:
   Nur die Zimmerzahl der konkreten Wohnung.

8. angegebene_miete:
   Der im Inserat sichtbar angegebene monatliche
   Mietpreis.

   Beispiel:
   1700

9. mietpreis_art:
   Verwende genau einen dieser Werte:

   "netto"
   "brutto"
   "inkl_nebenkosten"
   "unbekannt"

10. Wenn klar ist, dass der Preis Nettomiete ist:
    nettomiete = Preis

11. Wenn klar ist, dass der Preis bereits
    Nebenkosten enthält:
    bruttomiete_ohne_parkplatz = Preis

12. Wenn Nebenkosten separat genannt sind:
    nebenkosten = Betrag

13. Wenn Parkplatzkosten separat genannt sind:
    parkplatz_kosten = Betrag

14. Fehlende Geldbeträge niemals als 0 eintragen.

15. Nicht annehmen, dass ein sichtbarer Preis
    Nebenkosten oder Parkplatz enthält.

16. einzelwohnung_sicher:
    Nur true, wenn mindestens die Wohnung als
    einzelnes Objekt eindeutig erkennbar ist.

17. Bei Ja/Nein-Feldern:

    true = eindeutig bestätigt
    false = eindeutig verneint
    null = unbekannt

18. nicht_erdgeschoss:
    true bei 1., 2., 3. Stock usw.
    false bei Erdgeschoss.

19. balkon:
    true bei ausdrücklich Balkon oder Terrasse.

20. modern:
    true bei modern, renoviert, saniert,
    neuwertig oder hochwertigem Ausbau.

21. ruhig:
    true nur wenn ruhige Lage ausdrücklich
    erwähnt wird.

22. parkplatz:
    true wenn Parkplatz, Einstellplatz,
    Garage oder Autoabstellplatz angeboten wird.

23. begehbare_dusche:
    true nur bei begehbarer, bodenebener oder
    Walk-in-Dusche.

24. badewanne:
    true wenn Badewanne vorhanden.
    false nur wenn ausdrücklich keine vorhanden ist.

25. gute_oev:
    true bei ausdrücklich guter ÖV-Anbindung
    oder nahe gelegener Bus-, Tram- oder
    Bahnhaltestelle.

26. Der Titel einer Übersichtsseite wie
    "75 Wohnungen mieten in Aesch"
    darf NIEMALS als Titel einer einzelnen
    Wohnung übernommen werden.

27. Für den Titel einer einzelnen Wohnung
    verwende, falls vorhanden, den individuellen
    Inserattitel. Sonst null.

WEBTREFFER:

{daten_text}
"""

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )

    output = (
        response.output_text
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    daten = json.loads(output)

    return daten.get(
        "wohnungen",
        [],
    )


# =========================================================
# PREISE
# =========================================================

def bekannte_wohnkosten(
    analyse,
):
    brutto = sichere_float_zahl(
        analyse.get(
            "bruttomiete_ohne_parkplatz"
        )
    )

    netto = sichere_float_zahl(
        analyse.get("nettomiete")
    )

    nk = sichere_float_zahl(
        analyse.get("nebenkosten")
    )

    angegeben = sichere_float_zahl(
        analyse.get("angegebene_miete")
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
        and mietpreis_art
        in ["brutto", "inkl_nebenkosten"]
    ):
        return angegeben

    return None


def gesamtpreis_berechnen(
    analyse,
    parkplatz_gewuenscht,
):
    wohnkosten = bekannte_wohnkosten(
        analyse
    )

    if wohnkosten is None:
        return None

    if parkplatz_gewuenscht:
        park = sichere_float_zahl(
            analyse.get(
                "parkplatz_kosten"
            )
        )

        if park is None:
            return None

        return wohnkosten + park

    return wohnkosten


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
):
    punkte = 0
    beurteilbar = 0

    gesamt_wunschpunkte = 0
    bestaetigte_wunschpunkte = 0

    details = []

    gesamtpreis = gesamtpreis_berechnen(
        analyse,
        parkplatz,
    )

    angegebene_miete = sichere_float_zahl(
        analyse.get("angegebene_miete")
    )

    zimmer = sichere_float_zahl(
        analyse.get("zimmer")
    )

    # -----------------------------------------
    # PREIS
    # -----------------------------------------

    gesamt_wunschpunkte += 3

    if gesamtpreis is None:
        if angegebene_miete is not None:
            details.append(
                (
                    "❓",
                    "Gesamtpreis",
                    (
                        f"angegebene Miete "
                        f"CHF {angegebene_miete:,.0f}; "
                        "NK/Parkplatz noch nicht vollständig bekannt"
                    ),
                )
            )
        else:
            details.append(
                (
                    "❓",
                    "Gesamtpreis",
                    "noch nicht bekannt",
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

        else:
            details.append(
                (
                    "❌",
                    "Gesamtpreis",
                    (
                        f"CHF {gesamtpreis:,.0f} "
                        "– über Budget"
                    ),
                )
            )

    # -----------------------------------------
    # ZIMMER
    # -----------------------------------------

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

        else:
            details.append(
                (
                    "❌",
                    "Zimmer",
                    f"{zimmer:g}",
                )
            )

    # -----------------------------------------
    # WEITERE KRITERIEN
    # -----------------------------------------

    pruefungen = [
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
            analyse.get("balkon"),
            False,
        ),
        (
            "Moderner Ausbau",
            modern,
            analyse.get("modern"),
            False,
        ),
        (
            "Ruhige Lage",
            ruhig,
            analyse.get("ruhig"),
            False,
        ),
        (
            "Parkplatz",
            parkplatz,
            analyse.get("parkplatz"),
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
            analyse.get("badewanne"),
            True,
        ),
        (
            "ÖV-Anbindung",
            oev,
            analyse.get("gute_oev"),
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

    # -----------------------------------------
    # STEUER
    # -----------------------------------------

    steuer_info = steuervergleich(
        analyse.get("ort"),
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
            guenstig = steuer_info.get(
                "guenstig"
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

    # -----------------------------------------
    # PROZENTE
    # -----------------------------------------

    if beurteilbar:
        match = round(
            punkte / beurteilbar * 100
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
        steuerfuss = steuer_info.get(
            "steuerfuss"
        )

    kerndaten_vollstaendig = (
        gesamtpreis is not None
        and zimmer is not None
    )

    if zimmer is None:
        status = "unvollständig"

    elif not (
        min_zimmer
        <= zimmer
        <= max_zimmer
    ):
        status = "Zimmer ausserhalb"

    elif gesamtpreis is None:
        status = "Preis offen"

    elif gesamtpreis > max_miete:
        status = "über Budget"

    elif match >= 85:
        status = "sehr passend"

    elif match >= 70:
        status = "teilweise passend"

    else:
        status = "weniger passend"

    return {
        "gesamtpreis": gesamtpreis,
        "angegebene_miete": (
            angegebene_miete
        ),
        "steuerfuss": steuerfuss,
        "match": match,
        "bestaetigt": bestaetigt,
        "offen": offen,
        "details": details,
        "status": status,
        "kerndaten_vollstaendig": (
            kerndaten_vollstaendig
        ),
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


# =========================================================
# MERKLISTE LADEN
# =========================================================

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

col1, col2, col3 = st.columns(3)

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

st.subheader("Wunschkriterien")

col1, col2 = st.columns(2)

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

steuer = st.checkbox(
    "Niedriger Steuerfuss bevorzugt",
    True,
)


# =========================================================
# SUCHORTE
# =========================================================

suchorte = list(gemeinden)

if weitere_orte.strip():
    for ort in weitere_orte.split(","):
        ort = ort.strip()

        if ort and ort not in suchorte:
            suchorte.append(ort)


# =========================================================
# AUTOMATISCHE SUCHE
# =========================================================

st.subheader("🔎 Wohnungen automatisch suchen")

st.caption(
    "Der Agent durchsucht aktuelle Immobilienseiten "
    "und kann auch einzelne Wohnungen aus "
    "Trefferlisten herauslesen."
)


if st.button(
    "🔎 Wohnungen suchen",
    type="primary",
    use_container_width=True,
):
    if not suchorte:
        st.warning(
            "Bitte mindestens einen Ort auswählen."
        )

    else:
        st.session_state.suchergebnisse = []

        statusfeld = st.empty()
        fortschritt = st.progress(10)

        try:
            statusfeld.write(
                "🔎 Suche aktuelle Wohnungen ..."
            )

            ort_text = " OR ".join(
                f'"{ort}"'
                for ort in suchorte
            )

            suchtext = (
                f"Mietwohnung Schweiz "
                f"({ort_text}) "
                f"{min_zimmer:g} bis "
                f"{max_zimmer:g} Zimmer "
                f"Miete CHF "
                f"Balkon Parkplatz"
            )

            # Nur ein Tavily-Aufruf
            treffer = tavily_suche(
                suchtext,
                max_results=15,
            )

            fortschritt.progress(45)

            # Duplikate entfernen,
            # aber Suchseiten NICHT mehr löschen.
            gefiltert = []
            urls = set()

            for item in treffer:
                url = item.get(
                    "url",
                    "",
                )

                if not url:
                    continue

                if url in urls:
                    continue

                urls.add(url)
                gefiltert.append(item)

            # Geschwindigkeit/Kosten begrenzen
            gefiltert = gefiltert[:12]

            if not gefiltert:
                fortschritt.empty()
                statusfeld.empty()

                st.warning(
                    "Keine Suchtreffer gefunden."
                )

            else:
                statusfeld.write(
                    "🤖 KI liest die gefundenen "
                    "Wohnungsseiten ..."
                )

                fortschritt.progress(60)

                # Nur EIN OpenAI-Aufruf
                analysen = ki_extrahiere_wohnungen(
                    gefiltert
                )

                fortschritt.progress(85)

                ergebnisse = []
                bekannte_wohnungen = set()

                for analyse in analysen:
                    if not analyse.get(
                        "einzelwohnung_sicher",
                        False,
                    ):
                        continue

                    treffer_id = analyse.get(
                        "treffer_id"
                    )

                    try:
                        treffer_id = int(
                            treffer_id
                        )

                    except Exception:
                        continue

                    if (
                        treffer_id < 1
                        or treffer_id
                        > len(gefiltert)
                    ):
                        continue

                    # Eine Wohnung muss mindestens
                    # Adresse/Ort und Zimmerzahl haben.
                    if (
                        not analyse.get("strasse")
                        and not analyse.get("ort")
                    ):
                        continue

                    if sichere_float_zahl(
                        analyse.get("zimmer")
                    ) is None:
                        continue

                    schluessel = wohnungs_schluessel(
                        analyse
                    )

                    if schluessel in bekannte_wohnungen:
                        continue

                    bekannte_wohnungen.add(
                        schluessel
                    )

                    original = gefiltert[
                        treffer_id - 1
                    ]

                    bewertung = bewerte_wohnung(
                        analyse=analyse,
                        suchorte=suchorte,
                        max_miete=max_miete,
                        min_zimmer=min_zimmer,
                        max_zimmer=max_zimmer,
                        nicht_eg=nicht_eg,
                        balkon=balkon,
                        modern=modern,
                        ruhig=ruhig,
                        parkplatz=parkplatz,
                        dusche=dusche,
                        keine_badewanne=(
                            keine_badewanne
                        ),
                        oev=oev,
                        steuer=steuer,
                    )

                    ergebnisse.append(
                        {
                            "titel": (
                                analyse.get("titel")
                                or "Mietwohnung"
                            ),
                            "strasse": analyse.get(
                                "strasse"
                            ),
                            "ort": analyse.get(
                                "ort"
                            ),
                            "zimmer": sichere_float_zahl(
                                analyse.get("zimmer")
                            ),
                            "angegebene_miete": (
                                bewertung[
                                    "angegebene_miete"
                                ]
                            ),
                            "gesamtpreis": (
                                bewertung[
                                    "gesamtpreis"
                                ]
                            ),
                            "steuerfuss": (
                                bewertung[
                                    "steuerfuss"
                                ]
                            ),
                            "match": bewertung[
                                "match"
                            ],
                            "bestaetigt": bewertung[
                                "bestaetigt"
                            ],
                            "offen": bewertung[
                                "offen"
                            ],
                            "details": bewertung[
                                "details"
                            ],
                            "status": bewertung[
                                "status"
                            ],
                            "kerndaten_vollstaendig": (
                                bewertung[
                                    "kerndaten_vollstaendig"
                                ]
                            ),
                            "url": original.get(
                                "url"
                            ),
                            "quelle": quelle_aus_url(
                                original.get(
                                    "url",
                                    "",
                                )
                            ),
                        }
                    )

                # Zuerst Wohnungen innerhalb
                # des gewünschten Zimmerbereichs.
                def sortierwert(x):
                    zimmer = x.get("zimmer")

                    zimmer_passend = (
                        zimmer is not None
                        and min_zimmer
                        <= zimmer
                        <= max_zimmer
                    )

                    preis_bekannt = (
                        x.get("gesamtpreis")
                        is not None
                    )

                    return (
                        zimmer_passend,
                        preis_bekannt,
                        x.get(
                            "bestaetigt",
                            0,
                        ),
                    )

                ergebnisse.sort(
                    key=sortierwert,
                    reverse=True,
                )

                st.session_state.suchergebnisse = (
                    ergebnisse
                )

                fortschritt.progress(100)
                fortschritt.empty()
                statusfeld.empty()

                if ergebnisse:
                    st.success(
                        f"✅ {len(ergebnisse)} einzelne "
                        "Wohnung(en) gefunden."
                    )

                else:
                    st.warning(
                        "Suchseiten wurden gefunden, "
                        "aber daraus konnten keine "
                        "eindeutigen einzelnen Wohnungen "
                        "ausgelesen werden."
                    )

        except requests.HTTPError as e:
            fortschritt.empty()
            statusfeld.empty()

            st.error(
                f"Fehler bei der Websuche: {e}"
            )

        except Exception as e:
            fortschritt.empty()
            statusfeld.empty()

            st.error(
                f"Suche nicht möglich: {e}"
            )


# =========================================================
# 2. GEFUNDENE WOHNUNGEN
# =========================================================

st.divider()
st.header("🏠 2. Gefundene Wohnungen")


if not st.session_state.suchergebnisse:
    st.info(
        "Noch keine Wohnungen gesucht."
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
            wohnung.get("match")
        )

        status = wohnung.get(
            "status",
            "unvollständig",
        )

        if status == "Preis offen":
            symbol = "⚪"
            status_text = "Preis noch offen"

        elif status == "Zimmer ausserhalb":
            symbol = "🔴"
            status_text = "Zimmer ausserhalb"

        elif status == "über Budget":
            symbol = "🔴"
            status_text = "Über Budget"

        elif status == "unvollständig":
            symbol = "⚪"
            status_text = "Daten unvollständig"

        elif match >= 85:
            symbol = "🟢"
            status_text = f"Match {match}%"

        elif match >= 70:
            symbol = "🟡"
            status_text = f"Match {match}%"

        else:
            symbol = "🔴"
            status_text = f"Match {match}%"

        adresse = adresse_anzeigen(
            wohnung.get("strasse"),
            wohnung.get("ort"),
        )

        if not adresse:
            adresse = "Adresse unbekannt"

        zimmer = wohnung.get("zimmer")

        zimmer_text = (
            f"{zimmer:g} Zimmer"
            if zimmer is not None
            else "Zimmer ❓"
        )

        gesamtpreis = wohnung.get(
            "gesamtpreis"
        )

        angegebene_miete = wohnung.get(
            "angegebene_miete"
        )

        if gesamtpreis is not None:
            preis_text = (
                f"Gesamt CHF "
                f"{gesamtpreis:,.0f}"
            )

        elif angegebene_miete is not None:
            preis_text = (
                f"Miete CHF "
                f"{angegebene_miete:,.0f} + offene Kosten"
            )

        else:
            preis_text = "Preis ❓"

        kopf = (
            f"{symbol} {nummer}. "
            f"{adresse} – "
            f"{zimmer_text} – "
            f"{preis_text}"
        )

        with st.expander(kopf):
            col1, col2, col3 = st.columns(3)

            with col1:
                if wohnung.get(
                    "kerndaten_vollstaendig"
                ):
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
                    f"{wohnung.get('bestaetigt', 0)}%",
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
                f"**Status:** {status_text}"
            )

            if wohnung.get("strasse"):
                st.write(
                    f"**Strasse:** "
                    f"{wohnung['strasse']}"
                )

            if wohnung.get("ort"):
                st.write(
                    f"**Ort:** "
                    f"{wohnung['ort']}"
                )

            if zimmer is not None:
                st.write(
                    f"**Zimmer:** {zimmer:g}"
                )

            if angegebene_miete is not None:
                st.write(
                    "**Im Inserat angegebene Miete:** "
                    f"CHF {angegebene_miete:,.0f}"
                )

            if gesamtpreis is not None:
                st.write(
                    "**Gesamtpreis inkl. bekannten "
                    "NK + Parkplatz:** "
                    f"CHF {gesamtpreis:,.0f}"
                )

            else:
                st.warning(
                    "Der endgültige Gesamtpreis inkl. "
                    "Nebenkosten und Parkplatz ist noch "
                    "nicht vollständig bekannt."
                )

            if wohnung.get(
                "steuerfuss"
            ) is not None:
                st.write(
                    f"**Steuerfuss:** "
                    f"{wohnung['steuerfuss']:g} %"
                )

            st.caption(
                f"Quelle: "
                f"{wohnung.get('quelle', '')}"
            )

            st.write("**Kriterien:**")

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
                    f"**{name}:** {text}"
                )

            st.link_button(
                "🏠 Quelle / Inserat öffnen",
                wohnung["url"],
            )

            if st.button(
                "❤️ Wohnung merken",
                key=f"merken_{nummer}",
                use_container_width=True,
            ):
                vorhanden = any(
                    (
                        x.get("strasse")
                        == wohnung.get("strasse")
                        and x.get("ort")
                        == wohnung.get("ort")
                        and x.get("zimmer")
                        == wohnung.get("zimmer")
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
                            "titel": wohnung.get(
                                "titel"
                            ),
                            "strasse": wohnung.get(
                                "strasse"
                            ),
                            "ort": wohnung.get(
                                "ort"
                            ),
                            "zimmer": wohnung.get(
                                "zimmer"
                            ),
                            "angegebene_miete": (
                                wohnung.get(
                                    "angegebene_miete"
                                )
                            ),
                            "gesamtpreis": wohnung.get(
                                "gesamtpreis"
                            ),
                            "steuerfuss": wohnung.get(
                                "steuerfuss"
                            ),
                            "match": wohnung.get(
                                "match"
                            ),
                            "bestaetigt": wohnung.get(
                                "bestaetigt"
                            ),
                            "offen": wohnung.get(
                                "offen"
                            ),
                            "status": wohnung.get(
                                "status"
                            ),
                            "url": wohnung.get(
                                "url"
                            ),
                            "quelle": wohnung.get(
                                "quelle"
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
st.header("❤️ 3. Merkliste & Vergleich")

st.caption(
    "Die Merkliste wird lokal in diesem Browser gespeichert."
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
            key=lambda x: x.get(
                "match"
            ) or 0,
            reverse=True,
        )

    elif sortierung == "Höchste Bestätigung":
        wohnungen_sortiert.sort(
            key=lambda x: x.get(
                "bestaetigt"
            ) or 0,
            reverse=True,
        )

    elif sortierung == "Tiefster Gesamtpreis":
        wohnungen_sortiert.sort(
            key=lambda x: (
                x.get("gesamtpreis")
                if x.get("gesamtpreis")
                is not None
                else float("inf")
            )
        )

    elif sortierung == "Tiefster Steuerfuss":
        wohnungen_sortiert.sort(
            key=lambda x: (
                x.get("steuerfuss")
                if x.get("steuerfuss")
                is not None
                else float("inf")
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

        angegebene_miete = wohnung.get(
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
                f"CHF {gesamtpreis:,.0f}"
            )

        elif angegebene_miete is not None:
            preis_text = (
                f"CHF {angegebene_miete:,.0f} + ?"
            )

        else:
            preis_text = "❓"

        tabellen_daten.append(
            {
                "Nr.": nummer,
                "Strasse": (
                    wohnung.get("strasse")
                    or "—"
                ),
                "Ort": wohnung.get(
                    "ort",
                    "",
                ),
                "Zimmer": (
                    f"{zimmer:g}"
                    if zimmer is not None
                    else "❓"
                ),
                "Preis": preis_text,
                "Steuerfuss": (
                    f"{steuerwert:g} %"
                    if steuerwert is not None
                    else "❓"
                ),
                "Match": (
                    f"{wohnung.get('match', 0)}%"
                ),
                "Bestätigt": (
                    f"{wohnung.get('bestaetigt', 0)}%"
                ),
                "Offen": wohnung.get(
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
            wohnung.get("strasse"),
            wohnung.get("ort"),
        )

        titel = (
            adresse
            or wohnung.get("titel")
            or f"Wohnung {nummer}"
        )

        with st.expander(
            f"{nummer}. {titel}"
        ):
            if wohnung.get("strasse"):
                st.write(
                    f"**Strasse:** "
                    f"{wohnung['strasse']}"
                )

            if wohnung.get("ort"):
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
                "angegebene_miete"
            ) is not None:
                st.write(
                    "**Angegebene Miete:** "
                    f"CHF "
                    f"{wohnung['angegebene_miete']:,.0f}"
                )

            if wohnung.get(
                "gesamtpreis"
            ) is not None:
                st.write(
                    "**Gesamtpreis:** "
                    f"CHF "
                    f"{wohnung['gesamtpreis']:,.0f}"
                )

            else:
                st.write(
                    "**Gesamtpreis:** ❓ "
                    "noch nicht vollständig bekannt"
                )

            if wohnung.get("url"):
                st.link_button(
                    "🏠 Quelle / Inserat öffnen",
                    wohnung["url"],
                    key=f"link_{nummer}",
                )

            if st.button(
                "🗑️ Entfernen",
                key=f"delete_{nummer}",
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
    "Wohnungs-Finder Schweiz – automatische Websuche "
    "mit Tavily und KI-Auswertung. Preise, Nebenkosten, "
    "Parkplatzkosten und Verfügbarkeit immer im "
    "Originalinserat überprüfen. Steuerfüsse BL: Stand 2026."
)
