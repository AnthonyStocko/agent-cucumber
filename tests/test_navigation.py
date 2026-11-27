"""
Navigation : seule la page choisie est exécutée ; hors des pages Cucumber, aucune tâche de fond ni aucun fragment
à rafraîchissement automatique (l'application ne se réexécute plus d'elle-même sur l'onglet Intégration).
"""
import os
import time

from streamlit.testing.v1 import AppTest

from tools import cucumber_detection, standard_version_task
from agent_socle import ui_timer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _app(monkeypatch, tmp_path, page: str = "") -> tuple:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.delenv("AGENT_AUTH", raising=False)
    calls = []
    monkeypatch.setattr(cucumber_detection, "start", lambda *a, **k: calls.append(("detection", a, k)) or False)
    monkeypatch.setattr(standard_version_task, "start", lambda *a, **k: calls.append(("version", a, k)) or False)
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120)
    if page:
        at.session_state["nav_page"] = page
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at, calls


def test_search_criteria_kept_when_changing_page(monkeypatch, tmp_path):
    at, _ = _app(monkeypatch, tmp_path, "cucumber-avance")
    at.text_input(key="cucumber_repo").input("ABC").run()
    at.session_state["nav_page"] = "cucumber"  # autre page de l'IHM Cucumber (Configuration globale : manager, Réglages des agents)
    at.run()
    at.session_state["nav_page"] = "cucumber-avance"
    at.run()
    assert at.text_input(key="cucumber_repo").value == "ABC"


def test_commit_check_every_15_minutes_and_recheck_now(monkeypatch, tmp_path):
    monkeypatch.delenv("CUCUMBER_DETECTION_INTERVAL", raising=False)
    assert cucumber_detection.interval() == 900
    checked = time.time() - 60
    monkeypatch.setattr(cucumber_detection, "load_detection", lambda client: {
        "verifie_le": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(checked))})
    assert 830 <= cucumber_detection.next_check_in("x") <= 840
    assert not cucumber_detection.due("x")
    launched = []

    class Process:
        returncode = None

        def poll(self):
            return None

    monkeypatch.setattr(cucumber_detection, "log_path", lambda client: str(tmp_path / "detection.log"))
    monkeypatch.setattr(cucumber_detection.subprocess, "Popen", lambda cmd, **k: launched.append(cmd) or Process())
    assert cucumber_detection.start("x", ["main.py"]) is False              # contrôle récent : pas avant 15 min
    assert cucumber_detection.start("x", ["main.py"], now=True) is True     # « Revérifier maintenant »
    assert launched == [["main.py", "--detect-only"]]                       # contrôle des commits, sans --detect-force
    cucumber_detection._PROCESSES.pop("x", None)
