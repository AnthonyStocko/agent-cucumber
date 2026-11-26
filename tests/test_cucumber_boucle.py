"""Boucle de correction autonome : classement, demande, limite d'itérations, arrêt sans progrès, retour arrière
automatique, refus des corrections interdites (anti-triche), transport vers dev-tool. Données fictives."""
import json
import os

import pytest

from tests.conftest import write
from tools import cucumber_boucle as cb
from tools import cucumber_boucle_run as run
from tools.cucumber_devtool import ClientDevTool, DevToolErreur


# --- classement ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("categorie,nature,message,attendu", [
    ("correction", "step_equivalent", "Undefined step", cb.AGENT),
    ("correction", "assertion", "expected <3> but was <2>", cb.AGENT),
    ("correction", "donnee_non_creee", "", cb.AGENT),
    ("correction", "technique", "Read timed out", cb.INCERTAIN),
    ("diagnostic", "mecanisme_ecriture", "", cb.INCERTAIN),
    ("produit", "bug_applicatif", "500 Internal Server Error", cb.APPLICATION),
    ("produit", "liste_choix_vide", "", cb.APPLICATION),
    ("environnement", "deploiement", "", cb.ENVIRONNEMENT),
    ("environnement", "conflit_verrouillage", "", cb.ENVIRONNEMENT),
    ("hors_depot", "hors_depot", "", cb.ENVIRONNEMENT),
    ("hors_perimetre", "hors_perimetre", "", cb.ENVIRONNEMENT),
    ("", "", "", cb.INCERTAIN),
])
def test_categorie(categorie, nature, message, attendu):
    assert cb.categorie({"categorie": categorie, "nature": nature, "message": message}) == attendu


def test_classer_init_en_echec_et_echecs_non_classes():
    analyse = {"resultats": {"a.feature::S1": {"statut": "echoue", "step": "Then x", "message": "m"},
                             "a.feature::S2": {"statut": "passe"}},
               "echecs": []}
    echecs = cb.classer(analyse)
    assert [(e["id"], e["categorie_boucle"]) for e in echecs] == [("a.feature::S1", cb.INCERTAIN)]
    analyse["init_en_echec"] = {"id": "init"}
    assert cb.classer(analyse)[0]["categorie_boucle"] == cb.ENVIRONNEMENT


def test_seuls_agent_et_incertain_sont_envoyes():
    echecs = [{"categorie_boucle": c} for c in cb.CATEGORIES]
    assert [e["categorie_boucle"] for e in cb.a_envoyer(echecs)] == [cb.AGENT, cb.INCERTAIN]


# --- demande ------------------------------------------------------------------------------------------------------
def _echec(i="features/a.feature::Créer une réception", cat=cb.AGENT, message="expected <RCP-0042> but was <>"):
    fichier, titre = i.split("::")
    return {"id": i, "fichier": fichier, "titre": titre, "step": "Then la réception est créée", "message": message,
            "categorie_boucle": cat, "nature": "assertion", "cause": "écart"}


def test_construire_demande_contrat():
    details = [cb.echec_pour_demande(_echec(), trace="at Step.java:12 password=hunter2"),
               cb.echec_pour_demande(_echec(cat=cb.APPLICATION))]
    demande = cb.construire_demande("gen-1", 1, 3, "projetx", "SPEC-1", details, ["b.feature", "a.feature"],
                                    [{"nom": "p", "empreinte": "x"}], "abc123")
    assert demande["version"] == 1 and demande["type"] == cb.TYPE_DEMANDE and demande["depot"] == "agent-cucumber"
    assert demande["iteration"] == 1 and demande["iterations_max"] == 3
    assert [e["categorie"] for e in demande["echecs"]] == [cb.AGENT]           # APPLICATION jamais envoyé
    assert demande["fichiers_generes"] == ["a.feature", "b.feature"]
    assert "hunter2" not in json.dumps(demande)                                 # secret masqué
    assert {"projetx", "SPEC-1", "Créer une réception", "RCP-0042"} <= set(demande["marqueurs_interdits"])
    assert demande["regles"] and demande["annuler"] is None


