"""
Serveurs MCP des appels `claude` : liste fermée. Sans Groundcover activé, appels identiques (--strict-mcp-config sans
--mcp-config) ; activé, fichier MCP limité à Groundcover, outils de lecture ajoutés pour les seules étapes de
diagnostic ; aucun serveur Jira, aucun jeton.
"""
import importlib
import io
import json
import os
import sys

import pytest

from agent_socle import mcp_servers as ms

READ_TOOLS = ["mcp__groundcover__query_logs", "mcp__groundcover__list_workloads", "mcp__groundcover__getTraces"]
WRITE_TOOLS = ["mcp__groundcover__create_monitor", "mcp__groundcover__delete_dashboard",
               "mcp__groundcover__query_and_update"]
URL = "https://mcp.groundcover.example/api/mcp"
CONSOLE = os.path.join(os.path.dirname(__file__), "reference", "11-build-241-run-complet.console.txt")


@pytest.fixture(scope="module")
def main_module():
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        return importlib.import_module("main")
    finally:
        sys.stdout, sys.stderr = saved


@pytest.fixture
def mcp_dir(tmp_path, monkeypatch):
    for name in (ms.URL_ENV, ms.HEADERS_ENV, ms.ENABLED_ENV, ms.TOOLS_ENV):
        monkeypatch.delenv(name, raising=False)
    directory = str(tmp_path / "mcp")
    monkeypatch.setattr(ms, "MCP_DIR", directory)
    return directory


def enable(monkeypatch, tools=READ_TOOLS + WRITE_TOOLS):
    monkeypatch.setenv(ms.URL_ENV, URL)
    monkeypatch.setenv(ms.ENABLED_ENV, "1")
    ms.save_state("connecté", "ok", list(tools))


class FakeProcess:
    calls = []

    def __init__(self, cmd, **kwargs):
        FakeProcess.calls.append({"cmd": cmd, "env": kwargs.get("env")})
        self.returncode = 0

    def communicate(self, input=None):
        return json.dumps({"result": FakeProcess.answer, "usage": {"input_tokens": 1}}), ""


def run(main_module, monkeypatch, step, answer="fini", lean=True):
    FakeProcess.calls, FakeProcess.answer = [], answer
    monkeypatch.setattr(main_module.subprocess, "Popen", FakeProcess)
    out = main_module.run_claude("prompt", "sonnet", ["/std"], ["Read", "Grep"], ("--max-turns", "5"), lean=lean,
                                 mcp_step=step)
    return FakeProcess.calls[0], out


# ---------------------------------------------------------------------------
# Sans Groundcover : appels identiques à aujourd'hui
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Groundcover activé : étapes de diagnostic seulement
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Configuration : jamais de serveur Jira, jamais de jeton
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Accès en échec, masquage, état
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Fenêtre des échecs, namespace / conteneur / pod
# ---------------------------------------------------------------------------


def test_diagnostic_prompt_block(main_module, monkeypatch, mcp_dir):
    assert main_module.build_mcp_logs_block("cucumber-import-fix", "", [{"id": "x", "heure": "2026-10-30T13:40:00"}]) == ""
    enable(monkeypatch)
    block = main_module.build_mcp_logs_block("cucumber-init-fix", "", [{"id": "x", "step": "Given z",
                                                                        "heure": "2026-10-30T13:40:00"}],
                                             pod={"namespace": "jenkins", "pod": "p-1", "conteneurs": ["app"]})
    assert "13:39:30Z → 2026-10-30T13:40:30Z" in block and "GROUNDCOVER_ACCES=echec" in block
    assert "namespace « jenkins »" in block and "« app »" in block
    assert main_module.build_mcp_logs_block("cucumber-lot", "", [{"id": "x", "heure": "2026-10-30T13:40:00"}]) == ""
