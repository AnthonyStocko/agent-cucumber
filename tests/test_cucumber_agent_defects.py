"""Défauts de l'agent envoyés à dev-tool par la boucle autonome (lots en erreur persistante, constats)."""
from tools import cucumber_agent_defects as ad
from tools import cucumber_boucle as cb

LECON = {"type": "comportement_surprenant", "detail": "Le contrôle de la leçon n° 31 impose le préfixe interdit.",
         "fichier": "C:\\agent-scrum-master\\.tmp\\cucumber\\canson\\lecons.json", "ligne": "551-556",
         "certitude": "prouvé", "preuve": "leçon n° 31 non appliquée (l. 63 : FAT.L53.01.13.1)",
         "correction": "type de contrôle d'interdiction"}


def test_agent_defects_are_recognised():
    assert ad.is_agent_defect({"type": "defaut_agent", "detail": "x"})
    assert ad.is_agent_defect(LECON)
    assert not ad.is_agent_defect({**LECON, "certitude": "probable"})
    assert not ad.is_agent_defect({**LECON, "fichier": "wms-content-core/src/main/java/X.java"})
    assert ad.agent_file("prompts/cucumber_client_fix.md") and ad.agent_file("tools/cucumber_lessons.py")


def test_persistent_lot_error_and_constat_become_agent_failures():
    lot = {"numero": 7, "statut": "erreur_compilation", "fichiers": ["a/SPEC.feature"],
           "verification": {"ok": False, "etape": "fichiers", "erreurs": ["leçon n° 31 non appliquée"],
                            "environnement": False}}
    assert len(ad.record(lot, {"constats": [LECON, {"type": "defaut_code", "detail": "bug client"}]}, "fichiers")) == 1
    assert ad.record(lot, {"constats": [LECON]}, "fichiers") == []           # pas de doublon
    state = {"lots": [lot, {"numero": 6, "statut": "termine"}]}
    found = ad.failures(state)
    assert [f["id"] for f in found] == ["lot7::fichiers"] and "lecons.json" in found[0]["cause"]
    echecs = cb.classer({"echecs": [], "resultats": {}, "init_en_echec": {"x": 1}}, found)
    assert [e["categorie_boucle"] for e in echecs] == [cb.AGENT]           # même avec l'init en échec
    demande = cb.construire_demande("g", 1, 3, "canson", "", [cb.echec_pour_demande(echecs[0])], [], [])
    assert demande["echecs"][0]["nature"] == "defaut_agent"
    # Environnement bloquant : pas un défaut de l'agent
    lot["verification"]["environnement"], lot["defauts_agent"] = True, []
    assert ad.failures(state) == []