def test_construire_demande_refuse_iteration_hors_limite_ou_vide():
    details = [cb.echec_pour_demande(_echec())]
    with pytest.raises(ValueError):
        cb.construire_demande("g", 4, 3, "p", "", details, [], [])
    with pytest.raises(ValueError):
        cb.construire_demande("g", 1, 3, "p", "", [cb.echec_pour_demande(_echec(cat=cb.ENVIRONNEMENT))], [], [])
    assert cb.construire_demande("g", 1, 3, "p", "", [], [], [], annuler={"commit": "c", "raison": "r"})["annuler"]


def test_max_iterations(monkeypatch):
    monkeypatch.delenv("CUCUMBER_BOUCLE_MAX_ITERATIONS", raising=False)
    assert cb.max_iterations() == 3
    monkeypatch.setenv("CUCUMBER_BOUCLE_MAX_ITERATIONS", "5")
    assert cb.max_iterations() == 5
    monkeypatch.setenv("CUCUMBER_BOUCLE_MAX_ITERATIONS", "99")
    assert cb.max_iterations() == cb.ITERATIONS_PLAFOND
    monkeypatch.setenv("CUCUMBER_BOUCLE_MAX_ITERATIONS", "abc")
    assert cb.max_iterations() == 3


def test_step_definition(tmp_path):
    write(str(tmp_path / "src/test/java/steps/Recep.java"),
          'class R {\n  @Then("la réception {string} contient {int} lignes")\n  public void f(String a, int b) {}\n}\n')
    trouve = cb.step_definition(str(tmp_path), 'Then la réception "R1" contient 3 lignes')
    assert trouve["fichier"] == "src/test/java/steps/Recep.java" and trouve["ligne"] == 2
    assert cb.step_definition(str(tmp_path), "Then autre chose") == {}


# --- décisions ----------------------------------------------------------------------------------------------------
def test_decider():
    assert cb.decider(1, 3, 4, 0, 0)[0] == cb.TERMINEE
    assert cb.decider(1, 3, 4, 2, 0)[0] == cb.TERMINEE                        # restent APPLICATION / ENVIRONNEMENT
    assert cb.decider(1, 3, 4, 4, 2)[0] == cb.ABANDONNEE                      # aucun échec en moins
    assert cb.decider(1, 3, 4, 5, 2)[0] == cb.ABANDONNEE
    assert cb.decider(3, 3, 4, 2, 2)[0] == cb.ABANDONNEE                      # limite atteinte
    assert cb.decider(1, 3, 4, 2, 2)[0] == cb.EN_COURS
    assert cb.decider(1, 3, 4, 2, 2, "impossible")[0] == cb.ABANDONNEE


def test_regressions():
    avant = {"resultats": {"a": {"statut": "passe"}, "b": {"statut": "echoue"}, "c": {"statut": "passe"}}}
    apres = {"resultats": {"a": {"statut": "echoue"}, "b": {"statut": "passe"}, "c": {"statut": "passe"}}}
    assert cb.regressions(avant, apres) == ["a"]
    assert cb.regressions(avant, apres, {"c"}) == []


# --- anti-triche --------------------------------------------------------------------------------------------------
FEATURE = """Feature: Réception
  @agent_1
  Scenario: Créer
    Given une commande
    When je réceptionne
    Then la réception existe
    And le stock augmente
  @agent_2
  Scenario: Annuler
    Given une réception
    Then elle est annulée
"""
F = "src/test/resources/features/recep.feature"


def _regles(avant, apres, partagees=()):
    return {v["regle"] for v in cb.controler_regeneration(avant, apres, partagees)["violations"]}


