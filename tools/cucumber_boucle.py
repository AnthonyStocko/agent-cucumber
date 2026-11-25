"""
Boucle de correction autonome (0 token) : classement des échecs d'un run, demande d'aide à agent-dev-tool-savoye,
décisions d'arrêt et contrôle anti-triche des features régénérées.

Seule la logique est ici (testable sans Jenkins, ni Claude, ni réseau) ; l'enchaînement est dans
cucumber_boucle_run, le transport dans cucumber_devtool. Voir CLAUDE.md § 6 pour le contrat d'échange.

Catégories :
- AGENT : erreur due à la génération (step inexistant ou mal formulé, sélecteur, donnée, assertion incohérente) ;
- APPLICATION : le test est correct mais révèle un défaut de l'application ;
- ENVIRONNEMENT : timeout, service indisponible, donnée de référence absente, init, verrou, hors périmètre ;
- INCERTAIN : la cause n'est pas prouvée (signalé comme tel à dev-tool).
Seuls AGENT et INCERTAIN partent vers dev-tool ; APPLICATION et ENVIRONNEMENT sont rapportés, jamais « corrigés »
en modifiant le test.
"""
import hashlib
import os
import re

AGENT, APPLICATION, ENVIRONNEMENT, INCERTAIN = "AGENT", "APPLICATION", "ENVIRONNEMENT", "INCERTAIN"
CATEGORIES = (AGENT, APPLICATION, ENVIRONNEMENT, INCERTAIN)
A_ENVOYER = (AGENT, INCERTAIN)
EN_COURS, TERMINEE, ABANDONNEE = "en_cours", "terminee", "abandonnee"
VERSION_CONTRAT = 1
TYPE_DEMANDE = "correction-agent-cucumber"
DEPOT = "agent-cucumber"
DEFAUT_ITERATIONS = 3
ITERATIONS_PLAFOND = 10

# Classement d'agent-cucumber (cucumber_failures.CATEGORIES) -> catégorie de la boucle
_PAR_CATEGORIE = {"correction": AGENT, "diagnostic": INCERTAIN, "produit": APPLICATION,
                  "environnement": ENVIRONNEMENT, "hors_depot": ENVIRONNEMENT, "hors_perimetre": ENVIRONNEMENT}
# Natures de « correction » qui ne relèvent pas de la génération : le test est juste, l'environnement non
_NATURES_ENVIRONNEMENT = {"deploiement", "conflit_verrouillage", "environnement_corrompu", "version", "init",
                          "donnee_reference", "environnement", "clear_client"}
_NATURES_APPLICATION = {"bug_applicatif", "liste_choix_vide"}
_TIMEOUT = re.compile(r"\b(?:timed? ?out|time-?out|d[ée]lai (?:d[ée]pass[ée]|expir[ée])|Connection refused|"
                      r"503 Service Unavailable|UnknownHostException|ConnectException)\b", re.I)

REGLES = [
    "Corriger l'agent cucumber (code et prompts), jamais les tests de cette génération : l'objectif est que l'agent "
    "génère correctement la prochaine fois, pour toute fonctionnalité et tout projet.",
    "Interdit : supprimer, désactiver, taguer @ignore ou commenter un scénario, ou demander à l'agent de le faire.",
    "Interdit : affaiblir une assertion, élargir un sélecteur au point de ne plus rien vérifier, ajouter un try/catch "
    "qui avale l'erreur.",
    "Interdit : coder en dur un résultat attendu, un identifiant ou une donnée propre à cette fonctionnalité "
    "(voir marqueurs_interdits) dans le code ou les prompts de l'agent.",
    "Interdit : modifier le code de l'application testée.",
    "Une step definition partagée existante ne se modifie pas sans le dire explicitement dans la réponse.",
    "Si la seule façon de faire passer le test est l'une de ces actions : répondre « impossible » avec la raison ; "
    "l'échec sera classé APPLICATION ou INCERTAIN.",
]


# --- réglages -----------------------------------------------------------------------------------------------------
def active() -> bool:
    """Boucle activée (CUCUMBER_BOUCLE, défaut 1)."""
    return os.getenv("CUCUMBER_BOUCLE", "1").strip().lower() not in ("0", "false", "non", "no", "off")


