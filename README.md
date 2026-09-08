# Chatbot BI – Prototype

*Version française · [Deutsche Fassung](README.de.md)*

Prototype d'un **chatbot apprenant pour la création interactive d'analyses de
Business Intelligence**. L'utilisateur construit une analyse au fil du dialogue :
il choisit les données, change de type de graphique, ajoute des séries et
définit des indicateurs à l'exécution — conformément au dialogue exemple du
professeur.

## Stack technique

| Couche              | Technologie                                            |
|---------------------|--------------------------------------------------------|
| Interface           | Streamlit                                              |
| NLU                 | LLM via Instructor (cloud **ou** local/Ollama) + mode démo à base de règles |
| Couche sémantique   | module Python maison (mesures, KPI)                    |
| Accès aux données   | DuckDB                                                 |
| Visualisation       | Plotly                                                 |

Le LLM ne génère **aucun SQL** : il produit uniquement des commandes
structurées s'appuyant sur un vocabulaire contrôlé (principe du *function
calling*). C'est sûr, testable, et cela correspond au modèle de composants du
chapitre 4.

## Démarrage rapide

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python3 create_data.py        # crée data/bi_demo.duckdb (facultatif, sinon automatique)
streamlit run app.py
```

L'application s'ouvre dans le navigateur. En **mode démo** (par défaut, aucune
clé API nécessaire), saisissez le dialogue exemple étape par étape. Pour le
**mode LLM**, renseignez le fournisseur, le modèle et la clé API dans la barre
latérale.

> Remarque : les noms de modèles (`claude-sonnet-5` ou similaires) sont des
> exemples — à adapter aux modèles réellement disponibles chez votre
> fournisseur.

## Modèle local (Ollama) – souveraineté des données

Le **mode local** fait tourner le module NLU sur un modèle open-weight
auto-hébergé. Les données ne quittent pas la machine, il n'y a aucun coût
d'API et le tout fonctionne hors ligne.

### Installation

| Système | Commande |
|---|---|
| macOS / Windows | Installateur sur [ollama.com](https://ollama.com) |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |

Sur macOS, Ollama démarre ensuite comme service en arrière-plan sur
`http://localhost:11434`.

```bash
ollama pull llama3.2:3b     # télécharger un modèle (~2 Go)
ollama list                 # vérifier les modèles installés
curl http://localhost:11434/api/tags   # vérifier que le service répond
```

Dans la barre latérale de l'application, choisir **« Lokal (Ollama) »**,
vérifier le nom du modèle puis cliquer sur **Verbinden**.

### Quel modèle choisir ?

Le module NLU fait de la **classification d'intention** avec extraction de
quelques paramètres — une tâche simple qui ne nécessite pas un grand modèle.

| Modèle | Taille | Remarque |
|---|---|---|
| `llama3.2:3b` | ~2 Go | Défaut recommandé, tourne avec 8 Go de RAM |
| `granite4:3b` | ~2,1 Go | Entraîné pour le *tool calling*, licence Apache 2.0 |
| `qwen3:8b` | ~5 Go | Plus robuste sur les formulations libres, nécessite un GPU |

Les modèles sous 4 milliards de paramètres fonctionnent même sans GPU
(inférence plus lente). Sur Mac Apple Silicon, l'accélération matérielle est
utilisée automatiquement.

### Aspects techniques

Le prototype utilise l'API compatible OpenAI d'Ollama avec `instructor` en
`Mode.JSON`. Ce mode **contraint le décodeur** : un JSON malformé devient
mécaniquement impossible, ce qui rend un modèle de 3B fiable pour cette tâche.
Un simple « réponds en JSON » dans le prompt ne serait qu'une requête, pas une
contrainte.

Limite connue : les petits modèles formatent bien mais choisissent parfois la
mauvaise action. Il est donc conseillé de garder un vocabulaire d'actions
restreint (le prototype en compte 7) avec des descriptions précises. D'où
également le `max_retries` et le `timeout` global.