def test_anti_triche_regeneration_honnete_acceptee():
    apres = FEATURE.replace("When je réceptionne", "When je réceptionne la commande")
    assert cb.controler_regeneration({F: FEATURE}, {F: apres}) == {"violations": [], "signalements": []}


@pytest.mark.parametrize("apres,regle", [
    (FEATURE.split("  @agent_2")[0], "scenario_supprime"),
    (FEATURE.replace("  Scenario: Annuler", "  # Scenario: Annuler"), "scenario_commente"),
    (FEATURE.replace("  @agent_2", "  @agent_2 @ignore"), "scenario_desactive"),
    (FEATURE.replace("    And le stock augmente\n", ""), "assertion_affaiblie"),
    (None, "scenario_supprime"),
])
def test_anti_triche_features(apres, regle):
    assert regle in _regles({F: FEATURE}, {F: apres})


def test_anti_triche_java_et_application():
    java = "src/test/java/steps/S.java"
    avant = "void f() {\n  assertEquals(1, x());\n}\n"
    assert "erreur_avalee" in _regles({java: avant}, {java: avant.replace(
        "  assertEquals(1, x());", "  try { assertEquals(1, x()); } catch (AssertionError e) { log(e); }")})
    assert "assertion_affaiblie" in _regles({java: avant}, {java: "void f() {\n  x();\n}\n"})
    assert "code_application" in _regles({"src/main/java/App.java": "a"}, {"src/main/java/App.java": "b"})
    resultat = cb.controler_regeneration({java: avant}, {java: avant + "// ok\n"}, partagees={java})
    assert resultat["violations"] == [] and resultat["signalements"][0]["regle"] == "step_partagee_modifiee"


# --- enchaînement -------------------------------------------------------------------------------------------------
def _analyse(resultats, echecs=None):
    return {"resultats": {i: {"statut": s, "step": "Then x", "message": "m"} for i, s in resultats.items()},
            "echecs": echecs if echecs is not None else [
                {"id": i, "fichier": i.split("::")[0], "titre": i.split("::")[1], "categorie": "correction",
                 "nature": "assertion", "message": "m", "step": "Then x"} for i, s in resultats.items() if s != "passe"]}


class FausseOps:
    worktree = client_root = ""

    def __init__(self, analyses, reponses, violations=None):
        self.analyses, self.reponses = analyses, list(reponses)
        self.demandes, self.retablis, self.suivant, self.violations = [], [], 1, violations or {}

    def analyse(self, numero):
        return self.analyses[numero]

    def scenarios_agent(self):
        return {i: {"tag": f"@agent_{n}", "spec": "SPEC-1"} for n, i in enumerate(self.analyses[1]["resultats"])}

    def steps_partagees(self):
        return set()

    def fichiers_generes(self):
        return ["f.feature"]

    def commit_agent(self):
        return "c0"

    def devtool(self, demande):
        self.demandes.append(demande)
        return self.reponses.pop(0) if self.reponses else {"statut": "impossible", "raison": "plus rien"}

    def mettre_a_jour_agent(self):
        return True, "c1"

    def head(self):
        return "h"

    def regenerer(self, numero):
        return 0

    def fichiers_modifies(self, depuis):
        return list(self.violations.get(self.suivant + 1, {}).get("apres", {}))

    def lire(self, rels, commit=""):
        cas = self.violations.get(self.suivant + 1, {})
        return {r: (cas["avant"] if commit else cas["apres"]).get(r) for r in rels}

    def retablir(self, rels, commit, raison):
        self.retablis.append(rels)

    def relancer(self, tags):
        self.suivant += 1
        return self.suivant if self.suivant in self.analyses else 0

    def cout_cucumber(self, depuis):
        return 0.5


def _executer(ops, n=3):
    return run.executer(ops, "projetx", 1, n, "gen", "SPEC-1", "", ecrire=lambda b, d: None,
                        noter=lambda *a: None)


