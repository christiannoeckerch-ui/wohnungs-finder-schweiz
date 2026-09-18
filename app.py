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
    "deinen persönlichen Wunschkriterien bewerten."
)

st.divider()

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
wirklich vorhanden sind.

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

Für Ja/Nein-Felder verwende:
true = eindeutig vorhanden bzw. erfüllt
false = eindeutig nicht vorhanden bzw. nicht erfüllt
null = nicht sicher aus dem Inserat bestimmbar

Bei "nicht_erdgeschoss":
true = Wohnung liegt NICHT im Erdgeschoss.
false = Wohnung liegt im Erdgeschoss.

Bei "badewanne":
true = Badewanne vorhanden.
false = ausdrücklich keine Badewanne.

Geldbeträge nur als Zahl in CHF zurückgeben.

Inserat:

{text}
"""

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )

    output = response.output_text.strip()

    # Falls das Modell Markdown-Codeblöcke zurückgibt
    output = output.replace(
        "```json",
        "",
    ).replace(
        "```",
        "",
    ).strip()

    return json.loads(output)


def bool_zu_text(wert):
    if wert is True:
        return "Ja"

    if wert is False:
        return "Nein"

    return "Unbekannt"


def wert_oder_standard(wert, standard):
    if wert is None:
        return standard
    return wert


def pruefen(
    gewuenscht,
    wert,
    umgekehrt=False,
):
    if not gewuenscht:
        return None

    if wert == "Unbekannt":
        return None

    if umgekehrt:
        return wert == "Nein"

    return wert == "Ja"


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
    "Basel",
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

st.caption(
    "Standardprofil: erste Wohnung in der Region Basel. "
    "Alle Einstellungen können für andere Personen geändert werden."
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

else:
    st.warning(
        "Bitte mindestens einen Suchort auswählen."
    )


# =========================================================
# 3. KI-INSERATANALYSE
# =========================================================

st.divider()
st.header("🤖 3. Inserat mit KI prüfen")

st.write(
    "Link zu einem Wohnungsinserat einfügen. "
    "Der Agent versucht, die Angaben automatisch auszulesen."
)

inserat_url = st.text_input(
    "Link zum Originalinserat",
    placeholder="https://...",
)

if st.button(
    "🤖 Inserat automatisch analysieren",
    type="primary",
    use_container_width=True,
):

    if not inserat_url.strip():
        st.warning(
            "Bitte zuerst einen Inserat-Link eingeben."
        )

    else:
        try:
            with st.spinner(
                "Inserat wird geladen und mit KI analysiert..."
            ):
                inserat_text = lade_inserat(
                    inserat_url
                )

                if len(inserat_text) < 200:
                    raise ValueError(
                        "Auf der Seite konnte nicht genügend "
                        "Inserattext gelesen werden."
                    )

                analyse = ki_analyse(
                    inserat_text
                )

                st.session_state.analyse = analyse

            st.success(
                "Inserat wurde analysiert."
            )

        except requests.exceptions.RequestException:
            st.error(
                "Das Inserat konnte nicht automatisch "
                "von der Webseite geladen werden. "
                "Das Portal blockiert möglicherweise "
                "den automatischen Zugriff."
            )

        except json.JSONDecodeError:
            st.error(
                "Die KI-Antwort konnte nicht korrekt "
                "ausgewertet werden. Bitte nochmals versuchen."
            )

        except Exception as e:
            st.error(
                f"Analyse nicht möglich: {e}"
            )


analyse = st.session_state.analyse


# =========================================================
# 4. ERKANNTE DATEN / MANUELLE KORREKTUR
# =========================================================

st.divider()
st.header("📝 4. Erkannte Angaben prüfen")

st.write(
    "Die KI-Ergebnisse können hier kontrolliert "
    "und bei Bedarf korrigiert werden."
)

col1, col2, col3 = st.columns(3)

with col1:
    titel = st.text_input(
        "Wohnung / Titel",
        value=str(
            wert_oder_standard(
                analyse.get("titel"),
                "",
            )
        ),
    )

with col2:
    ort = st.text_input(
        "Ort",
        value=str(
            wert_oder_standard(
                analyse.get("ort"),
                "",
            )
        ),
    )

with col3:
    zimmer = st.number_input(
        "Zimmer",
        min_value=1.0,
        max_value=10.0,
        value=float(
            wert_oder_standard(
                analyse.get("zimmer"),
                3.0,
            )
        ),
        step=0.5,
    )


st.subheader("💰 Kosten")

col1, col2, col3 = st.columns(3)

with col1:
    nettomiete = st.number_input(
        "Nettomiete CHF",
        min_value=0,
        value=int(
            wert_oder_standard(
                analyse.get("nettomiete"),
                0,
            )
        ),
        step=50,
    )

with col2:
    nebenkosten = st.number_input(
        "Nebenkosten CHF",
        min_value=0,
        value=int(
            wert_oder_standard(
                analyse.get("nebenkosten"),
                0,
            )
        ),
        step=10,
    )

with col3:
    parkplatz_kosten = st.number_input(
        "Parkplatz CHF",
        min_value=0,
        value=int(
            wert_oder_standard(
                analyse.get("parkplatz_kosten"),
                0,
            )
        ),
        step=10,
    )


gesamtpreis = (
    nettomiete
    + nebenkosten
    + parkplatz_kosten
)

st.metric(
    "Gesamtpreis inkl. NK + Parkplatz",
    f"CHF {gesamtpreis:,.0f}",
)


optionen = [
    "Ja",
    "Nein",
    "Unbekannt",
]


def index_fuer(wert):
    text = bool_zu_text(wert)

    return optionen.index(text)


st.subheader("🏡 Ausstattung")

col1, col2 = st.columns(2)

with col1:
    i_nicht_eg = st.selectbox(
        "Nicht Erdgeschoss?",
        optionen,
        index=index_fuer(
            analyse.get(
                "nicht_erdgeschoss"
            )
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
            analyse.get(
                "begehbare_dusche"
            )
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


# Steuerfuss kann aus dem Inserat normalerweise
# nicht zuverlässig bestimmt werden.
i_steuer = st.selectbox(
    "Steuerlich attraktive Gemeinde?",
    optionen,
    index=2,
)


# =========================================================
# 5. MATCH
# =========================================================

st.divider()
st.header("⭐ 5. Match berechnen")

if st.button(
    "⭐ Wohnung bewerten",
    use_container_width=True,
):

    punkte = 0
    maximal = 0
    details = []

    # Preis besonders wichtig
    maximal += 3

    if gesamtpreis <= max_miete:
        punkte += 3

        details.append(
            (
                "✅",
                "Gesamtpreis",
                f"CHF {gesamtpreis:,.0f} – innerhalb Budget",
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

    # Zimmer
    maximal += 2

    if min_zimmer <= zimmer <= max_zimmer:
        punkte += 2

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

        if gewuenscht:
            maximal += 1

            ergebnis = pruefen(
                gewuenscht,
                wert,
                umgekehrt,
            )

            if ergebnis is True:
                punkte += 1

                details.append(
                    (
                        "✅",
                        name,
                        "erfüllt",
                    )
                )

            elif ergebnis is False:
                details.append(
                    (
                        "❌",
                        name,
                        "nicht erfüllt",
                    )
                )

            else:
                details.append(
                    (
                        "❓",
                        name,
                        "nicht angegeben",
                    )
                )


    if maximal > 0:
        score = round(
            punkte / maximal * 100
        )

    else:
        score = 0


    st.subheader("📊 Ergebnis")

    if score >= 85:
        st.success(
            f"🟢 Match: {score}% – "
            "sehr hohe Übereinstimmung"
        )

    elif score >= 70:
        st.warning(
            f"🟡 Match: {score}% – "
            "gute Übereinstimmung"
        )

    else:
        st.error(
            f"🔴 Match: {score}% – "
            "mehrere Kriterien fehlen"
        )


    if titel:
        st.write(
            f"**Wohnung:** {titel}"
        )

    if ort:
        st.write(
            f"**Ort:** {ort}"
        )

    st.write(
        f"**Gesamtpreis:** "
        f"CHF {gesamtpreis:,.0f}"
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


    if inserat_url:
        st.link_button(
            "🏠 Originalinserat öffnen",
            inserat_url,
        )


    if gesamtpreis > max_miete:
        st.error(
            f"Die Wohnung überschreitet das "
            f"Budget von CHF {max_miete:,.0f} "
            f"um CHF "
            f"{gesamtpreis - max_miete:,.0f}."
        )


    unbekannt = sum(
        1
        for symbol, _, _ in details
        if symbol == "❓"
    )

    if unbekannt:
        st.info(
            f"{unbekannt} Kriterium/Kriterien "
            "konnten noch nicht beurteilt werden."
        )


st.divider()

st.caption(
    "Wohnungs-Finder Schweiz – KI-Angaben immer mit "
    "dem Originalinserat und dem Mietvertrag überprüfen."
)
