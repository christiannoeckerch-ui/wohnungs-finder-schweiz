import json
import re
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
            "TAVILY_API_KEY fehlt in den Streamlit Secrets."
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
# OFFENSICHTLICHE TREFFERLISTEN VORHER AUSSORTIEREN
# =========================================================

def ist_offensichtliche_trefferliste(
    titel,
    url,
):
    titel_klein = (
        str(titel)
        .lower()
        .strip()
    )

    # Beispiele:
    # "75 Wohnungen mieten in Aesch"
    # "11 Wohnungen in Münchenstein"

    muster = [
        r"^\d+\s+wohnungen",
        r"^\d+\s+mietwohnungen",
        r"wohnungen\s+mieten\s+in",
        r"wohnungen\s+in\s+.+\s+mieten",
        r"mietwohnungen\s+in",
        r"wohnungssuche",
        r"immobilien\s+in",
        r"trefferliste",
    ]

    for pattern in muster:
        if re.search(
            pattern,
            titel_klein,
        ):
            return True

    # Typische Suchseiten in URL
    url_klein = str(url).lower()

    url_muster = [
        "/trefferliste",
        "/search",
        "/suche",
    ]

    for pattern in url_muster:
        if pattern in url_klein:
            return True

    return False


# =========================================================
# EIN KI-AUFRUF FÜR ALLE TREFFER
# =========================================================

