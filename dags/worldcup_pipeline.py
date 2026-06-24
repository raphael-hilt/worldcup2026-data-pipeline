from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys

# On ajoute le dossier scripts/ au path Python
# pour qu'Airflow puisse importer nos fonctions
sys.path.insert(0, '/opt/airflow/scripts')

# Configuration par défaut du DAG
default_args = {
    'owner': 'raphael',
    'depends_on_past': False,       # Chaque run est indépendant
    'start_date': datetime(2026, 6, 25),
    'retries': 2,                   # Retry automatique 2 fois si échec
    'retry_delay': timedelta(minutes=2),  # Attendre 2 min entre chaque retry
}

# Définition du DAG
dag = DAG(
    'worldcup_ingestion',           # Nom unique du DAG
    default_args=default_args,
    description='Pipeline ingestion Coupe du Monde 2026',
    schedule_interval='*/10 * * * *',  # Toutes les 10 minutes (syntaxe CRON)
    catchup=False,   # Ne pas rattraper les runs manqués depuis start_date
    tags=['worldcup', 'data-engineering'],
)


def ingest_matches():
    """Tâche 1 : récupère et stocke les matchs."""
    from ingest import fetch_matches, store_matches, create_tables
    create_tables()
    matches = fetch_matches()
    if matches:
        store_matches(matches)


def ingest_scorers():
    """Tâche 2 : récupère et stocke les buteurs."""
    from ingest import fetch_scorers, store_scorers
    scorers = fetch_scorers()
    if scorers:
        store_scorers(scorers)


def ingest_standings():
    """Tâche 3 : récupère et stocke les classements."""
    from ingest import fetch_standings, store_standings
    standings = fetch_standings()
    if standings:
        store_standings(standings)


# Définition des tâches
task_matches = PythonOperator(
    task_id='fetch_and_store_matches',
    python_callable=ingest_matches,
    dag=dag,
)

task_scorers = PythonOperator(
    task_id='fetch_and_store_scorers',
    python_callable=ingest_scorers,
    dag=dag,
)

task_standings = PythonOperator(
    task_id='fetch_and_store_standings',
    python_callable=ingest_standings,
    dag=dag,
)

# Ordre d'exécution des tâches
# >> signifie "puis"
task_matches >> task_scorers >> task_standings