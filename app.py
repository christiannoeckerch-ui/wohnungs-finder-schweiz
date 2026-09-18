import json
import re
from urllib.parse import quote_plus

import requests
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI


st.set_page_config(
    page_title="Wohnungs-Finder Schweiz",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 Wohnungs-Finder Schweiz")
st.write(
    "Wohnungen suchen, Inserate mit KI analysieren und nach "
    "persönlichen Wunschkriterien bewerten."
)

st.divider()


# =========================================================
# STEUERFÜSSE BL 2026
# Quelle: Amt für Daten und Statistik Basel-Landschaft
# Natürliche Personen: Einkommen/Vermögen in % Staatssteuer
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


# =========================================================
# HILFSFUNKTIONEN
# =========================================================

def lade_inserat(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120 Safari/537.36"
        )
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=15,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    for element in soup(
        ["script", "style", "noscript"]
    ):
        element.decompose()

    text = soup.get_text(
        separator=" ",
        strip=True,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text[:30000]


def ki_analyse(text):
    client = OpenAI(
        api_key=st.secrets["OPENAI_API_KEY"]
    )

    prompt = f"""
Du analysierst ein Schweizer Mietwohnungs-Inserat.

Extrahiere ausschließlich Informationen, die im Inserat
wirklich vorhanden oder eindeutig daraus ableitbar sind.

Wenn eine Information nicht sicher erkennbar ist,
verwende null.

Antworte ausschließlich mit gültigem JSON.

Folgende Felder werden benötigt:

{{
  "titel": null,
  "ort": null,
  "zimmer": null,
  "nettomiete": null,
  "nebenkosten": null,
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

REGELN:

Für Ja/Nein-Felder:

true = eindeutig vorhanden bzw. erfüllt
false = eindeutig nicht vorhanden bzw. nicht erfüllt
null = nicht sicher bestimmbar

Bei "nicht_erdgeschoss":
true = Wohnung liegt NICHT im Erdgeschoss
false = Wohnung liegt im Erdgeschoss
null = Stockwerk unbekannt

Bei "badewanne":
true = Badewanne vorhanden
false = ausdrücklich keine Badewanne
null = unbekannt

Bei "begehbare_dusche":
true nur, wenn eine bodenebene, begehbare oder
Walk-in-Dusche ausdrücklich erwähnt wird.

Bei "modern":
true, wenn moderner, neuwertiger, sanierter oder
hochwertiger Ausbau eindeutig beschrieben wird.

Bei "ruhig":
true nur, wenn ruhige Lage, ruhiges Quartier,
verkehrsarme Lage oder Vergleichbares erwähnt wird.

Bei "gute_oev":
true, wenn gute ÖV-Verbindungen oder nahe
Bus-, Tram- oder Bahnhaltestellen erwähnt werden.

Geldbeträge nur als Zahlen in CHF zurückgeben.

Fehlende Kosten niemals mit 0 ersetzen.
Wenn Nettomiete, Nebenkosten oder Parkplatzkosten
nicht angegeben sind, verwende null.

Inserattext:

{text}
"""

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )

    output = response.output_text.strip()

    output = (
        output
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    return json.loads(output)


def bool_zu_text(wert):
    if wert is True:
        return "Ja"

    if wert is False:
        return "Nein"

    return "Unbekannt"


def index_fuer(wert):
    optionen = [
        "Ja",
        "Nein",
        "Unbekannt",
    ]

    return optionen.index(
        bool_zu_text(wert)
    )


def sichere_float_zahl(
    wert,
    standard=3.0,
):
    try:
        if wert is None:
            return standard

        return float(wert)

    except (ValueError, TypeError):
        return standard


def pruefen(
    wert,
    umgekehrt=False,
):
    if wert == "Unbekannt":
        return None

    if umgekehrt:
        return wert == "Nein"

    return wert == "Ja"


def geld_lesen(text):
    text = text.strip()

    if not text:
        return None

    try:
        text = (
            text
            .replace("CHF", "")
            .replace("'", "")
            .replace("’", "")
            .replace(" ", "")
            .replace(",", ".")
        )

        return float(text)

    except ValueError:
        return None


def gemeinde_aus_text(text):
    """
    Erkennt eine BL-Gemeinde aus einem von der KI
    zurückgegebenen Ort oder einer Adresse.
    """

    if not text:
        return None

    text_klein = str(text).lower()

    for gemeinde in STEUERFUESSE_BL_2026:
        if gemeinde.lower() in text_klein:
            return gemeinde

    return None


def suchgemeinde_normalisieren(text):
    """
    Wandelt z.B. 'Reinach BL' in 'Reinach' um.
    """

    text = text.strip()

    if text.endswith(" BL"):
        text = text[:-3]

    return text.strip()


def steuervergleich(
    wohnort,
    suchorte,
):
    """
    Vergleicht den Steuerfuss der Wohnung mit den
    ausgewählten BL-Suchgemeinden.
    """

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

    for ort_name in suchorte:
        normalisiert = suchgemeinde_normalisieren(
            ort_name
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
            "vergleich": "kein Vergleich verfügbar",
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
# SESSION STATE
# =========================================================

if "analyse" not in st.session_state:
    st.session_state.analyse = {}


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
    placeholder="z.B. Oberwil BL, Therwil, Sissach",
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
            1.0, 1.5, 2.0, 2.5, 3.0,
            3.5, 4.0, 4.5, 5.0,
        ],
        index=3,
    )

with col3:
    max_zimmer = st.selectbox(
        "Maximal Zimmer",
        [
            1.5, 2.0, 2.5, 3.0, 3.5,
            4.0, 4.5, 5.0, 5.5, 6.0,
        ],
        index=4,
    )


st.subheader("Ausstattung")

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
# 2. WOHNUNGEN SUCHEN
# =========================================================

st.divider()
st.header("🌐 2. Wohnungen suchen")

alle_orte = list(gemeinden)

if weitere_orte.strip():
    alle_orte += [
        x.strip()
        for x in weitere_orte.split(",")
        if x.strip()
    ]

if alle_orte:

    suchorte = " ".join(alle_orte)

    suchtext = (
        f"Mietwohnung {suchorte} "
        f"{min_zimmer} bis {max_zimmer} Zimmer "
        f"CHF {max_miete} Balkon Parkplatz"
    )

    google_url = (
        "https://www.google.com/search?q="
        + quote_plus(suchtext)
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.link_button(
            "🔎 Comparis öffnen",
            "https://www.comparis.ch/immobilien/",
            use_container_width=True,
        )

    with col2:
        st.link_button(
            "🏠 Flatfox öffnen",
            "https://flatfox.ch/",
            use_container_width=True,
        )

    with col3:
        st.link_button(
            "🌐 Websuche starten",
            google_url,
            use_container_width=True,
        )


# =========================================================
# 3. INSERAT ANALYSIEREN
# =========================================================

st.divider()
st.header("🤖 3. Inserat mit KI prüfen")

inserat_url = st.text_input(
    "Link zum Originalinserat (optional)",
    placeholder="https://...",
)

inserat_text_manuell = st.text_area(
    "Inserattext einfügen",
    height=250,
    placeholder=(
        "Inserat öffnen, Beschreibung, Preis und "
        "weitere Angaben kopieren und hier einfügen."
    ),
)

st.caption(
    "Am besten den ganzen relevanten Inserattext inklusive "
    "Mietpreis, Nebenkosten und Parkplatz kopieren."
)


if st.button(
    "🤖 Inserat automatisch analysieren",
    type="primary",
    use_container_width=True,
):

    text_fuer_analyse = ""

    if len(
        inserat_text_manuell.strip()
    ) >= 50:

        text_fuer_analyse = (
            inserat_text_manuell.strip()
        )

    elif inserat_url.strip():

        try:
            text_fuer_analyse = lade_inserat(
                inserat_url.strip()
            )

        except Exception:
            st.warning(
                "Das Portal blockiert den automatischen "
                "Zugriff. Bitte den Inserattext kopieren."
            )

    else:
        st.warning(
            "Bitte Inserattext oder Inserat-Link angeben."
        )


    if text_fuer_analyse:

        try:

            with st.spinner(
                "KI analysiert das Wohnungsinserat..."
            ):

                analyse = ki_analyse(
                    text_fuer_analyse
                )

                st.session_state.analyse = analyse

            st.success(
                "✅ Inserat erfolgreich analysiert."
            )

        except Exception as e:

            st.error(
                f"KI-Analyse nicht möglich: {e}"
            )


analyse = st.session_state.analyse


# =========================================================
# 4. ERKANNTE ANGABEN
# =========================================================

st.divider()
st.header("📝 4. Erkannte Angaben prüfen")

if analyse:
    st.success(
        "Die KI hat Angaben erkannt. Bitte kurz mit "
        "dem Originalinserat vergleichen."
    )

else:
    st.info(
        "Noch kein Inserat analysiert."
    )


col1, col2, col3 = st.columns(3)

with col1:
    titel = st.text_input(
        "Wohnung / Titel",
        value=str(
            analyse.get("titel") or ""
        ),
    )

with col2:
    ort = st.text_input(
        "Ort",
        value=str(
            analyse.get("ort") or ""
        ),
    )

with col3:
    zimmer = st.number_input(
        "Zimmer",
        min_value=1.0,
        max_value=10.0,
        value=sichere_float_zahl(
            analyse.get("zimmer"),
            3.0,
        ),
        step=0.5,
    )


# =========================================================
# KOSTEN
# =========================================================

st.subheader("💰 Kosten")

netto_erkannt = analyse.get("nettomiete")
nk_erkannt = analyse.get("nebenkosten")
park_erkannt = analyse.get("parkplatz_kosten")

col1, col2, col3 = st.columns(3)

with col1:
    nettomiete_text = st.text_input(
        "Nettomiete CHF",
        value=(
            str(netto_erkannt)
            if netto_erkannt is not None
            else ""
        ),
        placeholder="unbekannt",
    )

with col2:
    nebenkosten_text = st.text_input(
        "Nebenkosten CHF",
        value=(
            str(nk_erkannt)
            if nk_erkannt is not None
            else ""
        ),
        placeholder="unbekannt",
    )

with col3:
    parkplatz_text = st.text_input(
        "Parkplatz CHF",
        value=(
            str(park_erkannt)
            if park_erkannt is not None
            else ""
        ),
        placeholder="unbekannt",
    )


nettomiete = geld_lesen(
    nettomiete_text
)

nebenkosten = geld_lesen(
    nebenkosten_text
)

parkplatz_kosten = geld_lesen(
    parkplatz_text
)


kosten_fehlen = []

if nettomiete is None:
    kosten_fehlen.append(
        "Nettomiete"
    )

if nebenkosten is None:
    kosten_fehlen.append(
        "Nebenkosten"
    )

if parkplatz and parkplatz_kosten is None:
    kosten_fehlen.append(
        "Parkplatzkosten"
    )


if not kosten_fehlen:

    gesamtpreis = (
        nettomiete
        + nebenkosten
        + (
            parkplatz_kosten
            if parkplatz_kosten is not None
            else 0
        )
    )

    st.metric(
        "Gesamtpreis inkl. NK + Parkplatz",
        f"CHF {gesamtpreis:,.0f}",
    )

else:

    gesamtpreis = None

    st.warning(
        "⚠️ Gesamtpreis noch nicht vollständig bekannt. "
        "Es fehlen: "
        + ", ".join(kosten_fehlen)
    )


# =========================================================
# AUSSTATTUNG
# =========================================================

optionen = [
    "Ja",
    "Nein",
    "Unbekannt",
]

st.subheader("🏡 Ausstattung")

col1, col2 = st.columns(2)

with col1:

    i_nicht_eg = st.selectbox(
        "Nicht Erdgeschoss?",
        optionen,
        index=index_fuer(
            analyse.get("nicht_erdgeschoss")
        ),
    )

    i_balkon = st.selectbox(
        "Balkon / Terrasse?",
        optionen,
        index=index_fuer(
            analyse.get("balkon")
        ),
    )

    i_modern = st.selectbox(
        "Moderner Ausbau?",
        optionen,
        index=index_fuer(
            analyse.get("modern")
        ),
    )

    i_ruhig = st.selectbox(
        "Ruhige Lage?",
        optionen,
        index=index_fuer(
            analyse.get("ruhig")
        ),
    )

with col2:

    i_parkplatz = st.selectbox(
        "Parkplatz vorhanden?",
        optionen,
        index=index_fuer(
            analyse.get("parkplatz")
        ),
    )

    i_dusche = st.selectbox(
        "Begehbare Dusche?",
        optionen,
        index=index_fuer(
            analyse.get("begehbare_dusche")
        ),
    )

    i_badewanne = st.selectbox(
        "Badewanne vorhanden?",
        optionen,
        index=index_fuer(
            analyse.get("badewanne")
        ),
    )

    i_oev = st.selectbox(
        "Gute ÖV-Anbindung?",
        optionen,
        index=index_fuer(
            analyse.get("gute_oev")
        ),
    )


# =========================================================
# STEUERFUSS AUTOMATISCH
# =========================================================

st.subheader("💰 Steuerfuss Gemeinde")

steuer_info = steuervergleich(
    ort,
    gemeinden,
)

if steuer_info:

    st.write(
        f"**{steuer_info['gemeinde']} BL:** "
        f"{steuer_info['steuerfuss']:g} % "
        "der Staatssteuer"
    )

    if "durchschnitt" in steuer_info:

        st.write(
            "Vergleich mit den ausgewählten "
            f"BL-Suchgemeinden: **"
            f"{steuer_info['vergleich']}**"
        )

        st.caption(
            "Durchschnitt der ausgewählten Gemeinden: "
            f"{steuer_info['durchschnitt']:.1f} %"
        )

    if steuer_info["guenstig"] is True:
        i_steuer = "Ja"

    elif steuer_info["guenstig"] is False:
        i_steuer = "Nein"

    else:
        i_steuer = "Unbekannt"

else:

    st.info(
        "Steuerfuss konnte für diese Gemeinde "
        "nicht automatisch bestimmt werden."
    )

    i_steuer = "Unbekannt"


# =========================================================
# 5. MATCH BERECHNEN
# =========================================================

st.divider()
st.header("⭐ 5. Match berechnen")


if st.button(
    "⭐ Wohnung bewerten",
    use_container_width=True,
):

    punkte = 0
    beurteilbar = 0
    gesamt_wunschpunkte = 0
    bestaetigte_wunschpunkte = 0
    details = []


    # PREIS - GEWICHT 3

    gesamt_wunschpunkte += 3

    if gesamtpreis is None:

        details.append(
            (
                "❓",
                "Gesamtpreis",
                "noch nicht vollständig bekannt",
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
                    f"CHF {gesamtpreis:,.0f} – "
                    "innerhalb Budget",
                )
            )

        else:

            details.append(
                (
                    "❌",
                    "Gesamtpreis",
                    f"CHF {gesamtpreis:,.0f} – "
                    "über Budget",
                )
            )


    # ZIMMER - GEWICHT 2

    gesamt_wunschpunkte += 2
    beurteilbar += 2

    if min_zimmer <= zimmer <= max_zimmer:

        punkte += 2
        bestaetigte_wunschpunkte += 2

        details.append(
            (
                "✅",
                "Zimmer",
                f"{zimmer}",
            )
        )

    else:

        details.append(
            (
                "❌",
                "Zimmer",
                f"{zimmer}",
            )
        )


    pruefungen = [
        (
            "Nicht Erdgeschoss",
            nicht_eg,
            i_nicht_eg,
            False,
        ),
        (
            "Balkon / Terrasse",
            balkon,
            i_balkon,
            False,
        ),
        (
            "Moderner Ausbau",
            modern,
            i_modern,
            False,
        ),
        (
            "Ruhige Lage",
            ruhig,
            i_ruhig,
            False,
        ),
        (
            "Parkplatz",
            parkplatz,
            i_parkplatz,
            False,
        ),
        (
            "Begehbare Dusche",
            dusche,
            i_dusche,
            False,
        ),
        (
            "Keine Badewanne",
            keine_badewanne,
            i_badewanne,
            True,
        ),
        (
            "ÖV-Anbindung",
            oev,
            i_oev,
            False,
        ),
        (
            "Steuerfuss",
            steuer,
            i_steuer,
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

        ergebnis = pruefen(
            wert,
            umgekehrt,
        )

        if ergebnis is None:

            details.append(
                (
                    "❓",
                    name,
                    "noch nicht beurteilbar",
                )
            )

        else:

            beurteilbar += 1

            if ergebnis:

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


    if beurteilbar > 0:

        match_beurteilbar = round(
            punkte / beurteilbar * 100
        )

    else:

        match_beurteilbar = 0


    if gesamt_wunschpunkte > 0:

        bestaetigungsgrad = round(
            bestaetigte_wunschpunkte
            / gesamt_wunschpunkte
            * 100
        )

    else:

        bestaetigungsgrad = 0


    unbekannt = sum(
        1
        for symbol, _, _ in details
        if symbol == "❓"
    )


    st.divider()
    st.header("📊 Ergebnis")


    if match_beurteilbar >= 85:

        st.success(
            f"🟢 Match der beurteilbaren Kriterien: "
            f"{match_beurteilbar}%"
        )

    elif match_beurteilbar >= 70:

        st.warning(
            f"🟡 Match der beurteilbaren Kriterien: "
            f"{match_beurteilbar}%"
        )

    else:

        st.error(
            f"🔴 Match der beurteilbaren Kriterien: "
            f"{match_beurteilbar}%"
        )


    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            "Beurteilbarer Match",
            f"{match_beurteilbar}%",
        )

    with col2:
        st.metric(
            "Gesamte Wunschliste bestätigt",
            f"{bestaetigungsgrad}%",
        )


    if unbekannt:

        st.info(
            f"ℹ️ {unbekannt} Kriterium/Kriterien sind "
            "noch unbekannt und wurden beim "
            "beurteilbaren Match nicht negativ gewertet."
        )


    if titel:
        st.write(
            f"**Wohnung:** {titel}"
        )

    if ort:
        st.write(
            f"**Ort:** {ort}"
        )

    if gesamtpreis is not None:
        st.write(
            f"**Gesamtpreis:** "
            f"CHF {gesamtpreis:,.0f}"
        )

    else:
        st.write(
            "**Gesamtpreis:** noch nicht vollständig bekannt"
        )


    if steuer_info:

        st.write(
            f"**Steuerfuss {steuer_info['gemeinde']}:** "
            f"{steuer_info['steuerfuss']:g} %"
        )


    st.subheader("Kriterien")

    for (
        symbol,
        name,
        text,
    ) in details:

        st.write(
            f"{symbol} **{name}:** {text}"
        )


    if (
        gesamtpreis is not None
        and gesamtpreis > max_miete
    ):

        st.error(
            f"Die Wohnung überschreitet das "
            f"Budget von CHF {max_miete:,.0f} "
            f"um CHF "
            f"{gesamtpreis - max_miete:,.0f}."
        )


    if inserat_url:

        st.link_button(
            "🏠 Originalinserat öffnen",
            inserat_url,
        )


st.divider()

st.caption(
    "Wohnungs-Finder Schweiz – Steuerfüsse BL: Stand 2026. "
    "KI-Angaben immer mit dem Originalinserat und dem "
    "Mietvertrag überprüfen."
)
