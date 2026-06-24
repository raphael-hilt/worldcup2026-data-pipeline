import requests
import psycopg2
import json
import os
from datetime import datetime
from dotenv import load_dotenv

# Charge les variables du fichier .env
load_dotenv()

# Configuration API
API_KEY = os.getenv("API_KEY")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY}
COMPETITION_CODE = "WC"

def get_connection():
    """
    Crée et retourne une connexion à la base de données PostgreSQL.
    
    En local : host=localhost (PostgreSQL tourne dans Docker sur ta machine)
    En entreprise : host=adresse_du_serveur (ex: AWS RDS, serveur interne)
    
    On utilise os.getenv() pour lire les valeurs depuis .env
    et ne jamais écrire les credentials en dur dans le code.
    """
    return psycopg2.connect(
        host="localhost",
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

def create_tables():
    """
    Crée les tables dans PostgreSQL si elles n'existent pas encore.
    
    On crée 3 tables :
    - matches : tous les matchs de la compétition
    - scorers : le classement des buteurs
    - standings : les classements par groupe
    
    'IF NOT EXISTS' est important : si on relance le script,
    il ne va pas planter en essayant de recréer une table déjà existante.
    """
    conn = get_connection()  # On ouvre la connexion
    cur = conn.cursor()      # Le curseur est comme un "stylo" pour écrire dans la BDD

    # Table des matchs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY,
            utc_date TIMESTAMP,
            status VARCHAR(20),           -- SCHEDULED, IN_PLAY, FINISHED
            stage VARCHAR(50),            -- GROUP_STAGE, ROUND_OF_16, etc.
            team1 VARCHAR(100),           -- Première équipe
            team2 VARCHAR(100),           -- Deuxième équipe
            score_team1 INTEGER,          -- Score équipe 1 (NULL si pas joué)
            score_team2 INTEGER,          -- Score équipe 2 (NULL si pas joué)
            winner VARCHAR(100),          -- Gagnant (NULL si nul ou pas joué)
            ingested_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Table des buteurs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scorers (
            id SERIAL PRIMARY KEY,        -- SERIAL = auto-incrément, PostgreSQL génère l'id
            player_name VARCHAR(100),     -- Nom du joueur
            team_name VARCHAR(100),       -- Son équipe
            goals INTEGER,               -- Nombre de buts
            ingested_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Table des classements par groupe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS standings (
            id SERIAL PRIMARY KEY,
            group_name VARCHAR(10),       -- Nom du groupe : A, B, C...
            team_name VARCHAR(100),       -- Equipe
            played_games INTEGER,         -- Matchs joués
            won INTEGER,                  -- Victoires
            draw INTEGER,                 -- Nuls
            lost INTEGER,                 -- Défaites
            points INTEGER,              -- Points
            goals_for INTEGER,           -- Buts marqués
            goals_against INTEGER,       -- Buts encaissés
            goal_difference INTEGER,     -- Différence de buts
            ingested_at TIMESTAMP DEFAULT NOW()
        );
    """)

    conn.commit()   # Valide les changements — comme un "Enregistrer" dans la BDD
    cur.close()     # Ferme le curseur
    conn.close()    # Ferme la connexion — toujours libérer les ressources après usage
    print(" Tables créées ou déjà existantes.")


def fetch_matches():
    """
    Appelle l'API football-data.org et récupère tous les matchs
    de la Coupe du Monde 2026.
    
    L'API retourne un JSON avec une clé "matches" contenant
    la liste de tous les matchs. On retourne cette liste.
    
    Si l'appel échoue (mauvaise clé API, problème réseau...),
    on affiche l'erreur et on retourne une liste vide pour
    ne pas faire planter tout le pipeline.
    """
    url = f"{BASE_URL}/competitions/{COMPETITION_CODE}/matches"
    
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        # 200 = succès en HTTP
        # Autres codes courants : 401 = non autorisé, 429 = trop de requêtes
        print(f" Erreur API matches : {response.status_code} - {response.text}")
        return []

    return response.json().get("matches", [])
    # .json() convertit la réponse texte en dictionnaire Python
    # .get("matches", []) récupère la clé "matches", ou [] si elle n'existe pas

def fetch_scorers():
    """
    Récupère le classement des buteurs de la compétition.
    Même logique que fetch_matches().
    """
    url = f"{BASE_URL}/competitions/{COMPETITION_CODE}/scorers"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        print(f" Erreur API scorers : {response.status_code} - {response.text}")
        return []

    return response.json().get("scorers", [])

def fetch_standings():
    """
    Récupère les classements par groupe.
    Disponible uniquement pendant et après la phase de groupes.
    """
    url = f"{BASE_URL}/competitions/{COMPETITION_CODE}/standings"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        print(f" Erreur API standings : {response.status_code} - {response.text}")
        return []

    return response.json().get("standings", [])


def store_matches(matches):
    """
    Stocke la liste des matchs dans la table 'matches' de PostgreSQL.
    
    Ici j'utilise 'INSERT ... ON CONFLICT DO UPDATE' — appelé UPSERT.
    Pouquoi? Si le match existe déjà, on met à jour ses données
    (le score peut avoir changé). Sinon on l'insère.
    C'est crucial car on appelle ce script toutes les 10 minutes —
    on ne veut pas de doublons mais on veut les mises à jour.
    """
    conn = get_connection()
    cur = conn.cursor()

    for match in matches:
        # L'API renvoie les scores dans un objet imbriqué
        # On vérifie qu'ils existent avant de les lire
        score_team1 = None
        score_team2 = None
        winner = None

        if match.get("score", {}).get("fullTime"):
            score_team1 = match["score"]["fullTime"].get("home")
            score_team2 = match["score"]["fullTime"].get("away")

        # Détermine le gagnant si le match est terminé
        if score_team1 is not None and score_team2 is not None:
            if score_team1 > score_team2:
                winner = match["homeTeam"]["name"]
            elif score_team2 > score_team1:
                winner = match["awayTeam"]["name"]
            else:
                winner = "Draw"  # Match nul (uniquement possible en phase de groupes)

        cur.execute("""
            INSERT INTO matches 
                (id, utc_date, status, stage, team1, team2, score_team1, score_team2, winner)
            VALUES 
                (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                score_team1 = EXCLUDED.score_team1,
                score_team2 = EXCLUDED.score_team2,
                winner = EXCLUDED.winner,
                ingested_at = NOW();
        """, (
            match["id"],
            match["utcDate"],
            match["status"],
            match.get("stage", ""),
            match["homeTeam"]["name"],  # team1 = première équipe selon l'API
            match["awayTeam"]["name"],  # team2 = deuxième équipe selon l'API
            score_team1,
            score_team2,
            winner
        ))

    conn.commit()
    cur.close()
    conn.close()
    print(f" {len(matches)} matchs stockés.")

def store_scorers(scorers):
    """
    Stocke le classement des buteurs.
    
    Contrairement aux matchs, on vide la table et on recharge
    à chaque fois (DELETE + INSERT). Pourquoi ? Parce que le
    classement des buteurs change à chaque but — il est plus
    simple de tout recharger que de gérer les mises à jour
    individuelles de chaque joueur.
    """
    conn = get_connection()
    cur = conn.cursor()

    # On vide la table avant de recharger
    cur.execute("DELETE FROM scorers;")

    for s in scorers:
        cur.execute("""
            INSERT INTO scorers (player_name, team_name, goals)
            VALUES (%s, %s, %s);
        """, (
            s["player"]["name"],   # Nom du joueur
            s["team"]["name"],     # Son équipe
            s.get("goals", 0)      # Nombre de buts, 0 par défaut
        ))

    conn.commit()
    cur.close()
    conn.close()
    print(f" {len(scorers)} buteurs stockés.")

def store_standings(standings):
    """
    Stocke les classements par groupe.
    Même stratégie que les buteurs : DELETE + INSERT complet.
    Les classements changent après chaque match —
    plus simple de tout recharger.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM standings;")

    for group in standings:
        group_name = group.get("group", "")
        # Chaque groupe contient une liste d'équipes dans "table"
        for team in group.get("table", []):
            cur.execute("""
                INSERT INTO standings
                    (group_name, team_name, played_games, won, draw, 
                     lost, points, goals_for, goals_against, goal_difference)
                VALUES 
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);  -- On évite l'injection SQL et on laisse psycogp2 gérer le manière sécurisé. 
            """, (
                group_name,
                team["team"]["name"],
                team["playedGames"],
                team["won"],
                team["draw"],
                team["lost"],
                team["points"],
                team["goalsFor"],
                team["goalsAgainst"],
                team["goalDifference"]
            ))

    conn.commit()
    cur.close()
    conn.close()
    print(" Classements stockés.")


def run():
    """
    Fonction principale qui orchestre tout le pipeline d'ingestion.
    
    Elle appelle chaque fonction dans le bon ordre :
    1. Crée les tables si nécessaire
    2. Récupère et stocke les matchs
    3. Récupère et stocke les buteurs
    4. Récupère et stocke les classements
    
    C'est cette fonction qu'Airflow appellera toutes les 10 minutes.
    """
    print(f"\n Ingestion démarrée à {datetime.now()}")
    
    # Étape 1 : création des tables
    create_tables()

    # Étape 2 : matchs
    print("\n Récupération des matchs...")
    matches = fetch_matches()
    if matches:
        store_matches(matches)
    else:
        print(" Aucun match récupéré.")

    # Étape 3 : buteurs
    print("\n Récupération des buteurs...")
    scorers = fetch_scorers()
    if scorers:
        store_scorers(scorers)
    else:
        print(" Aucun buteur récupéré.")

    # Étape 4 : classements
    print("\n Récupération des classements...")
    standings = fetch_standings()
    if standings:
        store_standings(standings)
    else:
        print(" Aucun classement récupéré.")

    print(f"\n Ingestion terminée à {datetime.now()}\n")


# Point d'entrée du script
# Cette condition vérifie si on lance ce fichier directement
# avec "python3 ingest.py" — si oui, on appelle run()
# Si ce fichier est importé par un autre script (comme Airflow),
# run() ne sera PAS appelé automatiquement
if __name__ == "__main__":
    run()