def dans_boucle() -> bool:
    """Processus lancé par une boucle (ses étapes ne relancent jamais une boucle)."""
    return bool(os.getenv("CUCUMBER_BOUCLE_ID", "").strip())


def max_iterations() -> int:
    """N (CUCUMBER_BOUCLE_MAX_ITERATIONS, défaut 3, borné à 1..10)."""
    try:
        valeur = int(os.getenv("CUCUMBER_BOUCLE_MAX_ITERATIONS", str(DEFAUT_ITERATIONS)).strip())
    except ValueError:
        return DEFAUT_ITERATIONS
    return max(1, min(ITERATIONS_PLAFOND, valeur))


# --- classement ---------------------------------------------------------------------------------------------------
def categorie(echec: dict) -> str:
    """Catégorie de la boucle d'un échec classé par cucumber_failures (cascade : déjà rattachée à sa cause)."""
    nature = str(echec.get("nature") or "")
    existante = str(echec.get("categorie") or "")
    if nature in _NATURES_APPLICATION:
        return APPLICATION
    if nature in _NATURES_ENVIRONNEMENT:
        return ENVIRONNEMENT
    resultat = _PAR_CATEGORIE.get(existante, INCERTAIN)
    if resultat == AGENT and _TIMEOUT.search(str(echec.get("message") or "")):
        return INCERTAIN          # une correction proposée sur un délai dépassé n'est pas prouvée
    return resultat


def classer(analysis: dict) -> list:
    """Échecs d'une analyse d'import, chacun avec sa catégorie de boucle (`categorie_boucle`)."""
    echecs = [dict(e) for e in analysis.get("echecs") or []]
    vus = {e.get("id") for e in echecs}
    for identifiant, resultat in (analysis.get("resultats") or {}).items():
        if resultat.get("statut") != "passe" and identifiant not in vus:
            fichier, titre = identifiant.split("::", 1) if "::" in identifiant else ("", identifiant)
            echecs.append({"id": identifiant, "fichier": fichier, "titre": titre, "step": resultat.get("step", ""),
                           "message": resultat.get("message", ""), "categorie": "", "nature": "",
                           "cause": "échec non classé par l'analyse"})
    init = analysis.get("init_en_echec") or {}
    for echec in echecs:
        echec["categorie_boucle"] = ENVIRONNEMENT if init else categorie(echec)
    return echecs


def a_envoyer(echecs: list) -> list:
    return [e for e in echecs if e.get("categorie_boucle") in A_ENVOYER]


def par_categorie(echecs: list) -> dict:
    compte = {c: 0 for c in CATEGORIES}
    for e in echecs:
        compte[e.get("categorie_boucle", INCERTAIN)] = compte.get(e.get("categorie_boucle", INCERTAIN), 0) + 1
    return compte


def echoues(analysis: dict) -> set:
    return {i for i, r in (analysis.get("resultats") or {}).items() if r.get("statut") != "passe"}


def passes(analysis: dict) -> set:
    return {i for i, r in (analysis.get("resultats") or {}).items() if r.get("statut") == "passe"}


def regressions(precedente: dict, courante: dict, perimetre: set = None) -> list:
    """Scénarios qui passaient au run précédent et échouent maintenant (dans le périmètre, s'il est donné)."""
    avant = passes(precedente)
    if perimetre is not None:
        avant &= perimetre
    return sorted(avant & echoues(courante))


# --- contexte d'un échec ------------------------------------------------------------------------------------------
_ANNOTATION = re.compile(r"@(Given|When|Then|And|But|Etantdonn[ée]|Soit|Quand|Lorsque|Alors|Et|Mais)\s*\(\s*\"((?:[^\"\\]|\\.)*)\"")
_MOT_CLE = re.compile(r"^\s*(?:Given|When|Then|And|But|\*|[ÉE]tant donn[ée]e?s?(?: que| qu')?|Soit|Quand|Lorsque|"
                      r"Alors|Et|Mais)\s+", re.I)
