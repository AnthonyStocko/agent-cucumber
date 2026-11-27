# agent-cucumber

Tests Cucumber des clients : inventaire des spécifiques, génération et correction par lots, init et clear, runs
Jenkins, livraison ; post-merge (`generate-cucumber-postmerge`) et remise de configuration (`restore-config`).
Code repris tel quel d'agent-scrum-master (phase 6 du découpage) ; `main.py` et `app.py` élagués par script.

| | |
|---|---|
| IHM | `streamlit run app.py` (port 8507) : onglets « Cucumber » et « Cucumber (avancé) » |
| CLI | `python main.py --step generate-cucumber-client\|generate-cucumber-postmerge\|restore-config …` |
| Dépendance interne | `agent-socle` (seule) : `pip install -e ../agent-socle` pendant le chantier |
| Venv | `venv\` de ce dépôt (le manager lance l'agent avec lui) : `py -3.12 -m venv venv`, `requirements.txt`, socle en éditable |
| Données | `.tmp/cucumber…`, patchs et `.env` de `AGENT_DATA_DIR` (`C:\agent-data` ; défaut `..\agent-data`) ; CLI et IHM s'y placent |

Point d'entrée : le manager redirige vers cette IHM (8507). Lancée depuis ce dépôt, elle se place dans `AGENT_DATA_DIR`
et appelle le `main.py` de ce dépôt par chemin absolu (agent-scrum-master, qui y déléguait, est supprimé).

## Boucle de correction autonome

À la fin d'un run Jenkins lancé par l'agent (`--run-jenkins`), si des scénarios échouent **à cause de l'agent**
(catégorie `AGENT`, ou `INCERTAIN`), une boucle se lance seule, sans aucune validation humaine :

1. chaque échec est classé `AGENT`, `APPLICATION`, `ENVIRONNEMENT` ou `INCERTAIN` ; seuls `AGENT` et `INCERTAIN`
   partent vers **agent-dev-tool-savoye** (démarré au besoin par le superviseur du manager) ;
2. dev-tool corrige le code ou les prompts de l'agent (correction générique), lance ses tests unitaires et fusionne
   sur `main` (un commit par itération) ; une correction qui casse les tests ou fait régresser un scénario est
   annulée par `git revert` ;
3. l'agent recharge la correction, régénère les seuls scénarios en échec (contrôle anti-triche : pas de scénario
   supprimé, désactivé, commenté, ni d'assertion affaiblie) et rejoue la feature entière sur Jenkins (un seul job à
   la fois) ;
4. arrêt quand plus aucun échec n'est dû à l'agent, après N itérations (`CUCUMBER_BOUCLE_MAX_ITERATIONS`, 3) ou si
   une itération ne fait baisser aucun échec.

Rapport et journal des échanges : `.tmp/cucumber/<client>/boucles/<génération>.md`, `.json`, `.jsonl` et `.log` ;
le tableau de bord du manager l'affiche. `CUCUMBER_BOUCLE=0` désactive la boucle ; relance à la main :
`python main.py --step generate-cucumber-client --client-name <client> --boucle-correction --from-import <n>`.
Détails et contrat d'échange : `CLAUDE.md` § 6.
