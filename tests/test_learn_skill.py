"""Auto-amélioration : compétences tirées des réussites prouvées, proposées aux tâches semblables."""
import importlib
import io
import os
import sys

from agent_socle import skills as sk

PROPOSAL = {"action": "creer", "nom": "OP introuvable : créer l'OP dans le Background",
            "description": "Un contrôle échoue car l'ordre de préparation n'existe pas après l'init",
            "declencheurs": ["OP introuvable", "Cannot access first() element from an empty List"],
            "etapes": ["Lire en base l'OP cherché par le step", "Absent : le créer dans le Background par le step "
                       "PREP- Création d'un ordre de préparation", "Relancer le scénario seul"],
            "pieges": ["Ne pas modifier l'init globale"], "exemple": "TOW-730 chez apparel ; token=abc123"}


def test_learn_skill_only_after_a_complex_success(tmp_path, monkeypatch):
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        m = importlib.import_module("main")
    finally:
        sys.stdout, sys.stderr = saved
    monkeypatch.setenv("AGENT_KNOWLEDGE_DIR", str(tmp_path))
    monkeypatch.delenv("SKILLS_AUTO", raising=False)
    monkeypatch.setenv("SKILLS_MIN_TURNS", "8")
    calls = []

    def claude(prompt, *a, **k):
        calls.append(prompt)
        return 0, "```json\n" + __import__("json").dumps(PROPOSAL) + "\n```", {}, False
    monkeypatch.setattr(m, "run_claude", claude)
    monkeypatch.setattr(m, "report_token_usage", lambda *a, **k: None)
    assert m.learn_skill("apparel", "cucumber-correction", "S1 vert", "preuve", str(tmp_path), "", str(tmp_path),
                         "K", 3) == ""                                   # trop simple : rien
    assert calls == []
    path = m.learn_skill("apparel", "cucumber-correction", "- S1 : échec « OP introuvable »", "1 scénario vert sur "
                         "Jenkins", str(tmp_path), "", str(tmp_path), "K", 12)
    assert path and os.path.exists(path) and "OP introuvable" in calls[0] and "(aucune)" in calls[0]
