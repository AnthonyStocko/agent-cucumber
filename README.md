# agent-cucumber

Tests Cucumber des clients : inventaire des spécifiques, génération et correction par lots, init et clear, runs
Jenkins, livraison ; post-merge (`generate-cucumber-postmerge`) et remise de configuration (`restore-config`).
Code repris tel quel d'agent-scrum-master (phase 6 du découpage) ; `main.py` et `app.py` élagués par script.

| | |
|---|---|
| IHM | `streamlit run app.py` (port 8507) : onglets « Cucumber » et « Cucumber (avancé) » |
| CLI | `python main.py --step generate-cucumber-client\|generate-cucumber-postmerge\|restore-config …` |
| Dépendance interne | `agent-socle` (seule) : `pip install -e ../agent-socle` pendant le chantier |
| Données | `.tmp/cucumber…`, patchs et `.env` de `AGENT_DATA_DIR` (défaut `..\agent-scrum-master`) ; CLI et IHM s'y placent |

`agent-scrum-master` délègue ces étapes (`AGENT_CUCUMBER_DIR`) ; lancée depuis ce dépôt, l'IHM appelle le `main.py`
d'agent-scrum-master (dossier de travail), qui relance celui-ci.