CORRIGE = {"statut": "corrige", "commit": "abc", "cause": "prompt vague", "fichiers": ["prompts/x.md"], "cout_usd": 1.0}


def test_boucle_terminee_quand_tout_passe():
    ops = FausseOps({1: _analyse({"f::A": "echoue", "f::B": "echoue"}), 2: _analyse({"f::A": "passe", "f::B": "passe"})},
                    [CORRIGE])
    boucle = _executer(ops)
    assert boucle["etat"] == cb.TERMINEE and boucle["iteration"] == 1
    assert boucle["corrections"][0]["commit"] == "abc" and boucle["cout_usd"] == 1.5
    assert ops.demandes[0]["iteration"] == 1 and len(ops.demandes[0]["echecs"]) == 2
    assert boucle["final"]["echecs"] == 0 and not boucle["relance"]


def test_boucle_envoie_les_defauts_de_l_agent_hors_run_et_reprend_les_lots():
    """Lot resté en erreur de fichiers (contrôle d'une leçon faux) : envoyé à dev-tool, puis lot repris, sans run
    Jenkins en échec ; la boucle se termine quand la reprise a fait disparaître le défaut."""
    class OpsDefauts(FausseOps):
        def __init__(self, *a):
            super().__init__(*a)
            self.defauts, self.reprises, self.regenerations = [{"id": "lot7::fichiers", "fichier": "a.feature",
                                                                "titre": "Lot 7 : erreur de fichiers persistante",
                                                                "step": "", "message": "leçon n° 31 non appliquée",
                                                                "categorie": "correction", "nature": "defaut_agent",
                                                                "cause": "contrôle inversé (lecons.json)"}], 0, 0

        def defauts_agent(self):
            return list(self.defauts)

        def reprendre(self):
            self.reprises += 1
            self.defauts = []
            return 0

        def regenerer(self, numero):
            self.regenerations += 1
            return 0
    ops = OpsDefauts({1: _analyse({"f::A": "passe"}), 2: _analyse({"f::A": "passe"})}, [CORRIGE])
    boucle = _executer(ops)
    assert ops.demandes[0]["echecs"][0]["nature"] == "defaut_agent" and ops.demandes[0]["echecs"][0]["categorie"] == cb.AGENT
    assert ops.reprises == 1 and ops.regenerations == 0           # rien à régénérer côté Jenkins
    assert boucle["etat"] == cb.TERMINEE and boucle["initial"]["defauts_agent"] == 1


def test_boucle_limite_iterations():
    analyses = {1: _analyse({f"f::{c}": "echoue" for c in "ABCD"}),
                2: _analyse({"f::A": "passe", "f::B": "echoue", "f::C": "echoue", "f::D": "echoue"}),
                3: _analyse({"f::A": "passe", "f::B": "passe", "f::C": "echoue", "f::D": "echoue"})}
    ops = FausseOps(analyses, [CORRIGE, {**CORRIGE, "commit": "def"}])
    boucle = _executer(ops, n=2)
    assert boucle["etat"] == cb.ABANDONNEE and "limite" in boucle["raison"] and len(ops.demandes) == 2
    assert [d["iteration"] for d in ops.demandes] == [1, 2] and boucle["relance"]


def test_boucle_arret_sans_progres():
    ops = FausseOps({1: _analyse({"f::A": "echoue"}), 2: _analyse({"f::A": "echoue"})}, [CORRIGE])
    boucle = _executer(ops)
    assert boucle["etat"] == cb.ABANDONNEE and "aucun échec en moins" in boucle["raison"]
    assert len(ops.demandes) == 1


