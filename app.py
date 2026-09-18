import streamlit as st

st.set_page_config(
    page_title="Wohnungs-Finder Schweiz",
    page_icon="🏠",
    layout="wide"
)

st.title("🏠 Wohnungs-Finder Schweiz")
st.write(
    "Finde Wohnungen, die möglichst gut zu deinen persönlichen "
    "Wunschkriterien passen."
)

st.divider()

# -------------------------------------------------
# REGION
# -------------------------------------------------

st.header("📍 Wo suchst du?")

standard_gemeinden = [
    "Reinach BL",
    "Münchenstein",
    "Aesch BL",
    "Muttenz",
    "Liestal",
    "Frenkendorf"
]

gemeinden = st.multiselect(
    "Gemeinden / Orte",
    options=standard_gemeinden,
    default=standard_gemeinden
)

weitere_orte = st.text_input(
    "Weitere Orte",
    placeholder="z.B. Pratteln, Binningen, Arlesheim"
)

# -------------------------------------------------
# PREIS UND GRÖSSE
# -------------------------------------------------

st.header("💰 Preis & Grösse")

col1, col2, col3 = st.columns(3)

with col1:
    max_miete = st.number_input(
        "Max. Gesamtpreis pro Monat (CHF)",
        min_value=500,
        max_value=10000,
        value=1800,
        step=50
    )

with col2:
    min_zimmer = st.selectbox(
        "Mindestens Zimmer",
        [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
        index=3
    )

with col3:
    max_zimmer = st.selectbox(
        "Maximal Zimmer",
        [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0],
        index=4
    )

st.caption(
    "Der maximale Gesamtpreis soll Miete, Nebenkosten und "
    "den gewünschten Autoabstellplatz umfassen."
)

# -------------------------------------------------
# WOHNUNG
# -------------------------------------------------

st.header("🏡 Ausstattung")

col1, col2 = st.columns(2)

with col1:
    nicht_eg = st.checkbox("Nicht im Erdgeschoss", value=True)
    balkon = st.checkbox("Balkon / Terrasse", value=True)
    moderne_wohnung = st.checkbox("Moderner Ausbau", value=True)
    ruhige_lage = st.checkbox("Ruhige Wohnlage", value=True)

with col2:
    parkplatz = st.checkbox("Autoabstellplatz / Parkplatz", value=True)
    begehbare_dusche = st.checkbox("Begehbare Dusche", value=True)
    keine_badewanne = st.checkbox("Keine Badewanne", value=True)
    gute_oev = st.checkbox("Gute ÖV-Anbindung", value=True)

# -------------------------------------------------
# GEMEINDE / STEUERN
# -------------------------------------------------

st.header("🏛️ Gemeinde")

steuerfuss = st.checkbox(
    "Niedriger Steuerfuss bevorzugt",
    value=True
)

# -------------------------------------------------
# PRIORITÄTEN
# -------------------------------------------------

st.header("⭐ Was ist besonders wichtig?")

prioritaeten = st.multiselect(
    "Diese Kriterien stärker gewichten",
    [
        "Preis",
        "Ruhige Lage",
        "Moderner Ausbau",
        "Balkon / Terrasse",
        "Parkplatz",
        "Begehbare Dusche",
        "ÖV-Anbindung",
        "Niedriger Steuerfuss"
    ],
    default=[
        "Preis",
        "Ruhige Lage",
        "Begehbare Dusche"
    ]
)

# -------------------------------------------------
# SUCHE
# -------------------------------------------------

st.divider()

if st.button("🔎 Wohnungen suchen", type="primary"):

    st.success("Suchprofil wurde erstellt.")

    st.subheader("Deine Suche")

    st.write("**Orte:**", ", ".join(gemeinden))

    if weitere_orte:
        st.write("**Weitere Orte:**", weitere_orte)

    st.write(
        f"**Zimmer:** {min_zimmer} bis {max_zimmer}"
    )

    st.write(
        f"**Maximaler Gesamtpreis:** CHF {max_miete:,.0f} / Monat"
    )

    st.info(
        "Im nächsten Ausbauschritt verbinden wir diese Maske "
        "mit der eigentlichen Wohnungssuche und bewerten die "
        "gefundenen Inserate nach ihrer Übereinstimmung."
    )

st.divider()

st.caption(
    "Wohnungs-Finder Schweiz – Inserate und Angaben sollten "
    "vor einer Bewerbung immer beim jeweiligen Anbieter überprüft werden."
)