_PARAMETRES = {"{int}": r"-?\d+", "{float}": r"-?[\d.,]+", "{word}": r"\S+", "{string}": r"(?:\"[^\"]*\"|'[^']*')",
               "{}": r".*", "{bigdecimal}": r"-?[\d.,]+", "{long}": r"-?\d+", "{double}": r"-?[\d.,]+"}


def _expression(texte: str) -> re.Pattern:
    texte = texte.encode("utf-8").decode("unicode_escape") if "\\\\" in texte else texte.replace('\\"', '"')
    if texte.startswith("^") or texte.endswith("$"):
        try:
            return re.compile(texte)
        except re.error:
            return re.compile(re.escape(texte))
    morceaux = re.split(r"(\{\w*\})", texte)
    motif = "".join(_PARAMETRES.get(m, r".*") if re.fullmatch(r"\{\w*\}", m) else re.escape(m) for m in morceaux)
    return re.compile(f"^{motif}$")


def step_definition(worktree: str, step: str, limite_fichiers: int = 2000) -> dict:
    """Step definition Java (fichier, ligne, extrait) qui correspond au texte du step en échec ; {} si introuvable."""
    texte = _MOT_CLE.sub("", step or "", count=1).strip()
    racine = os.path.join(worktree or "", "src", "test")
    if not texte or not os.path.isdir(racine):
        return {}
    vus = 0
    for dossier, _, fichiers in os.walk(racine):
        for nom in fichiers:
            if not nom.endswith(".java"):
                continue
            vus += 1
            if vus > limite_fichiers:
                return {}
            chemin = os.path.join(dossier, nom)
            try:
                with open(chemin, encoding="utf-8", errors="replace") as f:
                    lignes = f.read().splitlines()
            except OSError:
                continue
            for n, ligne in enumerate(lignes):
                for m in _ANNOTATION.finditer(ligne):
                    if _expression(m.group(2)).match(texte):
                        return {"fichier": os.path.relpath(chemin, worktree).replace(os.sep, "/"), "ligne": n + 1,
                                "extrait": "\n".join(lignes[n:n + 15])[:1500]}
    return {}


_SYMBOLE_APPLICATIF = re.compile(r"(?<![\w/])(/(?:api|rest|ws)/[\w/{}.-]+)|\b([A-Z]\w+(?:Service|Controller|Resource|"
                                 r"Repository|Exception|Manager|Dao))\b")


def code_applicatif(client_root: str, message: str, limite_fichiers: int = 4000, max_extraits: int = 2) -> list:
    """Extraits du code applicatif cités par le message d'erreur (route REST ou classe), au mieux, bornés."""
    if not client_root or not os.path.isdir(client_root):
        return []
    symboles = []
    for route, classe in _SYMBOLE_APPLICATIF.findall(message or ""):
        symbole = route or classe
        if symbole and symbole not in symboles:
            symboles.append(symbole)
    if not symboles:
        return []
    extraits, vus = [], 0
    for dossier, sous, fichiers in os.walk(client_root):
        sous[:] = [d for d in sous if d not in (".git", "target", "node_modules", "build")]
        for nom in fichiers:
            if not nom.endswith((".java", ".xml", ".properties")):
                continue
            vus += 1
            if vus > limite_fichiers or len(extraits) >= max_extraits:
                return extraits
            chemin = os.path.join(dossier, nom)
            try:
                with open(chemin, encoding="utf-8", errors="replace") as f:
                    lignes = f.read().splitlines()
            except OSError:
                continue
            for n, ligne in enumerate(lignes):
                trouve = next((s for s in symboles if s in ligne), "")
                if trouve:
                    extraits.append({"fichier": os.path.relpath(chemin, client_root).replace(os.sep, "/"),
                                     "ligne": n + 1, "symbole": trouve,
                                     "extrait": "\n".join(lignes[max(0, n - 3):n + 12])[:1500]})
                    break
    return extraits


