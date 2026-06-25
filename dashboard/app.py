import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration de la page
st.set_page_config(
    page_title="World Cup 2026 · Data Pipeline",
    page_icon="⚽",
    layout="wide"   # Utilise toute la largeur de l'écran
)

@st.cache_resource
def get_connection():
    """
    Crée une connexion à PostgreSQL.
    
    @st.cache_resource signifie que Streamlit garde cette connexion
    en mémoire — elle n'est créée qu'une seule fois au démarrage
    de l'application, pas à chaque fois qu'un utilisateur interagit
    avec le dashboard. C'est une optimisation importante.
    
    En local : host="localhost"
    Dans Docker : host="postgres" (nom du service dans docker-compose.yml)
    On utilise une variable d'environnement pour switcher facilement.
    """
    host = os.getenv("POSTGRES_HOST", "localhost")
    # os.getenv("POSTGRES_HOST", "localhost") signifie :
    # "prends la variable POSTGRES_HOST du .env,
    # si elle n'existe pas utilise localhost par défaut"
    
    return psycopg2.connect(
        host=host,
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )


@st.cache_data(ttl=600)
def load_matches():
    """
    Charge tous les matchs depuis PostgreSQL.
    
    @st.cache_data(ttl=600) signifie que Streamlit met en cache
    le résultat pendant 600 secondes (10 minutes).
    Pourquoi ? Pour ne pas interroger PostgreSQL à chaque clic
    de l'utilisateur — c'est plus rapide et moins coûteux.
    Après 10 minutes le cache expire et les données sont rechargées
    — cohérent avec notre pipeline qui tourne toutes les 10 minutes.
    """
    conn = get_connection()
    return pd.read_sql(
        "SELECT * FROM matches ORDER BY utc_date",
        conn
    )
    # pd.read_sql() exécute une requête SQL et retourne
    # directement un DataFrame pandas


@st.cache_data(ttl=600)
def load_scorers():
    """Charge les buteurs triés par nombre de buts décroissant."""
    conn = get_connection()
    return pd.read_sql(
        "SELECT * FROM scorers ORDER BY goals DESC",
        conn
    )


@st.cache_data(ttl=600)
def load_standings():
    """Charge les classements par groupe."""
    conn = get_connection()
    return pd.read_sql(
        "SELECT * FROM standings ORDER BY group_name, points DESC",
        conn
    )

# --- HEADER ---
st.title("World Cup 2026 · Data Pipeline")
st.markdown(
    "Pipeline temps réel · **Airflow** · **PySpark** · **PostgreSQL** · **Streamlit**"
)
st.divider()  # Ligne de séparation horizontale

# --- CHARGEMENT DES DONNÉES ---
matches = load_matches()
scorers = load_scorers()
standings = load_standings()

# On filtre les matchs terminés et en cours
finished = matches[matches["status"] == "FINISHED"]
in_play = matches[matches["status"] == "IN_PLAY"]
scheduled = matches[matches["status"] == "TIMED"]

# --- MÉTRIQUES GLOBALES ---
# st.columns(4) divise la page en 4 colonnes égales
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Matchs joués",
        value=len(finished),
        delta=f"{len(in_play)} en cours"
        # delta affiche un petit indicateur vert/rouge sous la métrique
    )

with col2:
    st.metric(
        label="Matchs restants",
        value=len(scheduled)
    )

with col3:
    # Calcule le total des buts
    total_goals = int(finished["score_team1"].sum() + finished["score_team2"].sum())
    st.metric(
        label="Buts marqués",
        value=total_goals
    )

with col4:
    # Moyenne de buts par match
    avg_goals = round(total_goals / len(finished), 2) if len(finished) > 0 else 0
    st.metric(
        label="Moyenne buts/match",
        value=avg_goals
    )

st.divider()

# --- ONGLETS ---
# st.tabs() crée des onglets navigables
tab1, tab2, tab3 = st.tabs(["📊 Classements", "⚽ Buteurs", "📅 Résultats"])

