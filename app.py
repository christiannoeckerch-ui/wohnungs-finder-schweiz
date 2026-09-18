import streamlit as st
from urllib.parse import quote_plus

st.set_page_config(
    page_title="Wohnungs-Finder Schweiz",
    page_icon="🏠",
    layout="wide"
)

st.title("🏠 Wohnungs-Finder Schweiz")
st.write(
    "Wohnungen suchen, vergleichen und nach deinen persönlichen "
    "Wunschkriterien bewerten."
)

st.divider()

# =========================================================
# SUCHPROFIL
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
    placeholder="z.B. Oberwil BL, Therwil, Sissach"
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
        [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
        index=3,
    )

with col3:
    max_zimmer = st.selectbox(
        "Maximal Zimmer",
        [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0],
        index=4,
    )

st.subheader("Ausstattung")

col1, col2 = st.columns(2)

with col1:
    nicht_eg = st.checkbox("Nicht im Erdgeschoss", True)
    balkon = st.checkbox("Balkon / Terrasse", True)
    modern = st.checkbox("Moderner Ausbau", True)
    ruhig = st.checkbox("Ruhige Wohnlage", True)

with col2:
    parkplatz = st.checkbox("Autoabstellplatz / Parkplatz", True)
    dusche = st.checkbox("Begehbare Dusche", True)
    keine_badewanne = st.checkbox("Keine Badewanne", True)
    oev = st.checkbox("Gute ÖV-Anbindung", True)

steuer = st.checkbox(
    "Niedriger Steuerfuss bevorzugt",
    True
)

st.caption(
    "Standardprofil: erste Wohnung in der Region Basel. "
    "Alle Einstellungen können für andere Personen geändert werden."
)

# =========================================================
# SUCHPORTALE
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
        f"{min_zimmer} {max_zimmer} Zimmer "
        f"CHF {max_miete} Balkon Parkplatz Dusche"
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
            use_container_width=True
        )

    with col2:
        st.link_button(
            "🏠 Flatfox öffnen",
            "https://flatfox.ch/",
            use_container_width=True
        )

    with col3:
        st.link_button(
            "🌐 Websuche starten",
            google_url,
            use_container_width=True
        )

else:
    st.warning("Bitte mindestens einen Suchort auswählen.")

# =========================================================
# INSERAT PRÜFEN
# =========================================================

st.divider()
st.header("🤖 3. Inserat prüfen")

st.write(
    "Hier kannst du die Angaben einer gefundenen Wohnung "
    "eintragen. Der Agent berechnet daraus einen Match-Score."
)

inserat_url = st.text_input(
    "Link zum Originalinserat",
    placeholder="https://..."
)

col1, col2, col3 = st.columns(3)

with col1:
    titel = st.text_input(
        "Wohnung / Titel",
        placeholder="z.B. moderne 3½-Zimmer-Wohnung"
    )

with col2:
    ort = st.text_input(
        "Ort",
        placeholder="z.B. Reinach BL"
    )

with col3:
    zimmer = st.number_input(
        "Zimmer",
        min_value=1.0,
        max_value=10.0,
        value=3.0,
        step=0.5
    )

st.subheader("💰 Kosten")

col1, col2, col3 = st.columns(3)

with col1:
    nettomiete = st.number_input(
        "Nettomiete CHF",
        min_value=0,
        value=1500,
        step=50
    )

with col2:
    nebenkosten = st.number_input(
        "Nebenkosten CHF",
        min_value=0,
        value=200,
        step=10
    )

with col3:
    parkplatz_kosten = st.number_input(
        "Parkplatz CHF",
        min_value=0,
        value=0,
        step=10
    )

gesamtpreis = nettomiete + nebenkosten + parkplatz_kosten

st.metric(
    "Gesamtpreis inkl. NK + Parkplatz",
    f"CHF {gesamtpreis:,.0f}"
)

st.subheader("🏡 Angaben aus dem Inserat")

optionen = ["Ja", "Nein", "Unbekannt"]

col1, col2 = st.columns(2)

with col1:
    i_nicht_eg = st.selectbox(
        "Nicht Erdgeschoss?",
        optionen,
        index=2
    )

    i_balkon = st.selectbox(
        "Balkon / Terrasse?",
        optionen,
        index=2
    )

    i_modern = st.selectbox(
        "Moderner Ausbau?",
        optionen,
        index=2
    )

    i_ruhig = st.selectbox(
        "Ruhige Lage?",
        optionen,
        index=2
    )