def test_boucle_retour_arriere_sur_regression():
    analyses = {1: _analyse({"f::A": "echoue", "f::B": "echoue", "f::C": "passe", "f::D": "echoue"}),
                2: _analyse({"f::A": "passe", "f::B": "passe", "f::C": "echoue", "f::D": "echoue"}),
                3: _analyse({"f::A": "passe", "f::B": "passe", "f::C": "passe", "f::D": "passe"})}
    ops = FausseOps(analyses, [CORRIGE, {**CORRIGE, "commit": "def", "annulations": [
        {"commit": "abc", "revert": "rev1", "raison": "régression"}]}])
    boucle = _executer(ops)
    assert ops.demandes[0]["annuler"] is None
    assert ops.demandes[1]["annuler"]["commit"] == "abc" and "f::C" in ops.demandes[1]["annuler"]["raison"]
    assert boucle["iterations"][0]["regressions"] == ["f::C"]
    assert boucle["annulations"][0]["revert"] == "rev1" and boucle["etat"] == cb.TERMINEE


def test_boucle_annulation_finale_si_arret_sur_regression():
    analyses = {1: _analyse({"f::A": "echoue", "f::C": "passe"}), 2: _analyse({"f::A": "echoue", "f::C": "echoue"})}
    ops = FausseOps(analyses, [CORRIGE, {"statut": "annule", "annulations": [{"commit": "abc", "revert": "r"}]}])
    boucle = _executer(ops)
    assert boucle["etat"] == cb.ABANDONNEE
    assert ops.demandes[-1]["annuler"]["commit"] == "abc" and ops.demandes[-1]["echecs"] == []


def test_boucle_correction_annulee_par_devtool_reessaie():
    analyses = {1: _analyse({"f::A": "echoue"}), 2: _analyse({"f::A": "passe"})}
    ops = FausseOps(analyses, [{"statut": "annule", "raison": "tests unitaires en échec"}, CORRIGE])
    boucle = _executer(ops)
    assert boucle["etat"] == cb.TERMINEE and len(ops.demandes) == 2
    assert ops.demandes[1]["historique"][0]["statut"] == "annule"


def test_boucle_anti_triche_retablit_et_classe_incertain():
    violations = {2: {"avant": {F: FEATURE}, "apres": {F: FEATURE.replace("  @agent_2", "  @agent_2 @ignore")}}}
    analyses = {1: _analyse({f"{F}::Créer": "echoue", f"{F}::Annuler": "echoue"}),
                2: _analyse({f"{F}::Créer": "passe", f"{F}::Annuler": "echoue"})}
    ops = FausseOps(analyses, [CORRIGE], violations)
    boucle = _executer(ops, n=1)
    assert ops.retablis == [[F]]
    assert boucle["iterations"][0]["anti_triche"][0]["regle"] == "scenario_desactive"
    assert boucle["final"]["restants"][0]["categorie"] == cb.INCERTAIN


def test_boucle_rien_a_envoyer():
    echecs = [{"id": "f::A", "fichier": "f", "titre": "A", "categorie": "produit", "nature": "bug_applicatif"}]
    ops = FausseOps({1: _analyse({"f::A": "echoue"}, echecs)}, [])
    boucle = _executer(ops)
    assert boucle["etat"] == cb.TERMINEE and ops.demandes == [] and boucle["relance"]   # APPLICATION à traiter


def test_boucle_devtool_impossible():
    ops = FausseOps({1: _analyse({"f::A": "echoue"})}, [{"statut": "impossible", "raison": "seule issue : @ignore"}])
    boucle = _executer(ops)
    assert boucle["etat"] == cb.ABANDONNEE and "impossible" in boucle["raison"] and "demande_texte" in boucle


def test_argv_de_base_et_tags():
    argv = ["--step", "generate-cucumber-client", "--client-name", "projetx", "--run-jenkins", "--run-tags", "@a",
            "--complete", "--from-import=3", "--specifics", "S1"]
    assert run.argv_de_base(argv) == ["--step", "generate-cucumber-client", "--client-name", "projetx"]
    agent = {"f1::A": {"tag": "@agent_1", "spec": "S"}, "f1::B": {"tag": "@agent_2", "spec": ""},
             "f2::C": {"tag": "@agent_3", "spec": "S"}, "f3::D": {"tag": "@agent_4", "spec": "T"}}
    assert run.tags_feature(agent, ["f1::A"], "S") == "@agent_1 or @agent_2 or @agent_3"