# --- demande ------------------------------------------------------------------------------------------------------
def empreintes_prompts(dossier_prompts: str) -> list:
    """Prompts de l'agent utilisés par cette génération : nom et empreinte (le contenu est dans le dépôt)."""
    out = []
    if not os.path.isdir(dossier_prompts):
        return out
    for nom in sorted(os.listdir(dossier_prompts)):
        if nom.endswith(".md"):
            with open(os.path.join(dossier_prompts, nom), "rb") as f:
                out.append({"nom": nom[:-3], "empreinte": hashlib.sha1(f.read()).hexdigest()[:12]})
    return out


_LITTERAL = re.compile(r"[\"'«<]\s*([\w][\w .:/-]{3,60}?)\s*[\"'»>]")
_MOTS_COURANTS = {"null", "true", "false", "expected", "but was", "error", "erreur", "le", "la", "les", "the"}


def marqueurs_interdits(echecs: list, projet: str, fonctionnalite: str) -> list:
    """Chaînes propres à cette fonctionnalité qui ne doivent pas apparaître en dur dans le code de l'agent : client,
    spécifiques, titres de scénarios, noms de features, valeurs littérales des messages d'erreur."""
    marqueurs = [projet] + [s.strip() for s in re.split(r"[,;]", fonctionnalite or "") if s.strip()]
    for e in echecs:
        marqueurs.append(str(e.get("titre") or ""))
        fichier = str(e.get("fichier") or "")
        if fichier:
            marqueurs.append(os.path.splitext(os.path.basename(fichier))[0])
        marqueurs += _LITTERAL.findall(str(e.get("message") or ""))
    out = []
    for m in marqueurs:
        m = " ".join(str(m).split())
        if len(m) >= 4 and m.lower() not in _MOTS_COURANTS and not m.isdigit() and m not in out:
            out.append(m)
    return out[:80]


_SECRET_NOMME = re.compile(r"(?i)\b((?:[\w-]*token|password|passwd|pwd|secret|api[_-]?key|authorization)"
                           r"[\"']?\s*[=:]\s*[\"']?(?:Bearer\s+|Basic\s+)?)[^\s\"',;&]+")


def _masque(texte) -> str:
    """Secrets masqués : valeurs connues de l'environnement (socle), puis toute valeur nommée « token=… »,
    « password: … », « Authorization: Bearer … »."""
    texte = str(texte or "")
    try:
        from agent_socle.secret_tools import mask_secrets
        texte = mask_secrets(texte)[0]
    except Exception:  # noqa: BLE001 — sans socle : masquage par motif seul
        pass
    return _SECRET_NOMME.sub(r"\1***", texte)


def masquer(valeur):
    """Masquage récursif d'une structure JSON (chaînes seulement)."""
    if isinstance(valeur, str):
        return _masque(valeur)
    if isinstance(valeur, list):
        return [masquer(v) for v in valeur]
    if isinstance(valeur, dict):
        return {k: masquer(v) for k, v in valeur.items()}
    return valeur


def echec_pour_demande(echec: dict, trace: str = "", definition: dict = None, applicatif: list = None) -> dict:
    return {"id": echec.get("id", ""), "feature": echec.get("fichier", ""), "scenario": echec.get("titre", ""),
            "step": echec.get("step", ""), "message": _masque(echec.get("message", ""))[:600],
            "trace": _masque(trace)[:4000], "step_definition": definition or {},
            "code_applicatif": applicatif or [], "categorie": echec.get("categorie_boucle", INCERTAIN),
            "nature": echec.get("nature", ""), "cause": _masque(echec.get("cause", ""))[:400],
            "signale_incertain": echec.get("categorie_boucle") == INCERTAIN}


