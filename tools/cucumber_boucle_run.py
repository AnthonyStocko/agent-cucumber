"""
Enchaînement de la boucle de correction autonome (CLAUDE.md § 6), dans un processus détaché lancé à la fin d'un run
Jenkins (`declencher`) : `main.py --step generate-cucumber-client --client-name <c> --boucle-correction
--from-import <n>`.

Chaque étape qui écrit (régénération, run Jenkins) est un NOUVEAU processus main.py : il recharge le code et les
prompts corrigés par dev-tool et prend lui-même le verrou du client ; la boucle ne le prend pas, elle attend qu'il
soit libre. Le run Jenkins attend tout build Cucumber en cours (cucumber_run.launch : un seul job à la fois).

Les actions concrètes sont dans `Operations` (git, sous-processus, API de dev-tool), remplaçable dans les tests ;
`executer` ne contient que l'enchaînement et les décisions (cucumber_boucle).
"""
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from tools import cucumber_boucle as cb

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Options d'un run qui ne se transmettent pas aux étapes de la boucle (elle les pose elle-même)
_OPTIONS_RUN = {"--run-jenkins": 0, "--run-dry": 0, "--run-no-push": 0, "--run-branch": 1, "--run-tags": 1,
                "--complete": 0, "--from-import": 1, "--boucle-correction": 0, "--resume": 0, "--reprise": 0,
                "--import-url": 1, "--max-lots": 1, "--specifics": 1}


def argv_de_base(argv: list) -> list:
    """Arguments de la commande d'origine sans ses options de run (client, dépôts, projet… conservés)."""
    out, i = [], 0
    while i < len(argv):
        option = argv[i].split("=", 1)[0]
        if option in _OPTIONS_RUN:
            i += 1 + (_OPTIONS_RUN[option] if "=" not in argv[i] else 0)
            continue
        out.append(argv[i])
        i += 1
    return out


def identifiant(client: str, numero: int, maintenant: datetime = None) -> str:
    return f"{client}-{numero}-{(maintenant or datetime.now()).strftime('%Y%m%d-%H%M%S')}"


def dossier(client: str) -> str:
    from tools import cucumber_tools
    chemin = os.path.join(cucumber_tools.cache_dir(client), "boucles")
    os.makedirs(chemin, exist_ok=True)
    return chemin