def ki_analysiere_alle_treffer(
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
        raw = (
            treffer.get("raw_content")
            or treffer.get("content")
            or ""
        )

        # Pro Treffer begrenzen
        raw = raw[:6000]

        kompakte_treffer.append(
            {
                "id": nummer,
                "titel": treffer.get(
                    "title",
                    "",
                ),
                "url": treffer.get(
                    "url",
                    "",
                ),
                "text": raw,
            }
        )

    daten_text = json.dumps(
        kompakte_treffer,
        ensure_ascii=False,
    )

    prompt = f"""
Du analysierst Web-Suchergebnisse für Schweizer
Mietwohnungen.

Analysiere ALLE gelieferten Treffer in einem Durchgang.

WICHTIG:

- Keine Angaben erfinden.
- Keine Daten verschiedener Wohnungen vermischen.
- Trefferlisten mit mehreren Wohnungen verwerfen.
- Nur konkrete einzelne Mietwohnungen zurückgeben.
- Wenn etwas unbekannt ist: null.
- Die URL muss exakt aus dem gelieferten Treffer stammen.

Antworte ausschließlich mit gültigem JSON
in dieser Form:

{{
  "wohnungen": [
    {{
      "treffer_id": 1,
      "ist_konkretes_inserat": true,
      "titel": null,
      "strasse": null,
      "ort": null,
      "zimmer": null,
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
      "gute_oev": null
    }}
  ]
}}

REGELN:

ist_konkretes_inserat:
Nur true, wenn der Treffer EIN bestimmtes Mietobjekt
beschreibt.

Eine Seite wie
"75 Wohnungen mieten in Aesch"
ist KEIN konkretes Inserat.

strasse:
Nur Strasse und Hausnummer.
Beispiel:
"Eichbergweg 47"

ort:
Möglichst PLZ + Gemeinde.
Beispiel:
"4147 Aesch BL"

zimmer:
Nur Zimmerzahl der konkreten Wohnung.

PREIS:

Wenn eine Bruttomiete inklusive Nebenkosten genannt
wird, schreibe sie in:

bruttomiete_ohne_parkplatz

Wenn Nettomiete und Nebenkosten getrennt genannt
werden, schreibe sie getrennt in:

nettomiete
nebenkosten

Parkplatzkosten ausschließlich in:

parkplatz_kosten

Fehlende Preise niemals mit 0 ersetzen.

JA/NEIN-FELDER:

true = eindeutig bestätigt
false = eindeutig verneint
null = unbekannt

nicht_erdgeschoss:
true bei 1., 2., 3. Stock usw.
false bei Erdgeschoss.

begehbare_dusche:
true nur bei ausdrücklich begehbarer,
bodenebener oder Walk-in-Dusche.

modern:
true bei ausdrücklich modernem,
renoviertem, saniertem oder neuwertigem Ausbau.

ruhig:
true nur bei ausdrücklich ruhiger Lage.

gute_oev:
true bei ausdrücklich guter ÖV-Anbindung
oder nahe gelegener Bus-, Tram- oder Bahnhaltestelle.

SUCHTREFFER:

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
# PREIS
# =========================================================

def gesamtpreis_berechnen(
    analyse,
    parkplatz_gewuenscht,
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

    park = sichere_float_zahl(
        analyse.get("parkplatz_kosten")
    )

    if brutto is not None:
        basis = brutto

    elif (
        netto is not None
        and nk is not None
    ):
        basis = netto + nk

    else:
        return None

    if parkplatz_gewuenscht:
        if park is None:
            return None

        return basis + park

    return basis


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

    zimmer = sichere_float_zahl(
        analyse.get("zimmer")
    )

    # PREIS = 3 Punkte
    gesamt_wunschpunkte += 3

    if gesamtpreis is None:
        details.append(
            (
                "❓",
                "Gesamtpreis",
                "nicht vollständig bekannt",
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
                    f"CHF {gesamtpreis:,.0f} – über Budget",
                )
            )

    # ZIMMER = 2 Punkte
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

    # STEUER
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

    if not kerndaten_vollstaendig:
        status = "unvollständig"

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
            1.0, 1.5, 2.0, 2.5,
            3.0, 3.5, 4.0, 4.5, 5.0,
        ],
        index=3,
    )

with col3:
    max_zimmer = st.selectbox(
        "Maximal Zimmer",
        [
            1.5, 2.0, 2.5, 3.0,
            3.5, 4.0, 4.5, 5.0,
            5.5, 6.0,
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
    "Eine schnelle gemeinsame Websuche für alle "
    "ausgewählten Orte. Danach prüft die KI nur "
    "die relevanten Treffer."
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
                "🔎 Suche aktuelle Wohnungsinserate ..."
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
                f"CHF {max_miete} "
                f"Adresse Balkon Parkplatz"
            )

            treffer = tavily_suche(
                suchtext,
                max_results=15,
            )

            fortschritt.progress(40)

            # -----------------------------------------
            # DUPLIKATE + TREFFERLISTEN ENTFERNEN
            # -----------------------------------------

            gefiltert = []
            urls = set()

            for item in treffer:
                url = item.get(
                    "url",
                    "",
                )

                titel = item.get(
                    "title",
                    "",
                )

                if not url:
                    continue

                if url in urls:
                    continue

                if ist_offensichtliche_trefferliste(
                    titel,
                    url,
                ):
                    continue

                urls.add(url)

                gefiltert.append(item)

            # Maximal 12 KI-relevante Treffer
            gefiltert = gefiltert[:12]

            if not gefiltert:
                fortschritt.empty()
                statusfeld.empty()

                st.warning(
                    "Keine konkreten Wohnungsinserate "
                    "gefunden."
                )

            else:
                statusfeld.write(
                    f"🤖 KI prüft {len(gefiltert)} "
                    "Suchtreffer gemeinsam ..."
                )

                fortschritt.progress(60)

                analysen = ki_analysiere_alle_treffer(
                    gefiltert
                )

                fortschritt.progress(85)

                ergebnisse = []

                for analyse in analysen:
                    if not analyse.get(
                        "ist_konkretes_inserat",
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
                        or treffer_id > len(
                            gefiltert
                        )
                    ):
                        continue

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
                            "gesamtpreis": bewertung[
                                "gesamtpreis"
                            ],
                            "steuerfuss": bewertung[
                                "steuerfuss"
                            ],
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

                ergebnisse.sort(
                    key=lambda x: (
                        x.get(
                            "kerndaten_vollstaendig",
                            False,
                        ),
                        x.get(
                            "bestaetigt",
                            0,
                        ),
                        x.get(
                            "match",
                            0,
                        ),
                    ),
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
                        f"✅ {len(ergebnisse)} konkrete "
                        "Wohnung(en) gefunden und geprüft."
                    )
                else:
                    st.warning(
                        "Die Suche lieferte Treffer, "
                        "aber keine eindeutigen einzelnen "
                        "Wohnungsinserate."
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

        if status == "unvollständig":
            symbol = "⚪"
            status_text = "Daten unvollständig"

        elif status == "über Budget":
            symbol = "🔴"
            status_text = "Über Budget"

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
            adresse = (
                wohnung.get("titel")
                or "Adresse unbekannt"
            )

        zimmer = wohnung.get(
            "zimmer"
        )

        preis = wohnung.get(
            "gesamtpreis"
        )

        zimmer_text = (
            f"{zimmer:g} Zimmer"
            if zimmer is not None
            else "Zimmer ❓"
        )

        preis_text = (
            f"CHF {preis:,.0f}"
            if preis is not None
            else "Preis ❓"
        )

        # Saubere Kopfzeile:
        # 1. Eichbergweg 47, Aesch – 2.5 Zimmer – CHF 1'700

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
                        "unvollständig",
                    )

            with col2:
                st.metric(
                    "Wunschliste bestätigt",
                    f"{wohnung.get('bestaetigt', 0)}%",
                )

            with col3:
                st.metric(
                    "Noch offen",
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
            else:
                st.write(
                    "**Zimmer:** ❓ unbekannt"
                )

            if preis is not None:
                st.write(
                    "**Gesamtpreis inkl. NK + Parkplatz:** "
                    f"CHF {preis:,.0f}"
                )

                if preis > max_miete:
                    st.error(
                        f"Budget von CHF "
                        f"{max_miete:,.0f} überschritten."
                    )
            else:
                st.warning(
                    "Gesamtpreis inkl. Nebenkosten "
                    "und Parkplatz noch unbekannt."
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
                "🏠 Originalinserat öffnen",
                wohnung["url"],
            )

            if st.button(
                "❤️ Wohnung merken",
                key=f"merken_{nummer}",
                use_container_width=True,
            ):
                vorhanden = any(
                    x.get("url")
                    == wohnung.get("url")
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
        preis = wohnung.get(
            "gesamtpreis"
        )

        zimmer = wohnung.get(
            "zimmer"
        )

        steuerwert = wohnung.get(
            "steuerfuss"
        )

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
                "Gesamtpreis": (
                    f"CHF {preis:,.0f}"
                    if preis is not None
                    else "❓ Unbekannt"
                ),
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
                "gesamtpreis"
            ) is not None:
                st.write(
                    f"**Gesamtpreis:** "
                    f"CHF "
                    f"{wohnung['gesamtpreis']:,.0f}"
                )
            else:
                st.write(
                    "**Gesamtpreis:** ❓ unbekannt"
                )

            if wohnung.get("url"):
                st.link_button(
                    "🏠 Originalinserat öffnen",
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
    "mit Tavily und KI-Auswertung. Angaben und "
    "Verfügbarkeit immer im Originalinserat überprüfen. "
    "Steuerfüsse BL: Stand 2026."
)