def construire_demande(generation: str, iteration: int, iterations_max: int, projet: str, fonctionnalite: str,
                       echecs: list, fichiers_generes: list, prompts: list, commit_agent: str = "",
                       historique: list = None, annuler: dict = None) -> dict:
    """Demande structurée envoyée à dev-tool (contrat version 1, CLAUDE.md § 6). `echecs` : déjà au format
    echec_pour_demande, AGENT et INCERTAIN seulement."""
    if iteration < 1 or iteration > iterations_max:
        raise ValueError(f"itération {iteration} hors de 1..{iterations_max}")
    envoyes = [e for e in echecs if e.get("categorie") in A_ENVOYER]
    if not envoyes and not annuler:
        raise ValueError("aucun échec AGENT ou INCERTAIN à envoyer, ni commit à annuler")
    return {"version": VERSION_CONTRAT, "type": TYPE_DEMANDE, "depot": DEPOT, "generation": generation,
            "iteration": iteration, "iterations_max": iterations_max, "projet": projet,
            "fonctionnalite": fonctionnalite, "echecs": envoyes, "fichiers_generes": sorted(set(fichiers_generes)),
            "prompts": prompts, "commit_agent": commit_agent, "historique": historique or [],
            "annuler": annuler or None,
            "marqueurs_interdits": marqueurs_interdits([{"titre": e["scenario"], "fichier": e["feature"],
                                                         "message": e["message"]} for e in envoyes],
                                                       projet, fonctionnalite),
            "regles": list(REGLES)}


def demande_texte(demande: dict) -> str:
    """Demande « prête à coller » dans l'onglet Développer de dev-tool (relance du manager, bornée)."""
    lignes = [f"Boucle de correction {demande['generation']} (itération {demande['iteration']}/"
              f"{demande['iterations_max']}) : corriger l'agent cucumber (code et prompts) pour que la génération "
              f"de {demande['projet']} / {demande['fonctionnalite'] or 'fonctionnalité'} réussisse, sans toucher "
              f"aux tests ni coder en dur cette fonctionnalité."]
    for e in demande["echecs"][:5]:
        lignes.append(f"- [{e['categorie']}] {e['scenario']} — {e['step']} : {e['message'][:160]}")
    return "\n".join(lignes)


# --- décisions ----------------------------------------------------------------------------------------------------
def decider(iteration: int, iterations_max: int, avant: int, apres: int, restants_agent: int,
            reponse_statut: str = "corrige") -> tuple:
    """(état, raison) après une itération : `avant` / `apres` : nombre d'échecs (toutes catégories) du run précédent
    et de ce run ; `restants_agent` : échecs AGENT/INCERTAIN restants."""
    if restants_agent == 0:
        return TERMINEE, ("tous les scénarios passent" if apres == 0
                          else "plus aucun échec dû à l'agent (restent des échecs APPLICATION / ENVIRONNEMENT)")
    if reponse_statut in ("impossible", "refuse", "erreur"):
        return ABANDONNEE, f"dev-tool n'a rien fusionné ({reponse_statut})"
    if apres >= avant:
        return ABANDONNEE, f"aucun échec en moins à l'itération {iteration} ({avant} → {apres})"
    if iteration >= iterations_max:
        return ABANDONNEE, f"limite de {iterations_max} itération(s) atteinte"
    return EN_COURS, ""


# --- anti-triche --------------------------------------------------------------------------------------------------
_SCENARIO = re.compile(r"^\s*(Scenario Outline|Scenario Template|Scenario|Example|Sc[ée]nario|Plan du sc[ée]nario|"
                       r"Mod[eè]le du sc[ée]nario)\s*:\s*(.*\S)\s*$", re.I)
_SCENARIO_COMMENTE = re.compile(r"^\s*#+\s*(Scenario|Example|Sc[ée]nario|Plan du sc[ée]nario)\b[^:]*:", re.I)
_TAGS_DESACTIVANTS = re.compile(r"@(ignore|ignored|disabled?|skip|skipped|wip|manual|desactive|désactivé|"
                                r"MODULE_EXCLU)\b", re.I)
_ASSERTION_GHERKIN = re.compile(r"^\s*(Then|Alors)\b", re.I)
_SUITE = re.compile(r"^\s*(And|But|Et|Mais|\*)\b", re.I)
_ETAPE = re.compile(r"^\s*(Given|When|[ÉE]tant donn|Soit|Quand|Lorsque)\b", re.I)
_CATCH_VIDE = re.compile(r"catch\s*\([^)]*\)\s*\{\s*(?://[^\n]*)?\s*\}")
# catch d'une erreur d'assertion ou générique dont le bloc ne relance rien (journal ou commentaire seuls)
_CATCH_AVALE = re.compile(r"catch\s*\(\s*(?:final\s+)?(?:Exception|Throwable|RuntimeException|AssertionError|Error)\b"
                          r"[^)]*\)\s*\{(?:(?!throw|fail\s*\(|assert)[^}])*\}")