# --- actions concrètes --------------------------------------------------------------------------------------------
class Operations:
    def __init__(self, client: str, argv: list, generation: str, client_root: str = "", journal_processus=None):
        from tools import cucumber_tools
        self.client, self.argv, self.generation = client, argv, generation
        self.client_root = client_root
        self.worktree = cucumber_tools.worktree_dir(client)
        self.dossier = dossier(client)
        self.sortie = journal_processus or os.path.join(self.dossier, f"{generation}.log")

    # analyses
    def analyse(self, numero: int) -> dict:
        from tools import cucumber_import
        return cucumber_import.load_analysis(self.client, numero)

    def dernier_import(self) -> int:
        from tools import cucumber_import
        return max((e["numero"] for e in cucumber_import.load_index(self.client).get("imports", [])), default=0)

    def defauts_agent(self) -> list:
        return defauts_agent(self.client)

    def scenarios_agent(self) -> dict:
        from tools import cucumber_import, cucumber_tools
        return cucumber_import.agent_scenarios(cucumber_tools.load_state(self.client))

    # git du worktree client
    def _git(self, *args, dossier: str = "") -> str:
        sortie = subprocess.run(["git", "-C", dossier or self.worktree, *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        return sortie.stdout.strip() if sortie.returncode == 0 else ""

    def head(self) -> str:
        return self._git("rev-parse", "HEAD")

    def fichiers_modifies(self, depuis: str) -> list:
        noms = set(self._git("diff", "--name-only", depuis, "HEAD").splitlines()) if depuis else set()
        noms |= {l[3:].strip() for l in self._git("status", "--porcelain").splitlines() if len(l) > 3}
        return sorted(n.replace("\\", "/") for n in noms if n)

    def lire(self, rels: list, commit: str = "") -> dict:
        out = {}
        for rel in rels:
            if commit:
                sortie = subprocess.run(["git", "-C", self.worktree, "show", f"{commit}:{rel}"], capture_output=True)
                out[rel] = sortie.stdout.decode("utf-8", "replace") if sortie.returncode == 0 else None
            else:
                chemin = os.path.join(self.worktree, *rel.split("/"))
                try:
                    with open(chemin, encoding="utf-8", errors="replace") as f:
                        out[rel] = f.read()
                except OSError:
                    out[rel] = None
        return out

    def retablir(self, rels: list, commit: str, raison: str) -> None:
        """Fichiers rétablis dans leur état d'avant la régénération (anti-triche), commit dédié."""
        for rel in rels:
            if self.lire([rel], commit)[rel] is None:
                self._git("rm", "-q", "-f", "--", rel)
            else:
                self._git("checkout", commit, "--", rel)
        self._git("add", "-A", "--", *rels)
        self._git("commit", "-q", "-m", f"Cucumber : régénération rétablie (anti-triche) — {raison}"[:200])

    def steps_partagees(self) -> set:
        return {f for f in self._git("ls-files", "src/test/java").splitlines() if f.endswith(".java")}

    def fichiers_generes(self) -> list:
        from tools import cucumber_tools
        etat = cucumber_tools.load_state(self.client)
        return sorted({f for lot in etat.get("lots", []) for f in (lot.get("fichiers") or []) if isinstance(f, str)})

    # agent-cucumber lui-même
    def commit_agent(self) -> str:
        return self._git("rev-parse", "HEAD", dossier=RACINE)

    def mettre_a_jour_agent(self) -> tuple:
        """Copie locale d'agent-cucumber amenée sur origin/main (avance rapide seule, copie propre et sur main)."""
        self._git("fetch", "-q", "origin", dossier=RACINE)
        branche = self._git("rev-parse", "--abbrev-ref", "HEAD", dossier=RACINE)
        if branche != "main":
            return False, (f"copie locale d'agent-cucumber sur « {branche or '?'} » : la correction est sur main mais "
                           f"n'est pas chargée")
        if self._git("status", "--porcelain", "--untracked-files=no", dossier=RACINE):
            return False, "copie locale d'agent-cucumber modifiée : la correction n'est pas chargée"
        sortie = subprocess.run(["git", "-C", RACINE, "merge", "--ff-only", "-q", "origin/main"], capture_output=True,
                                text=True)
        if sortie.returncode != 0:
            return False, f"mise à jour d'agent-cucumber impossible : {(sortie.stderr or '').strip()[:200]}"
        return True, self.commit_agent()

    # étapes (nouveaux processus)
    def attendre_verrou(self, delai: float = 6 * 3600.0, pas: float = 30.0) -> bool:
        from tools import cucumber_lock
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if not cucumber_lock.holder(self.client):
                return True
            time.sleep(pas)
        return False

    def _etape(self, options: list) -> int:
        if not self.attendre_verrou():
            return 3
        env = {**os.environ, "CUCUMBER_BOUCLE_ID": self.generation, "PYTHONUNBUFFERED": "1"}
        with open(self.sortie, "a", encoding="utf-8") as sortie:
            sortie.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} main.py {' '.join(options)}\n")
            sortie.flush()
            return subprocess.run([sys.executable, os.path.join(RACINE, "main.py"), *self.argv, *options],
                                  stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env).returncode

    def reprendre(self) -> int:
        """Lots restés en erreur (fichiers, compilation) repris avec l'agent corrigé : correction et vérification."""
        return self._etape(["--resume"])

    def regenerer(self, numero: int) -> int:
        return self._etape(["--complete", "--from-import", str(numero)])

    def relancer(self, tags: str) -> int:
        avant = self.dernier_import()
        self._etape(["--run-jenkins"] + (["--run-tags", tags] if tags else []))
        apres = self.dernier_import()
        return apres if apres > avant else 0

    # dev-tool
    def devtool(self, demande: dict) -> dict:
        from tools.cucumber_devtool import ClientDevTool, DevToolErreur
        try:
            return ClientDevTool().demander(demande)
        except DevToolErreur as e:
            return {"statut": "erreur", "raison": str(e)}

    def cout_cucumber(self, depuis: str) -> float:
        from agent_socle.chemins import DATA_DIR
        from tools import cucumber_tools
        chemin, total = os.path.join(DATA_DIR, ".tmp", "token_usage.csv"), 0.0
        cle, depuis = cucumber_tools.work_id(self.client), depuis.replace("T", " ")
        try:
            with open(chemin, encoding="utf-8", newline="") as f:
                for ligne in csv.DictReader(f, delimiter=";"):
                    if ligne.get("ticket") == cle and str(ligne.get("date", "")).replace("T", " ") >= depuis:
                        try:
                            total += float(str(ligne.get("cout_usd") or 0).replace(",", "."))
                        except ValueError:
                            pass
        except OSError:
            pass
        return total


# --- persistance et journal ---------------------------------------------------------------------------------------
def enregistrer(boucle: dict, chemin_dossier: str) -> None:
    boucle["mis_a_jour"] = datetime.now().isoformat(timespec="seconds")
    base = os.path.join(chemin_dossier, boucle["generation"])
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(boucle, f, ensure_ascii=False, indent=2)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(cb.rapport_markdown(boucle))


def journaliser(chemin_dossier: str, generation: str, sens: str, contenu: dict) -> None:
    """Échange entre agents (une ligne JSON), secrets masqués ; relu par le manager."""
    ligne = {"date": datetime.now().isoformat(timespec="seconds"), "generation": generation, "sens": sens,
             "contenu": cb.masquer(contenu)}
    with open(os.path.join(chemin_dossier, f"{generation}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")


# --- enchaînement -------------------------------------------------------------------------------------------------
def _details(ops, echecs: list, analyse: dict) -> list:
    """Échecs AGENT / INCERTAIN au format de la demande (trace, step definition, code applicatif)."""
    resultats = analyse.get("resultats") or {}
    out = []
    for e in cb.a_envoyer(echecs):
        resultat = resultats.get(e.get("id"), {})
        out.append(cb.echec_pour_demande(
            e, trace=e.get("trace") or resultat.get("journal") or resultat.get("message") or "",
            definition=cb.step_definition(ops.worktree, e.get("step", "")),
            applicatif=cb.code_applicatif(ops.client_root, str(resultat.get("journal") or e.get("message", "")))))
    return out


def tags_feature(scenarios_agent: dict, ids: list, fonctionnalite: str) -> str:
    """Expression de tags d'un run couvrant la feature entière : tous les scénarios de l'agent des features en échec
    et des spécifiques de la fonctionnalité (échecs compris). Vide : tous les scénarios actifs."""
    fichiers = {i.split("::", 1)[0] for i in ids if "::" in i}
    specs = {s.strip() for s in (fonctionnalite or "").split(",") if s.strip()}
    tags = sorted({v["tag"] for i, v in scenarios_agent.items() if v.get("tag") and (
        i.split("::", 1)[0] in fichiers or (v.get("spec") and v["spec"] in specs) or i in ids)})
    return " or ".join(tags)


def _historique(boucle: dict) -> list:
    return [{"iteration": it["numero"], "statut": (it.get("reponse") or {}).get("statut", ""),
             "commit": (it.get("reponse") or {}).get("commit", ""), "cause": (it.get("reponse") or {}).get("cause", ""),
             "raison": (it.get("reponse") or {}).get("raison", ""), "echecs_avant": it.get("echecs_avant"),
             "echecs_apres": it.get("echecs_apres"), "regressions": it.get("regressions") or []}
            for it in boucle["iterations"]]


def executer(ops, client: str, numero: int, iterations_max: int, generation: str, fonctionnalite: str = "",
             chemin_dossier: str = "", ecrire=enregistrer, noter=journaliser) -> dict:
    """Boucle complète à partir de l'import `numero` ; renvoie l'état final de la boucle (aussi enregistré)."""
    debut = datetime.now().isoformat(timespec="seconds")
    analyse = ops.analyse(numero)
    lire_defauts = getattr(ops, "defauts_agent", None) or (lambda: [])
    defauts = lire_defauts()
    echecs = cb.classer(analyse, defauts)
    if not fonctionnalite:
        specs = ops.scenarios_agent()
        fonctionnalite = ",".join(sorted({specs.get(e["id"], {}).get("spec", "") for e in echecs} - {""}))
    boucle = {"generation": generation, "projet": client, "fonctionnalite": fonctionnalite, "etat": cb.EN_COURS,
              "iteration": 0, "iterations_max": iterations_max, "debut": debut, "import_initial": numero,
              "initial": {"echecs": len(cb.echoues(analyse)), "defauts_agent": len(defauts),
                          "par_categorie": cb.par_categorie(echecs)},
              "iterations": [], "corrections": [], "annulations": [], "signalements": [], "raison": "",
              "cout_devtool_usd": 0.0, "cout_cucumber_usd": 0.0, "cout_usd": 0.0}
    partagees = ops.steps_partagees()
    prompts = cb.empreintes_prompts(os.path.join(RACINE, "prompts"))
    dernier_commit, annuler, ids_initiaux = "", None, [e["id"] for e in echecs]

    def sauver():
        boucle["cout_cucumber_usd"] = round(ops.cout_cucumber(debut), 4)
        boucle["cout_usd"] = round(boucle["cout_devtool_usd"] + boucle["cout_cucumber_usd"], 4)
        ecrire(boucle, chemin_dossier)

    def demander(iteration: int, details: list, annulation) -> dict:
        demande = cb.construire_demande(generation, iteration, iterations_max, client, fonctionnalite, details,
                                        ops.fichiers_generes(), prompts, ops.commit_agent(), _historique(boucle),
                                        annulation)
        noter(chemin_dossier, generation, "cucumber→dev-tool", demande)
        reponse = ops.devtool(demande) or {}
        noter(chemin_dossier, generation, "dev-tool→cucumber", reponse)
        boucle["cout_devtool_usd"] = round(boucle["cout_devtool_usd"] + float(reponse.get("cout_usd") or 0.0), 4)
        for a in reponse.get("annulations") or []:
            boucle["annulations"].append({**a, "iteration": iteration})
        if reponse.get("commit"):
            boucle["corrections"].append({"iteration": iteration, "commit": reponse["commit"],
                                          "cause": reponse.get("cause", ""), "fichiers": reponse.get("fichiers") or [],
                                          "resume_diff": reponse.get("resume_diff", "")})
        return reponse

    sauver()
    for i in range(1, iterations_max + 1):
        details = _details(ops, echecs, analyse)
        if not details and not annuler:
            boucle["etat"], boucle["raison"] = cb.TERMINEE, "aucun échec AGENT ou INCERTAIN"
            break
        boucle["iteration"] = i
        it = {"numero": i, "import": numero, "envoyes": len(details),
              "echecs_avant": len(cb.echoues(analyse)) + len(defauts)}
        boucle["iterations"].append(it)
        sauver()
        reponse = demander(i, details, annuler)
        it["reponse"] = {k: reponse.get(k) for k in ("statut", "cause", "correction", "fichiers", "resume_diff",
                                                     "commit", "annulations", "raison", "cout_usd")}
        annuler = None
        statut = reponse.get("statut", "erreur")
        if reponse.get("commit"):
            dernier_commit = reponse["commit"]
        if statut in ("impossible", "erreur"):
            boucle["etat"], boucle["raison"] = cb.ABANDONNEE, (f"dev-tool : {statut}"
                                                               + (f" — {reponse['raison']}" if reponse.get("raison") else ""))
            break
        if statut in ("annule", "refuse") and not reponse.get("commit"):
            # Correction défaite par dev-tool (tests unitaires, anti-triche) : autre approche à l'itération suivante ;
            # un retour arrière fusionné est chargé tout de suite
            if reponse.get("annulations"):
                ops.mettre_a_jour_agent()
            if i >= iterations_max:
                boucle["etat"], boucle["raison"] = cb.ABANDONNEE, (f"limite de {iterations_max} itération(s) atteinte "
                                                                   f"(dernière correction : {statut})")
            continue
        ok, message = ops.mettre_a_jour_agent()
        if not ok:
            boucle["etat"], boucle["raison"] = cb.ABANDONNEE, message
            break
        avant_commit = ops.head()
        if defauts:
            # Lots restés en erreur à cause de l'agent : repris avec l'agent corrigé avant la régénération
            it["reprise_lots"] = ops.reprendre()
        if cb.a_envoyer([e for e in echecs if e.get("nature") != "defaut_agent"]):
            it["regeneration"] = ops.regenerer(numero)
        modifies = ops.fichiers_modifies(avant_commit)
        controle = cb.controler_regeneration(ops.lire(modifies, avant_commit), ops.lire(modifies), partagees)
        it["anti_triche"], it["signalements"] = controle["violations"], controle["signalements"]
        boucle["signalements"] += [{**s, "iteration": i} for s in controle["signalements"]]
        fautifs = sorted({v["fichier"] for v in controle["violations"]})
        if fautifs:
            ops.retablir(fautifs, avant_commit, "; ".join(f"{v['regle']} {v['detail']}"
                                                         for v in controle["violations"])[:150])
        tags = tags_feature(ops.scenarios_agent(), ids_initiaux, fonctionnalite)
        nouveau = ops.relancer(tags)
        if not nouveau:
            boucle["etat"], boucle["raison"] = cb.ABANDONNEE, "run Jenkins de vérification impossible (voir le journal)"
            break
        suivante = ops.analyse(nouveau)
        defauts_suivants = lire_defauts()
        echecs_suivants = cb.classer(suivante, defauts_suivants)
        for e in echecs_suivants:   # échec d'une feature rétablie par l'anti-triche : cause non prouvée
            if e.get("fichier") in fautifs and e["categorie_boucle"] == cb.AGENT:
                e["categorie_boucle"] = cb.INCERTAIN
        perimetre = set((suivante.get("resultats") or {}))
        avant = (len(cb.echoues(analyse) & perimetre) if perimetre else len(cb.echoues(analyse))) + len(defauts)
        apres = len(cb.echoues(suivante)) + len(defauts_suivants)
        regs = cb.regressions(analyse, suivante, perimetre)
        it.update(import_verification=nouveau, echecs_avant=avant, echecs_apres=apres, regressions=regs, tags=tags)
        if regs and dernier_commit:
            annuler = {"commit": dernier_commit, "raison": f"régression : {len(regs)} scénario(s) passaient avant "
                                                           f"cette correction ({', '.join(regs[:5])})"}
        etat, raison = cb.decider(i, iterations_max, avant, apres, len(cb.a_envoyer(echecs_suivants)), statut)
        analyse, echecs, numero, defauts = suivante, echecs_suivants, nouveau, defauts_suivants
        if etat != cb.EN_COURS:
            boucle["etat"], boucle["raison"] = etat, raison
            break
        sauver()
    else:
        if boucle["etat"] == cb.EN_COURS:
            boucle["etat"], boucle["raison"] = cb.ABANDONNEE, f"limite de {iterations_max} itération(s) atteinte"
    if annuler:      # la boucle s'arrête sur une régression : la correction fautive est défaite quand même
        reponse = demander(min(boucle["iteration"] or 1, iterations_max), [], annuler)
        boucle["iterations"][-1].setdefault("annulation_finale", reponse.get("statut"))
    restants = [{"id": e["id"], "categorie": e["categorie_boucle"], "cause": e.get("cause", "")} for e in echecs]
    boucle["final"] = {"import": numero, "passes": len(cb.passes(analyse)), "echecs": len(cb.echoues(analyse)),
                       "par_categorie": cb.par_categorie(echecs), "restants": restants}
    boucle["relance"] = bool(boucle["final"]["par_categorie"].get(cb.APPLICATION)) or (
        boucle["etat"] == cb.ABANDONNEE and bool(cb.a_envoyer(echecs)))
    if boucle["relance"] and cb.a_envoyer(echecs):
        try:
            boucle["demande_texte"] = cb.demande_texte(cb.construire_demande(
                generation, max(1, boucle["iteration"]), iterations_max, client, fonctionnalite,
                _details(ops, echecs, analyse), [], prompts))
        except ValueError:
            pass
    boucle["fin"] = datetime.now().isoformat(timespec="seconds")
    sauver()
    return boucle


# --- points d'entrée ----------------------------------------------------------------------------------------------
def defauts_agent(client: str) -> list:
    """Défauts de l'agent de la dernière génération du client ; [] si l'état est illisible (jamais bloquant)."""
    from tools import cucumber_agent_defects, cucumber_tools
    try:
        state = cucumber_tools.load_state(client)
        return cucumber_agent_defects.failures(state if isinstance(state, dict) else {})
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def declencher(client: str, argv: list, log=print, lancer=subprocess.Popen) -> str:
    """Fin d'un run Jenkins : lance la boucle (processus détaché) si des échecs AGENT ou INCERTAIN restent.
    Renvoie l'identifiant de la boucle, '' si elle n'est pas lancée."""
    if not cb.active() or cb.dans_boucle():
        return ""
    from tools import cucumber_import
    numero = max((e["numero"] for e in cucumber_import.load_index(client).get("imports", [])), default=0)
    if not numero:
        return ""
    defauts = defauts_agent(client)
    echecs = cb.classer(cucumber_import.load_analysis(client, numero), defauts)
    envoyes = cb.a_envoyer(echecs)
    if not envoyes:
        if echecs:
            log(f"[BOUCLE] {len(echecs)} échec(s), aucun dû à l'agent ({cb.par_categorie(echecs)}) : pas de boucle.")
        return ""
    generation = identifiant(client, numero)
    chemin = dossier(client)
    commande = [sys.executable, os.path.join(RACINE, "main.py"), *argv_de_base(argv), "--boucle-correction",
                "--from-import", str(numero)]
    options = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} \
        if sys.platform == "win32" else {"start_new_session": True}
    with open(os.path.join(chemin, f"{generation}.log"), "a", encoding="utf-8") as sortie:
        lancer(commande, stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
               env={**os.environ, "CUCUMBER_BOUCLE_GENERATION": generation}, cwd=os.getcwd(), **options)
    log(f"[BOUCLE] {len(envoyes)} échec(s) dû(s) à l'agent ou incertain(s)"
        + (f", dont {len(defauts)} défaut(s) de l'agent hors run (lots en erreur, constats)" if defauts else "")
        + " : boucle de correction autonome "
        f"{generation} lancée (au plus {cb.max_iterations()} itération(s)) ; rapport dans {chemin}.")
    return generation


def main(args) -> int:
    """`--boucle-correction --from-import <n>` : la boucle elle-même (sans verrou : ses étapes le prennent)."""
    client = args.client_name
    numero = args.from_import
    if not numero:
        from tools import cucumber_import
        numero = max((e["numero"] for e in cucumber_import.load_index(client).get("imports", [])), default=0)
    if not numero:
        print("[BOUCLE] Aucun import à corriger.")
        return 2
    generation = os.getenv("CUCUMBER_BOUCLE_GENERATION", "").strip() or identifiant(client, numero)
    root = args.client_repo if args.client_repo and os.path.isdir(args.client_repo) else \
        os.getenv("BITBUCKET_CLIENT_REPO_PATH", "")
    ops = Operations(client, argv_de_base(sys.argv[1:]), generation, root if os.path.isdir(root or "") else "")
    boucle = executer(ops, client, numero, cb.max_iterations(), generation, args.specifics.strip(), ops.dossier)
    print(f"[BOUCLE] {generation} {cb.LIBELLES[boucle['etat']]} après {boucle['iteration']} itération(s) : "
          f"{boucle['raison']} ; rapport : {os.path.join(ops.dossier, generation + '.md')}")
    return 0 if boucle["etat"] == cb.TERMINEE else 1