with col2:
    i_parkplatz = st.selectbox(
        "Parkplatz vorhanden?",
        optionen,
        index=2
    )

    i_dusche = st.selectbox(
        "Begehbare Dusche?",
        optionen,
        index=2
    )

    i_badewanne = st.selectbox(
        "Badewanne vorhanden?",
        optionen,
        index=2
    )

    i_oev = st.selectbox(
        "Gute ÖV-Anbindung?",
        optionen,
        index=2
    )

i_steuer = st.selectbox(
    "Steuerlich attraktive Gemeinde?",
    optionen,
    index=2
)

# =========================================================
# MATCH SCORE
# =========================================================

def pruefen(gewuenscht, wert, umgekehrt=False):

    if not gewuenscht:
        return None

    if wert == "Unbekannt":
        return None

    if umgekehrt:
        return wert == "Nein"

    return wert == "Ja"


if st.button(
    "⭐ Match berechnen",
    type="primary",
    use_container_width=True
):

    punkte = 0
    maximal = 0
    details = []

    # Preis
    maximal += 3

    if gesamtpreis <= max_miete:
        punkte += 3
        details.append(
            ("✅", "Gesamtpreis",
             f"CHF {gesamtpreis:,.0f} – innerhalb Budget")
        )
    else:
        details.append(
            ("❌", "Gesamtpreis",
             f"CHF {gesamtpreis:,.0f} – über Budget")
        )

    # Zimmer
    maximal += 2

    if min_zimmer <= zimmer <= max_zimmer:
        punkte += 2
        details.append(
            ("✅", "Zimmer", f"{zimmer}")
        )
    else:
        details.append(
            ("❌", "Zimmer", f"{zimmer}")
        )

    pruefungen = [
        (
            "Nicht Erdgeschoss",
            nicht_eg,
            i_nicht_eg,
            False
        ),
        (
            "Balkon / Terrasse",
            balkon,
            i_balkon,
            False
        ),
        (
            "Moderner Ausbau",
            modern,
            i_modern,
            False
        ),
        (
            "Ruhige Lage",
            ruhig,
            i_ruhig,
            False
        ),
        (
            "Parkplatz",
            parkplatz,
            i_parkplatz,
            False
        ),
        (
            "Begehbare Dusche",
            dusche,
            i_dusche,
            False
        ),
        (
            "Keine Badewanne",
            keine_badewanne,
            i_badewanne,
            True
        ),
        (
            "ÖV-Anbindung",
            oev,
            i_oev,
            False
        ),
        (
            "Steuerfuss",
            steuer,
            i_steuer,
            False
        ),
    ]

    for name, gewuenscht, wert, umgekehrt in pruefungen:

        if gewuenscht:

            maximal += 1

            ergebnis = pruefen(
                gewuenscht,
                wert,
                umgekehrt
            )

            if ergebnis is True:
                punkte += 1
                details.append(
                    ("✅", name, "erfüllt")
                )

            elif ergebnis is False:
                details.append(
                    ("❌", name, "nicht erfüllt")
                )

            else:
                details.append(
                    ("❓", name, "nicht angegeben")
                )

    if maximal > 0:
        score = round(
            punkte / maximal * 100
        )
    else:
        score = 0

    st.divider()
    st.header("📊 Ergebnis")

    if score >= 85:
        st.success(
            f"🟢 Match: {score}% – sehr hohe Übereinstimmung"
        )

    elif score >= 70:
        st.warning(
            f"🟡 Match: {score}% – gute Übereinstimmung"
        )

    else:
        st.error(
            f"🔴 Match: {score}% – mehrere Kriterien fehlen"
        )

    if titel:
        st.write(f"**Wohnung:** {titel}")

    if ort:
        st.write(f"**Ort:** {ort}")

    st.write(
        f"**Gesamtpreis:** CHF {gesamtpreis:,.0f}"
    )

    st.subheader("Kriterien")

    for symbol, name, text in details:
        st.write(
            f"{symbol} **{name}:** {text}"
        )

    if inserat_url:
        st.link_button(
            "🏠 Originalinserat öffnen",
            inserat_url
        )

    if gesamtpreis > max_miete:
        st.error(
            f"Die Wohnung überschreitet das Budget "
            f"von CHF {max_miete:,.0f} um "
            f"CHF {gesamtpreis - max_miete:,.0f}."
        )

    unbekannt = sum(
        1
        for symbol, _, _ in details
        if symbol == "❓"
    )

    if unbekannt:
        st.info(
            f"{unbekannt} Kriterium/Kriterien konnten "
            "noch nicht beurteilt werden."
        )

st.divider()

st.caption(
    "Wohnungs-Finder Schweiz – Angaben immer mit dem "
    "Originalinserat und dem Mietvertrag überprüfen."
)