_ASSERT_JAVA = re.compile(r"\b(assert\w*|fail|verify\w*|should\w*)\s*\(")
DOSSIER_TESTS = "src/test/"


def scenarios(texte: str) -> dict:
    """{titre: {"tags": set, "assertions": int, "commente": False}} d'une feature (scénarios actifs), plus les titres
    commentés sous la clé spéciale « # » (ensemble)."""
    out, commentes, tags, courant, dans_then = {}, set(), set(), None, False
    for ligne in (texte or "").splitlines():
        brut = ligne.strip()
        m = _SCENARIO.match(ligne)
        if m:
            courant = m.group(2).strip()
            out[courant] = {"tags": set(tags), "assertions": 0}
            tags, dans_then = set(), False
            continue
        if _SCENARIO_COMMENTE.match(ligne):
            commentes.add(brut.lstrip("#").split(":", 1)[-1].strip())
            continue
        if brut.startswith("@"):
            tags |= {t for t in brut.split() if t.startswith("@")}
            continue
        if courant is None:
            continue
        if _ASSERTION_GHERKIN.match(ligne):
            out[courant]["assertions"] += 1
            dans_then = True
        elif _SUITE.match(ligne) and dans_then:
            out[courant]["assertions"] += 1
        elif _ETAPE.match(ligne):
            dans_then = False
    out["#"] = commentes
    return out


def _ajoutees(avant: str, apres: str) -> list:
    import difflib
    return [l[1:] for l in difflib.unified_diff((avant or "").splitlines(), (apres or "").splitlines(), lineterm="", n=0)
            if l.startswith("+") and not l.startswith("+++")]


def _retirees(avant: str, apres: str) -> list:
    import difflib
    return [l[1:] for l in difflib.unified_diff((avant or "").splitlines(), (apres or "").splitlines(), lineterm="", n=0)
            if l.startswith("-") and not l.startswith("---")]


def controler_regeneration(avant: dict, apres: dict, partagees=()) -> dict:
    """
    Contrôle anti-triche de la régénération : `avant` / `apres` = {chemin relatif: texte} des fichiers du worktree
    touchés (absent = fichier inexistant). Renvoie {"violations": [{fichier, regle, detail}], "signalements": [...]}.
    Une violation fait rétablir le fichier ; un signalement (step definition partagée modifiée) va dans le rapport.
    """
    violations, signalements = [], []
    partagees = set(partagees or ())

    def viole(fichier, regle, detail):
        violations.append({"fichier": fichier, "regle": regle, "detail": detail[:300]})

    for rel in sorted(set(avant) | set(apres)):
        texte_avant, texte_apres = avant.get(rel), apres.get(rel)
        if not rel.replace("\\", "/").startswith(DOSSIER_TESTS):
            viole(rel, "code_application", "fichier hors des tests (code de l'application testée)")
            continue
        if rel.endswith(".feature"):
            if texte_avant is not None and texte_apres is None:
                viole(rel, "scenario_supprime", "feature supprimée")
                continue
            sa, sp = scenarios(texte_avant or ""), scenarios(texte_apres or "")
            commentes_avant, commentes_apres = sa.pop("#"), sp.pop("#")
            for titre in sorted(set(sa) - set(sp)):
                viole(rel, "scenario_commente" if titre in commentes_apres else "scenario_supprime", titre)
            for titre in sorted(commentes_apres - commentes_avant - set(sa)):
                viole(rel, "scenario_commente", titre)
            for titre, infos in sp.items():
                nouveaux = {t for t in infos["tags"] - sa.get(titre, {}).get("tags", set())
                            if _TAGS_DESACTIVANTS.fullmatch(t)}
                if nouveaux:
                    viole(rel, "scenario_desactive", f"{titre} : {', '.join(sorted(nouveaux))}")
                if titre in sa and infos["assertions"] < sa[titre]["assertions"]:
                    viole(rel, "assertion_affaiblie", f"{titre} : {sa[titre]['assertions']} → "
                                                      f"{infos['assertions']} vérification(s)")
        elif rel.endswith(".java"):
            ajoutees = _ajoutees(texte_avant, texte_apres)
            bloc = "\n".join(ajoutees)
            if _CATCH_VIDE.search(bloc) or _CATCH_AVALE.search(bloc):
                viole(rel, "erreur_avalee", "try/catch qui avale l'erreur")
            retirees = sum(1 for l in _retirees(texte_avant, texte_apres) if _ASSERT_JAVA.search(l))
            ajout = sum(1 for l in ajoutees if _ASSERT_JAVA.search(l))
            if retirees > ajout:
                viole(rel, "assertion_affaiblie", f"{retirees} vérification(s) retirée(s), {ajout} ajoutée(s)")
            if texte_avant is not None and texte_apres != texte_avant and rel in partagees:
                signalements.append({"fichier": rel, "regle": "step_partagee_modifiee",
                                     "detail": "step definition partagée existante modifiée"})
    return {"violations": violations, "signalements": signalements}