> La comparaison **mode cloud vs mode local** (précision de la reconnaissance
> d'intention, latence, protection des données) constitue un excellent
> matériau pour l'évaluation (chap. 6).

## Configuration et clés API

Les clés ne doivent **jamais** figurer dans le code source. Elles se placent
dans un fichier `.env` à la racine du projet :

```bash
cp .env.example .env
# puis éditer .env et renseigner la clé
```

```ini
ANTHROPIC_API_KEY=sk-ant-...
BI_MODEL=claude-sonnet-5
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.2:3b
```

L'application charge ce fichier au démarrage : la clé est alors préremplie et
il n'y a plus rien à retaper. Le fichier `.env` est exclu par `.gitignore` —
il ne partira donc jamais dans un dépôt Git. Sans fichier `.env`, la clé reste
saisissable à la main dans la barre latérale, et le **mode local ainsi que le
mode démo n'ont besoin d'aucune clé**.

## Modèle de données (schéma en étoile)

La base de démonstration suit un **schéma en étoile** selon Kimball — le
standard de la modélisation dimensionnelle en Business Intelligence. La DDL
complète et commentée se trouve dans [`schema.sql`](schema.sql).

```
        dim_zeit                    dim_region
             \                        /
              \                      /
               +--- fakt_verkauf ---+
              /                      \
             /                        \
        dim_produkt                 dim_kunde
```

**Granularité de la table de faits :** une position de commande
= *un jour × un produit × un client*. Toutes les agrégations (mois, trimestre,
région, catégorie) sont calculées au moment de la requête par `GROUP BY`.

**Seules les mesures additives de base** (`menge`, `umsatz`, `kosten`) sont
stockées. Les indicateurs dérivés comme le *Gewinn* (bénéfice) ne sont
volontairement **pas** matérialisés : ils sont calculés à l'exécution dans la
couche sémantique. C'est précisément ce qui fonde la définition d'indicateurs
par le dialogue (chap. 4).

S'y ajoute la vue aplatie `sales` (niveau mensuel), utilisée par le prototype
pour le dialogue exemple.

### Génération et vérification des données fictives

```bash
python3 create_data.py     # (re)construit la base
python3 check_data.py      # vérifie structure, intégrité et plausibilité
```

Le script `check_data.py` produit un rapport lisible : présence des tables,
nombre de lignes, intégrité référentielle, absence de valeurs nulles ou
négatives, cohérence de la vue `sales` avec la table de faits, contrôles de
plausibilité métier (croissance, marge, couverture des mois), puis un aperçu
chiffré des ventes mensuelles. Il se termine par un verdict global — pratique
à relancer après chaque modification et à joindre en annexe du mémoire.

Les données sont synthétiques, mais suivent délibérément des motifs réalistes
afin que les graphiques du dialogue soient parlants :

| Effet | Mise en œuvre |
|---|---|
| Tendance de croissance | +18 % par an, exponentielle sur la période |
| Saisonnalité | creux estival (juil./août), Q4 fort, pic de décembre |
| Effet jour de semaine | week-ends quasiment sans chiffre d'affaires |
| Effet segment | les *Key Accounts* commandent plus et obtiennent des remises |
| Effet produit | marge élevée sur le logiciel, faible sur le matériel |
| Bruit | dispersion multiplicative sur quantité, prix et coût unitaire |

La graine aléatoire est fixe (`SEED = 42`) : la génération est donc
**reproductible** — essentiel pour la traçabilité de l'évaluation. Période,
croissance et volume se règlent en tête de `create_data.py`.

Toutes les tables sont également exportées en CSV dans `data/`.

## Docker

Le projet se lance sans installer Python ni les dépendances — utile pour
présenter le prototype ou le remettre avec le mémoire.

```bash
docker compose up          # construit l'image et démarre l'application
# puis ouvrir http://localhost:8501
```

La base de démonstration est générée pendant la construction de l'image :
le conteneur démarre immédiatement, et la graine aléatoire fixe garantit des
données identiques à chaque build.

### Deux façons d'utiliser Ollama

**Par défaut — Ollama sur la machine hôte.** Le conteneur l'appelle via
`host.docker.internal`. C'est le mode recommandé : sur un Mac Apple Silicon,
un conteneur Linux n'a pas accès à l'accélération Metal, donc laisser Ollama
sur l'hôte évite une inférence beaucoup plus lente.

**Tout dans Docker** — autonome, mais sans accélération matérielle :

```bash
docker compose --profile ollama up
# une seule fois, pour télécharger le modèle dans le volume :
docker compose --profile ollama exec ollama ollama pull llama3.2:3b
```

Dans ce cas, remplacer `OLLAMA_BASE_URL` par `http://ollama:11434/v1` dans
`docker-compose.yml` (la ligne est déjà présente en commentaire).

### Clés API

Le fichier `.env` est chargé automatiquement s'il existe, mais reste
facultatif : les modes **démo** et **local** n'en ont pas besoin. Il est exclu
de l'image par `.dockerignore`, donc aucune clé ne se retrouve dans le
conteneur.

### Commandes utiles

```bash
docker compose up --build       # reconstruire après modification du code
docker compose down             # arrêter
docker compose exec app pytest -q        # lancer les tests dans le conteneur
docker compose exec app python check_data.py   # rapport de vérification
```

## Tests

```bash
pytest -q
```

Les tests rejouent notamment l'intégralité du dialogue exemple, vérifient la
définition à l'exécution de l'indicateur « Gewinn », ainsi que l'intégrité
référentielle et la plausibilité des données.

## Structure du projet

```
app.py                    Interface Streamlit
create_data.py            Crée le schéma en étoile + les données fictives
check_data.py             Rapport de vérification de la base
schema.sql                Modèle de données documenté (DDL)
Dockerfile                Image du conteneur
docker-compose.yml        Orchestration (app + Ollama optionnel)
bi_chatbot/
  state.py                État du dialogue et de l'analyse (contexte, « apprenant »)
  semantic_layer.py       Mesures, KPI, exécution des commandes
  schema.py               Schéma de sortie Pydantic du module NLU
  interpreter.py          Modes LLM et démo + exécution
  db.py                   Accès DuckDB (mesures de base)
  charts.py               Graphiques Plotly
data/
  bi_demo.duckdb          Base de démonstration (schéma en étoile, 2024–2025)
  *.csv                   toutes les tables pour inspection
tests/
  test_semantic.py        Logique de dialogue et de KPI
  test_data_quality.py    Intégrité et plausibilité des données
```

## Correspondance avec le plan (Gliederung)

- **Chap. 4 Conception** — `schema.sql` (modèle de données), `semantic_layer.py`, `state.py`, `schema.py`
- **Chap. 5 Implémentation** — `app.py`, `interpreter.py`, `db.py`, `charts.py`
- **Chap. 6 Évaluation** — `tests/`, `check_data.py`

## Prochaines étapes (pistes d'extension)

- Rendre les dimensions Produit/Client exploitables dans le dialogue
  (« chiffre d'affaires par catégorie de produit », « uniquement les Key Accounts »)
- Niveaux d'agrégation supplémentaires (trimestre, semaine calendaire)
- Plusieurs actions par message
- Persistance de l'historique du dialogue
- Comparaison mode LLM vs mode démo dans l'évaluation


Yug et Gervais