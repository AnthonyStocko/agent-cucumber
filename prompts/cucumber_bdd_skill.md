## Compétence : écriture BDD Cucumber / Gherkin

Cette compétence est adaptée de cucumber-skill (LambdaTest/agent-skills, licence MIT, reprise par
sickn33/agentic-awesome-skills).

En cas de conflit, les règles du projet passent avant elle, dans cet ordre :
1. bibliothèque de steps du Standard ;
2. profil client ;
3. leçons ;
4. prompts de l'agent.

Les parties de l'original qui ne s'appliquent pas ici sont retirées :
- exécution cloud (TestMu / LambdaTest) : interdite, car les données de test et les écrans du client partiraient
  chez un tiers ;
- Selenium, JavaScript et Ruby.

### Écriture des features
- **Langage métier.** Un scénario décrit un comportement métier observable : une règle, son déclencheur, son
  résultat. Il ne décrit ni les clics ni l'interface. Le titre dit ce qui est vérifié.
- **Steps existants d'abord.**
  - Réutilise d'abord les steps du Standard et du client, même s'ils sont plus « techniques » qu'un step idéal.
  - Ne crée une step definition que si aucun step existant ne couvre le besoin.
  - Formule-la alors de façon déclarative et paramétrée ({string}, {int}, DataTable), pour qu'elle soit
    réutilisable.
- **Background** : seulement pour un contexte vraiment commun à tous les scénarios de la feature. L'initialisation
  du client reste dans l'init (@INIT_…), jamais dans un Background.
- **Scenario Outline / Examples** : quand le même comportement se vérifie sur plusieurs jeux de valeurs. Chaque
  ligne d'Examples doit pouvoir échouer pour une raison distincte.
- **Un scénario = un comportement.**
  - Au moins un Then vérifie un résultat que le When a produit.
  - Pas de Then tautologique, c'est-à-dire qui relit la donnée que le Given vient de créer.
- **Données explicites.** Les valeurs qui comptent pour la règle sont visibles dans le scénario (table ou
  paramètre), pas cachées dans le code des steps.
- **Indépendance.**
  - Un scénario ne dépend ni de l'ordre d'exécution, ni des données laissées par un autre.
  - Il crée ce qu'il lit, avec des codes uniques.
- **Tags.**
  - Tag du client et tag propre au scénario, selon les conventions du profil.
  - Pas de tag @ignore pour masquer un échec.

### Step definitions (Java)
- Un step = une action ou une vérification ; pas de logique conditionnelle qui change ce qui est vérifié.
- L'état partagé entre steps d'un scénario passe par le contexte d'injection du projet (glue existante), jamais
  par des champs statiques.
- **Assertions.**
  - Message qui cite l'attendu et l'obtenu.
  - Jamais de try/catch qui avale une erreur.
  - Jamais d'assertion affaiblie pour faire passer le test.

### Vérification
- Dry-run d'abord (steps non définis, ambiguïtés), puis exécution filtrée par tags.
- Un échec se diagnostique avec la trace et les données, pas en modifiant l'attendu.

### Anti-patterns
| À éviter | À préférer |
|---|---|
| Détails d'interface dans le Gherkin | Langage métier |
| Une ligne de code par step | Steps métier, existants d'abord |
| Contexte répété dans chaque scénario | Background (hors init du client) |
| Scénario qui dépend d'un autre | Données créées par le scénario |
| Assertion vague (« pas d'erreur ») | Valeur attendue précise |