# ==============================
# ONGLET 1 — CLASSEMENTS
# ==============================
with tab1:
    st.subheader("Classements par groupe")

    if standings.empty:
        # .empty vérifie si le DataFrame est vide
        st.info("Classements en cours de chargement...")
    else:
        # On récupère la liste unique des groupes
        groups = sorted(standings["group_name"].unique())

        # On affiche les groupes sur 3 colonnes
        cols = st.columns(3)

        for i, group in enumerate(groups):
            with cols[i % 3]:
                # i % 3 donne le reste de la division par 3
                # 0%3=0, 1%3=1, 2%3=2, 3%3=0, 4%3=1...
                # Ca permet de répartir les groupes sur 3 colonnes

                # Filtre le DataFrame pour ce groupe
                group_df = standings[standings["group_name"] == group][[
                    "team_name", "played_games", "won",
                    "draw", "lost", "points", "goal_difference"
                ]].rename(columns={
                    "team_name": "Équipe",
                    "played_games": "J",
                    "won": "V",
                    "draw": "N",
                    "lost": "D",
                    "points": "Pts",
                    "goal_difference": "+/-"
                })

                st.markdown(f"**Groupe {group}**")
                st.dataframe(
                    group_df,
                    hide_index=True,        # Cache la colonne d'index pandas
                    use_container_width=True # Adapte la largeur au conteneur
                )

# ==============================
# ONGLET 2 — BUTEURS
# ==============================
with tab2:
    st.subheader("Classement des buteurs")

    if scorers.empty:
        st.info("Données buteurs en cours de chargement...")
    else:
        # Graphique horizontal avec Plotly
        fig = px.bar(
            scorers.head(15),       # Top 15 seulement
            x="goals",              # Axe horizontal = nombre de buts
            y="player_name",        # Axe vertical = nom du joueur
            orientation="h",        # h = horizontal
            color="team_name",      # Couleur différente par équipe
            title="Top 15 buteurs · Coupe du Monde 2026",
            labels={
                "goals": "Buts",
                "player_name": "Joueur",
                "team_name": "Équipe"
            }
        )
        # Trie les barres par nombre de buts croissant
        fig.update_layout(
            height=500,
            yaxis={"categoryorder": "total ascending"}
        )
        st.plotly_chart(fig, use_container_width=True)

# ==============================
# ONGLET 3 — RÉSULTATS
# ==============================
with tab3:
    st.subheader("Résultats des matchs")

    if finished.empty:
        st.info("Aucun match terminé pour le moment.")
    else:
        # Filtre par phase
        stages = ["Toutes les phases"] + list(matches["stage"].unique())
        selected_stage = st.selectbox("Filtrer par phase", stages)

        df_display = finished.copy()
        if selected_stage != "Toutes les phases":
            df_display = df_display[df_display["stage"] == selected_stage]

        # Formate les données pour l'affichage
        df_display["Score"] = (
            df_display["score_team1"].astype(int).astype(str)
            + " - " +
            df_display["score_team2"].astype(int).astype(str)
        )
        df_display["Date"] = pd.to_datetime(
            df_display["utc_date"]
        ).dt.strftime("%d/%m %H:%M")

        st.dataframe(
            df_display[[
                "Date", "team1", "Score", "team2", "winner", "stage"
            ]].rename(columns={
                "team1": "Équipe 1",
                "team2": "Équipe 2",
                "winner": "Gagnant",
                "stage": "Phase"
            }),
            hide_index=True,
            use_container_width=True
        )

# --- FOOTER ---
st.divider()
st.markdown("""
<div style='text-align:center; color:#999; font-size:0.8rem'>
    Pipeline orchestré par Apache Airflow · Stockage PostgreSQL · Dashboard Streamlit<br>
    Données : football-data.org · Raphaël Hilt · 2026
</div>
""", unsafe_allow_html=True)