# --- rapport ------------------------------------------------------------------------------------------------------
LIBELLES = {EN_COURS: "en cours", TERMINEE: "terminée", ABANDONNEE: "abandonnée"}


def rapport_markdown(boucle: dict) -> str:
    """Rapport final (et intermédiaire) de la boucle."""
    etat = LIBELLES.get(boucle.get("etat"), boucle.get("etat", ""))
    lignes = [f"# Boucle de correction {boucle['generation']}", "",
              f"- Projet : {boucle.get('projet', '')} · fonctionnalité : {boucle.get('fonctionnalite') or '—'}",
              f"- État : **{etat}** (itération {boucle.get('iteration', 0)}/{boucle.get('iterations_max', 0)})"
              + (f" — {boucle['raison']}" if boucle.get("raison") else ""),
              f"- Coût : {boucle.get('cout_usd', 0.0):.2f} $ (dev-tool {boucle.get('cout_devtool_usd', 0.0):.2f} $, "
              f"agent cucumber {boucle.get('cout_cucumber_usd', 0.0):.2f} $)", ""]
    final = boucle.get("final") or {}
    if final:
        lignes += ["## Résultat", "", f"- Scénarios passés : {final.get('passes', 0)}",
                   f"- Échecs restants : {final.get('echecs', 0)}"]
        for cat, n in (final.get("par_categorie") or {}).items():
            if n:
                lignes.append(f"  - {cat} : {n}")
        for e in final.get("restants") or []:
            lignes.append(f"  - [{e['categorie']}] {e['id']} — {e.get('cause', '')[:200]}")
        lignes.append("")
    lignes += ["## Itérations", ""]
    for it in boucle.get("iterations") or []:
        rep = it.get("reponse") or {}
        lignes.append(f"### Itération {it['numero']}")
        lignes.append(f"- Échecs envoyés : {it.get('envoyes', 0)} · statut dev-tool : {rep.get('statut', '—')}")
        if rep.get("cause"):
            lignes.append(f"- Cause : {rep['cause']}")
        if rep.get("commit"):
            lignes.append(f"- Correction fusionnée sur main : `{rep['commit']}` ({', '.join(rep.get('fichiers') or [])})")
        for a in rep.get("annulations") or []:
            lignes.append(f"- Retour arrière : `{a.get('commit', '')}` annulé par `{a.get('revert', '')}` "
                          f"({a.get('raison', '')})")
        if rep.get("raison"):
            lignes.append(f"- Raison : {rep['raison']}")
        for v in it.get("anti_triche") or []:
            lignes.append(f"- ⛔ Anti-triche : {v['fichier']} — {v['regle']} ({v['detail']}) : fichier rétabli")
        for s in it.get("signalements") or []:
            lignes.append(f"- ⚠️ {s['fichier']} : {s['detail']}")
        if it.get("regressions"):
            lignes.append(f"- Régressions : {', '.join(it['regressions'])}")
        if it.get("echecs_apres") is not None:
            lignes.append(f"- Échecs : {it.get('echecs_avant')} → {it.get('echecs_apres')}")
        lignes.append("")
    return "\n".join(lignes) + "\n"