def test_declencher(monkeypatch, tmp_path):
    from tools import cucumber_import, cucumber_tools
    monkeypatch.setattr(cucumber_tools, "CACHE_ROOT", str(tmp_path))
    monkeypatch.setattr(cucumber_import, "load_index", lambda c: {"imports": [{"numero": 4}]})
    monkeypatch.setattr(cucumber_import, "load_analysis", lambda c, n: _analyse({"f::A": "echoue"}))
    monkeypatch.delenv("CUCUMBER_BOUCLE_ID", raising=False)
    monkeypatch.delenv("CUCUMBER_BOUCLE", raising=False)
    lances = []
    assert run.declencher("projetx", ["--client-name", "projetx", "--run-jenkins"], log=lambda m: None,
                          lancer=lambda cmd, **kw: lances.append(cmd)).startswith("projetx-4-")
    assert lances[0][-3:] == ["--boucle-correction", "--from-import", "4"] and "--run-jenkins" not in lances[0]
    monkeypatch.setenv("CUCUMBER_BOUCLE_ID", "gen")            # étape d'une boucle : jamais de boucle imbriquée
    assert run.declencher("projetx", [], log=lambda m: None, lancer=lambda *a, **k: lances.append(a)) == ""
    monkeypatch.delenv("CUCUMBER_BOUCLE_ID")
    monkeypatch.setenv("CUCUMBER_BOUCLE", "0")
    assert run.declencher("projetx", [], log=lambda m: None, lancer=lambda *a, **k: lances.append(a)) == ""
    assert len(lances) == 1


# --- transport ----------------------------------------------------------------------------------------------------
def test_devtool_demarre_par_le_superviseur(tmp_path):
    devtool, manager = tmp_path / "devtool", tmp_path / "manager"
    write(str(manager / ".tmp/superviseur.json"), json.dumps({"port": 8499, "jeton": "sup"}))
    appels, en_ligne = [], {"v": False}

    def appel(url, jeton, methode="GET", corps=None, delai=30):
        appels.append((methode, url, jeton))
        if url.endswith("/agents/dev-tool/demarrer"):
            write(str(devtool / ".tmp/api.json"), json.dumps({"port": 8513, "jeton": "api"}))
            en_ligne["v"] = True
            return {}
        if url.endswith("/sante"):
            if not en_ligne["v"]:
                raise DevToolErreur("hors ligne")
            return {"etat": "ok"}
        if url.endswith("/demandes"):
            return {"id": "d1"}
        return {"etat": "termine", "reponse": {"statut": "corrige"}}

    client = ClientDevTool(str(devtool), str(manager), appel=appel, attendre=lambda s: None)
    assert client.demander({"x": 1}) == {"statut": "corrige"}
    assert ("POST", "http://127.0.0.1:8499/agents/dev-tool/demarrer", "sup") in appels


def test_devtool_sans_superviseur(tmp_path):
    client = ClientDevTool(str(tmp_path / "d"), str(tmp_path / "m"), appel=lambda *a, **k: {}, attendre=lambda s: None)
    with pytest.raises(DevToolErreur, match="superviseur"):
        client.demarrer()


def test_journal_masque_les_secrets(tmp_path):
    run.journaliser(str(tmp_path), "gen", "cucumber→dev-tool", {"trace": "Authorization: Bearer abcdefghijklmnop1234"})
    ligne = (tmp_path / "gen.jsonl").read_text(encoding="utf-8")
    assert "abcdefghijklmnop1234" not in ligne and os.path.exists(tmp_path / "gen.jsonl")
