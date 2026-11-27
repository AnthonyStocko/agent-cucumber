# CLAUDE.md — agent-cucumber

Fichier de contexte de l'agent Cucumber : ce que le code ne dit pas. Il fait autorité sur l'interprétation du code ;
en cas de contradiction entre ce fichier et le code, la signaler au lieu de trancher seul.

## 1. Rôle et périmètre

Génère, corrige et exécute les tests Cucumber d'un client Odatio (dépôt `<client>-cucumber`) : inventaire des
spécifiques, génération et correction par lots, init et clear, runs Jenkins, import des résultats, livraison ;
post-merge et remise de configuration. Code repris d'agent-scrum-master (phase 6 du découpage).

Il est lancé et supervisé par `agent-manager-savoye` (port 8507) et peut être amélioré automatiquement par
`agent-dev-tool-savoye` (boucle de correction autonome, § 6).

## 2. Stack, structure et commandes

- Python 3.12, Streamlit (`app.py`, IHM), CLI `main.py --step generate-cucumber-client …`, Claude Code CLI.
- Venv : `venv\` de ce dépôt (agent-socle en éditable pendant le chantier) ; le manager lance l'agent avec lui.
- Tests : `venv\Scripts\python.exe -m pytest -q tests` (depuis ce dossier). Aucun linter.
- Données : `AGENT_DATA_DIR` (`C:\agent-data` ; défaut `..\agent-data`) ; par client : `.tmp/cucumber/<client>/` (worktree,
  `etat.json`, `imports/<n>/analyse.json`, `generation.lock`, `boucles/`).
- Configuration : page ⚙️ de l'IHM, écrite dans `<AGENT_DATA_DIR>/.env` (le seul lu par l'IHM et `main.py`, partagé
  par tous les agents ; réglages globaux : manager, Configuration › Réglages des agents). Groundcover : API, `CUCUMBER_GROUNDCOVER_FILTER` (à défaut
  `logs.groundcover_filtre` de l'application du même nom dans `commun.toml` de `SAVOYE_CONFIG_DIR`, jamais écrit) et
  serveur MCP ; variables de `SAVOYE_VARIABLES` en lecture seule, jamais réécrites.

```
main.py                     CLI (étapes generate-cucumber-client, postmerge, restore-config)
app.py                      IHM Streamlit
prompts/*.md                prompts de l'agent (rendus par render_prompt)
tools/cucumber_*.py         logique (0 token sauf appels Claude explicites)
tools/cucumber_failures.py  classement de chaque échec d'un run importé (correction, diagnostic, environnement…)
tools/cucumber_import.py    import d'un build Jenkins ou d'un rapport : analyse.json par import
tools/cucumber_run.py       push, lancement et suivi du job Jenkins (attend tout build Cucumber en cours)
tools/cucumber_lock.py      verrou par client des générations (un seul processus écrit dans l'espace du client)
tools/cucumber_boucle.py    boucle de correction autonome : classement, demande, arrêt, anti-triche (0 token)
tools/cucumber_devtool.py   client de l'API locale d'agent-dev-tool-savoye (démarrage via le superviseur)
tools/cucumber_boucle_run.py  orchestration de la boucle (processus détaché, lancé à la fin d'un run)
tools/cucumber_configuration.py  page ⚙️ Configuration : Groundcover (composant agent_socle.ihm_groundcover), filtre repris de commun.toml
tests/                      tests unitaires (pytest) ; tests/reference/ : jeu de référence du classement
```

## 3. Prompts

`prompts/` : `cucumber_client_lot_systeme.md` (génération d'un lot), `cucumber_client_fix.md` (correction),
`cucumber_client_review.md`, `cucumber_init_*.md`, `postmerge.md`… Leur empreinte (sha1) est jointe à chaque demande
d'aide envoyée à dev-tool.

## 4. Glossaire

- **Spécifique** (= « fonctionnalité » dans le parcours du manager) : développement propre au client, couvert par
  des scénarios générés par lots, tagués `@agent_…`.
- **Import** : un run Jenkins (console + rapports Cucumber JSON) importé et analysé (`imports/<n>/analyse.json`).
- **Génération** : identifiant de boucle `<client>-<import>-<horodatage>`.

## 5. Règles sensibles

- Un seul job Cucumber à la fois sur Jenkins (`cucumber_run.launch` attend la fin du build en cours) ; un seul
  processus par client (`cucumber_lock`).
- Secrets : uniquement l'environnement transmis par le manager (`SAVOYE_VARIABLES`) ou le `.env` ; masqués
  (`agent_socle.secret_tools.mask_secrets`) avant tout stockage, journal ou envoi.
- Dépôt public : aucune donnée réelle de client dans les tests, exemples et commits.

## 6. Boucle de correction autonome (plan d'implémentation, 25 novembre 2026)

Objectif : à la fin d'un run, si des scénarios restent en échec à cause de l'agent lui-même, demander à
agent-dev-tool-savoye de corriger le code ou les prompts d'agent-cucumber, puis rejouer, sans validation humaine.

### Points d'accroche repérés (étape 0)

| Sujet | Où |
|---|---|
| Fin d'une génération exécutée | `main.run_cucumber_jenkins` → `run_cucumber_import` (analyse et bilan de l'import) |
| Résultats d'exécution | rapport Cucumber JSON + console du build Jenkins → `imports/<n>/analyse.json` (`resultats`, `echecs`) |
| Classement existant | `cucumber_failures.failure_results` (correction, diagnostic, environnement, produit, hors_depot, hors_perimetre) |
| Scénarios de l'agent | `cucumber_import.agent_scenarios(state)` : `{id: {tag, spec}}` |
| Verrou Jenkins | `cucumber_run.launch` (attente des builds en cours) ; verrou client `cucumber_lock` |
| Réception côté dev-tool | IHM seule (onglet Développer, lien `?demande=` du manager) : **ajout d'une API locale** |
| Localisation d'un dépôt (dev-tool) | `agent_dev/config.CIBLES` (dossier frère) : **ajout de la cible agent-cucumber** |
| Modification du code (dev-tool) | chantier = worktree depuis `origin/main`, session Agent SDK gardée (`garde.py`) |
| Lancement de dev-tool | superviseur du manager : `POST /agents/dev-tool/demarrer` (jeton de `.tmp/superviseur.json`) |
| Demande « prête à coller » | `manager/liens.py` (`?source=manager&page=developper&depot=…&demande=…`) |

### Classement (`cucumber_boucle.categorie`)

| Classement existant | Catégorie | Envoyé à dev-tool |
|---|---|---|
| `correction` (step, sélecteur, donnée, assertion…) | `AGENT` | oui |
| `diagnostic` (mécanisme à éclaircir) | `INCERTAIN` (signalé) | oui |
| `produit` (erreur serveur, liste de choix vide) | `APPLICATION` | non, rapporté |
| `environnement`, `hors_depot`, `hors_perimetre`, init en échec | `ENVIRONNEMENT` | non, rapporté |
| cascade | catégorie de l'échec qui la cause | selon celle-ci |
| inconnu | `INCERTAIN` | oui |
| défaut de l'agent hors run (`cucumber_agent_defects`) : lot en erreur de fichiers ou de compilation persistante, constat `defaut_agent` ou constat « prouvé » sur un fichier de l'agent (code, prompts, `.tmp/cucumber/<client>/`, `lecons.json`) | `AGENT` (nature `defaut_agent`, id `lot<n>::<étape>`) | oui, même sans échec Jenkins ; après la correction, les lots en erreur sont repris (`--resume`) avant toute régénération |

### Contrat d'échange (JSON, `version: 1`)

- Transport : API HTTP locale de dev-tool, `127.0.0.1:8513` (port et jeton dans
  `../agent-dev-tool-savoye/.tmp/api.json`, en-tête `X-Jeton`). `GET /sante`, `POST /demandes` (202 + `id`),
  `GET /demandes/<id>` (`attente`, `en_cours`, `termine` + réponse).
- Demande : `version`, `type = "correction-agent-cucumber"`, `generation`, `iteration`, `iterations_max`,
  `depot = "agent-cucumber"`, `projet`, `fonctionnalite`, `echecs[]` (id, feature, scenario, step, message, trace,
  step_definition, code_applicatif, categorie, nature, cause), `fichiers_generes[]`, `prompts[]` (nom, empreinte),
  `commit_agent`, `historique[]`, `annuler` (commit à défaire et raison, ou null), `marqueurs_interdits[]`
  (noms, titres et identifiants propres à cette fonctionnalité), `regles[]` (anti-triche). Secrets masqués.
- Réponse : `statut` (`corrige`, `annule`, `impossible`, `refuse`, `erreur`), `cause`, `correction`, `fichiers[]`,
  `resume_diff`, `commit`, `annulations[]`, `tests` (avant/après), `cout_usd`, `raison`.

### Déroulé

1. Fin de `run_cucumber_jenkins`, et fin d'une génération (`run_cucumber_client`) quand elle a produit un import
   (run de livraison) ou laissé un défaut de l'agent : si l'analyse compte au moins un échec `AGENT`/`INCERTAIN`, et hors boucle
   (`CUCUMBER_BOUCLE_ID` absent), un processus détaché `main.py --boucle-correction --from-import <n>` est lancé
   (`CUCUMBER_BOUCLE=0` le désactive).
2. Itération i ≤ N (`CUCUMBER_BOUCLE_MAX_ITERATIONS`, 3) : dev-tool démarré si besoin (superviseur), demande
   envoyée, réponse attendue. dev-tool : chantier, `git revert` du commit demandé, correction générique par l'agent,
   un seul commit, contrôle anti-triche du diff, tests unitaires d'agent-cucumber ; régression → `git revert` et
   rien n'est fusionné ; sinon fusion sur `main` et push.
3. Copie locale d'agent-cucumber mise à jour (`git merge --ff-only origin/main`, seulement si propre et sur
   `main`) ; chaque étape suivante est un nouveau processus `main.py`, qui recharge code et prompts.
4. Régénération des seuls scénarios en échec (`--complete --from-import <n>`), contrôle anti-triche des features
   (scénario supprimé, `@ignore`, scénario commenté, assertion retirée, fichier hors des tests) : fichier rétabli et
   échec classé `INCERTAIN`.
5. Un run Jenkins sélectionnant la feature entière (tags de tous ses scénarios, échecs compris), verrou respecté.
6. Arrêt : plus d'échec `AGENT`/`INCERTAIN` (terminée), N atteint ou aucun échec en moins (abandonnée). Un
   scénario qui passait et échoue ensuite → `annuler` du dernier commit à l'itération suivante (ou demande
   d'annulation seule si la boucle s'arrête).
7. Rapport : `boucles/<generation>.json` et `.md` (passés, restants par catégorie, corrections et commits,
   retours arrière, step definitions partagées modifiées, coût) ; journal des échanges `boucles/<generation>.jsonl`.
   Le manager l'affiche (outil `boucles_cucumber`, bloc du tableau de bord, relance si échecs restants).

### Décisions et points ouverts

- Autonomie complète demandée par l'utilisateur le 25 novembre 2026 : la fusion sans validation est limitée à la
  cible agent-cucumber, aux demandes reçues par l'API locale de dev-tool. Le reste de dev-tool garde la règle
  « confirmation avant de fusionner ».
- Une seule exécution Jenkins par itération (feature entière, échecs compris) au lieu de deux : même couverture,
  un seul passage du verrou.
- Le code de la boucle elle-même n'est pas rechargé pendant qu'elle tourne (les étapes le sont).
