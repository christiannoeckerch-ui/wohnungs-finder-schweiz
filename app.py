import streamlit as st
from urllib.parse import quote_plus

# -------------------------------------------------
# SEITENEINSTELLUNGEN
# -------------------------------------------------

st.set_page_config(
    page_title="Wohnungs-Finder Schweiz",
    page_icon="🏠",
    layout="wide"
)

st.title("🏠 Wohnungs-Finder Schweiz")
st.write(
    "Finde Mietwohnungen, die möglichst gut zu deinen "
    "persönlichen Wunschkriterien passen."
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

st.caption(
    "Der maximale Gesamtpreis soll Nettomiete, Nebenkosten "
    "und den gewünschten Autoabstellplatz umfassen."
)

# -------------------------------------------------
# AUSSTATTUNG
# -------------------------------------------------

st.header("🏡 Ausstattung")

col1, col2 = st.columns(2)

with col1:
    nicht_eg = st.checkbox(
        "Nicht im Erdgeschoss",
        value=True
    )

    balkon = st.checkbox(
        "Balkon / Terrasse",
        value=True
    )

    moderne_wohnung = st.checkbox(
        "Moderner Ausbau",
        value=True
    )

    ruhige_lage = st.checkbox(
        "Ruhige Wohnlage",
        value=True
    )

with col2:
    parkplatz = st.checkbox(
        "Autoabstellplatz / Parkplatz",
        value=True
    )

    begehbare_dusche = st.checkbox(
        "Begehbare Dusche",
        value=True
    )

    keine_badewanne = st.checkbox(
        "Keine Badewanne",
        value=True
    )

    gute_oev = st.checkbox(
        "Gute ÖV-Anbindung",
        value=True
    )

# -------------------------------------------------
# GEMEINDE
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
        "Keine Badewanne",
        "ÖV-Anbindung",
        "Niedriger Steuerfuss",
    ],
    default=[
        "Preis",
        "Ruhige Lage",
        "Begehbare Dusche",
    ],
)

# -------------------------------------------------
# SUCHBEGRIFF ERSTELLEN
# -------------------------------------------------

def suchtext_erstellen(ort):
    begriffe = [
        f"Mietwohnung {ort}",
        f"{min_zimmer} bis {max_zimmer} Zimmer",
        f"max CHF {max_miete}",
    ]

    if balkon:
        begriffe.append("Balkon")

    if parkplatz:
        begriffe.append("Parkplatz")

    if begehbare_dusche:
        begriffe.append("Dusche")

    if keine_badewanne:
        begriffe.append("-Badewanne")

    return " ".join(begriffe)


# -------------------------------------------------
# SUCHE
# -------------------------------------------------

st.divider()

if st.button(
    "🔎 Wohnungen suchen",
    type="primary",
    use_container_width=True,
):

    alle_orte = list(gemeinden)

    if weitere_orte.strip():
        extra = [
            ort.strip()
            for ort in weitere_orte.split(",")
            if ort.strip()
        ]

        alle_orte.extend(extra)

    if not alle_orte:
        st.warning(
            "Bitte mindestens einen Ort auswählen oder eingeben."
        )

    elif min_zimmer > max_zimmer:
        st.error(
            "Die minimale Zimmerzahl darf nicht grösser "
            "als die maximale Zimmerzahl sein."
        )

    else:

        st.success(
            f"Suchprofil für {len(alle_orte)} Ort(e) erstellt."
        )

        # -----------------------------------------
        # SUCHPROFIL
        # -----------------------------------------

        st.subheader("🎯 Aktuelles Suchprofil")

        profil1, profil2, profil3 = st.columns(3)

        with profil1:
            st.metric(
                "Max. Gesamtpreis",
                f"CHF {max_miete:,.0f}"
            )

        with profil2:
            st.metric(
                "Zimmer",
                f"{min_zimmer} – {max_zimmer}"
            )

        with profil3:
            st.metric(
                "Suchorte",
                len(alle_orte)
            )

        st.write(
            "**Orte:** " + ", ".join(alle_orte)
        )

        # -----------------------------------------
        # KRITERIEN
        # -----------------------------------------

        kriterien = []

        if nicht_eg:
            kriterien.append("Nicht EG")

        if balkon:
            kriterien.append("Balkon / Terrasse")

        if moderne_wohnung:
            kriterien.append("Moderner Ausbau")

        if ruhige_lage:
            kriterien.append("Ruhige Lage")

        if parkplatz:
            kriterien.append("Parkplatz")

        if begehbare_dusche:
            kriterien.append("Begehbare Dusche")

        if keine_badewanne:
            kriterien.append("Keine Badewanne")

        if gute_oev:
            kriterien.append("Gute ÖV-Anbindung")

        if steuerfuss:
            kriterien.append("Niedriger Steuerfuss")

        st.write(
            "**Gewünschte Kriterien:** "
            + ", ".join(kriterien)
        )

        # -----------------------------------------
        # PORTALE
        # -----------------------------------------

        st.divider()

        st.header("🌐 Wohnungssuche im Internet")

        st.write(
            "Öffne die Suchportale für den gewünschten Ort. "
            "Die Treffer können danach mit unserem Suchprofil "
            "verglichen werden."
        )

        for ort in alle_orte:

            st.subheader(f"📍 {ort}")

            suchtext = suchtext_erstellen(ort)
            google_suche = quote_plus(suchtext)

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.link_button(
                    "🏠 Homegate",
                    "https://www.homegate.ch/",
                    use_container_width=True,
                )

            with col2:
                st.link_button(
                    "🏢 ImmoScout24",
                    "https://www.immoscout24.ch/",
                    use_container_width=True,
                )

            with col3:
                st.link_button(
                    "🔎 Comparis",
                    "https://www.comparis.ch/immobilien/",
                    use_container_width=True,
                )

            with col4:
                st.link_button(
                    "🏘️ Flatfox",
                    "https://flatfox.ch/",
                    use_container_width=True,
                )

            st.link_button(
                f"🔍 Websuche nach Wohnungen in {ort}",
                "https://www.google.com/search?q="
                + google_suche,
                use_container_width=True,
            )

        # -----------------------------------------
        # NÄCHSTER AUSBAUSCHRITT
        # -----------------------------------------

        st.divider()

        st.header("🤖 Nächster Schritt: automatische Bewertung")

        st.info(
            "Als nächste Ausbaustufe soll der Agent einzelne "
            "Wohnungsinserate automatisch analysieren und einen "
            "Match-Score berechnen. Dabei prüfen wir unter anderem "
            "Gesamtpreis, Zimmerzahl, Parkplatz, Balkon, Stockwerk, "
            "Dusche/Badewanne, ÖV, Lage und modernen Ausbau."
        )

        st.write("**Prioritäten:**")

        if prioritaeten:
            for prioritaet in prioritaeten:
                st.write(f"⭐ {prioritaet}")
        else:
            st.write("Keine zusätzlichen Prioritäten gewählt.")

# -------------------------------------------------
# HINWEIS
# -------------------------------------------------

st.divider()

st.caption(
    "Wohnungs-Finder Schweiz – Angaben zu Preis, Nebenkosten, "
    "Parkplatz und Ausstattung immer im Originalinserat prüfen."
)
