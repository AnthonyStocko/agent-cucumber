"""
Page ⚙️ Configuration d'agent-cucumber : Groundcover (accès API, filtre, serveur MCP) réglable depuis son IHM, par le
composant commun d'agent-socle ; écrit dans le .env de l'agent, sans jeton ; variables transmises par le manager en
lecture seule et jamais réécrites ; filtre repris de commun.toml à défaut ; messages du socle vers cette page.
"""
import os

import pytest
from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

from agent_socle import config_commune, ihm_groundcover, mcp_servers
from tools import cucumber_configuration

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://mcp.groundcover.com/api/mcp"
FILTRE = "namespace:client-x-recette"
COMMUN = f"""
[[applications]]
nom = "clientx"

[applications.logs]
groundcover_filtre = "{FILTRE}"

[[applications]]
nom = "autre"
"""


@pytest.fixture(autouse=True)
def _sans_manager(monkeypatch):
    for nom in ihm_groundcover.VARIABLES + (mcp_servers.PAGE_ENV, config_commune.VARIABLE_LISTE, "SAVOYE_CONFIG_DIR"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.delenv("AGENT_AUTH", raising=False)
    config_commune.relever({})
    yield
    config_commune.relever({})


def _commun(tmp_path):
    dossier = tmp_path / "config"
    dossier.mkdir(exist_ok=True)
    (dossier / "commun.toml").write_text(COMMUN, encoding="utf-8")
    return str(dossier)


def _configuration(monkeypatch, tmp_path, env: str = "") -> AppTest:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(env, encoding="utf-8")
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120)
    at.session_state["nav_page"] = "configuration"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _champ(at, label):
    return next(t for t in at.text_input if t.label == label)


def _enregistrer(at):
    next(b for b in at.button if b.label == "Enregistrer").click().run()
    assert not at.exception, [e.value for e in at.exception]


# ---------------------------------------------------------------------------
# Filtre : .env, à défaut commun.toml (jamais écrit)
# ---------------------------------------------------------------------------

def test_filtre_du_env_prioritaire(monkeypatch, tmp_path):
    monkeypatch.setenv("CUCUMBER_GROUNDCOVER_FILTER", " namespace:env ")
    assert cucumber_configuration.filtre("clientx", _commun(tmp_path)) == {"valeur": "namespace:env", "source": "env"}
    assert cucumber_configuration.appliquer_filtre("clientx", _commun(tmp_path)) == ""
    assert os.environ["CUCUMBER_GROUNDCOVER_FILTER"] == " namespace:env "


def test_filtre_repris_de_commun_toml(monkeypatch, tmp_path):
    dossier = _commun(tmp_path)
    assert cucumber_configuration.filtre("clientx", dossier) == {"valeur": FILTRE, "source": "commun.toml"}
    assert cucumber_configuration.appliquer_filtre("clientx", dossier) == FILTRE
    assert os.environ["CUCUMBER_GROUNDCOVER_FILTER"] == FILTRE


def test_filtre_absent(tmp_path):
    dossier = _commun(tmp_path)
    for client in ("autre", "inconnu", ""):
        assert cucumber_configuration.filtre(client, dossier) == {"valeur": "", "source": ""}
        assert cucumber_configuration.appliquer_filtre(client, dossier) == ""
    assert cucumber_configuration.filtre_application("clientx", str(tmp_path / "absent")) == ""
    assert "CUCUMBER_GROUNDCOVER_FILTER" not in os.environ


def test_filtre_par_savoye_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SAVOYE_CONFIG_DIR", _commun(tmp_path))
    assert cucumber_configuration.filtre_application("clientx") == FILTRE


# ---------------------------------------------------------------------------
# Écriture : variables du manager jamais réécrites
# ---------------------------------------------------------------------------

def test_variables_du_manager_jamais_ecrites(tmp_path):
    config_commune.relever({config_commune.VARIABLE_LISTE: "GROUNDCOVER_API_KEY,GROUNDCOVER_API_URL",
                            "GROUNDCOVER_API_KEY": "cle-manager", "GROUNDCOVER_API_URL": "https://api.manager"})
    env = tmp_path / ".env"
    env.write_text("AUTRE=1\n", encoding="utf-8")
    ecrites = cucumber_configuration.enregistrer(str(env), {
        "GROUNDCOVER_API_KEY": "autre ", "GROUNDCOVER_API_URL": "x", "CUCUMBER_GROUNDCOVER_FILTER": " namespace:a ",
        "GROUNDCOVER_BACKEND_ID": " b "})
    assert ecrites == {"CUCUMBER_GROUNDCOVER_FILTER": "namespace:a", "GROUNDCOVER_BACKEND_ID": "b"}
    assert dotenv_values(env) == {"AUTRE": "1", "CUCUMBER_GROUNDCOVER_FILTER": "namespace:a",
                                  "GROUNDCOVER_BACKEND_ID": "b"}


# ---------------------------------------------------------------------------
# Messages du socle : page de cet agent
# ---------------------------------------------------------------------------

def test_messages_designent_la_page_d_agent_cucumber(monkeypatch, tmp_path):
    monkeypatch.setenv(mcp_servers.URL_ENV, URL)
    monkeypatch.setenv(mcp_servers.ENABLED_ENV, "1")
    cucumber_configuration.designer_page()
    page = cucumber_configuration.PAGE
    assert f"({page}, « Se connecter à Groundcover »)" in mcp_servers.failure_message("expiré")
    assert mcp_servers.unavailable_reason(str(tmp_path)).endswith(f"({page})")
    assert "onglet ⚙️, Serveurs MCP" not in mcp_servers.failure_message("expiré")


# ---------------------------------------------------------------------------
# Page ⚙️ Configuration (IHM)
# ---------------------------------------------------------------------------

def test_page_configuration_affiche_groundcover(monkeypatch, tmp_path):
    at = _configuration(monkeypatch, tmp_path, "GROUNDCOVER_API_URL=https://api.groundcover.com\n")
    labels = {t.label for t in at.text_input}
    assert {"GROUNDCOVER_API_KEY", "GROUNDCOVER_BACKEND_ID", "GROUNDCOVER_API_URL", "CUCUMBER_GROUNDCOVER_FILTER",
            "Adresse du serveur MCP Groundcover", "En-têtes non secrets (facultatif)",
            "Outils autorisés (facultatif)"} <= labels
    assert _champ(at, "GROUNDCOVER_API_URL").value == "https://api.groundcover.com"
    assert [m for m in at.markdown if "Serveurs MCP" in m.value]
    assert [c for c in at.checkbox if c.label == "Groundcover activé"]
    assert {"Se connecter à Groundcover", "Tester"} <= {b.label for b in at.button}
    assert os.environ[mcp_servers.PAGE_ENV] == cucumber_configuration.PAGE


def test_connect_to_mcp_enregistre_sans_jeton(monkeypatch, tmp_path):
    at = _configuration(monkeypatch, tmp_path)
    next(c for c in at.checkbox if c.label == "Groundcover activé").check()
    _champ(at, "Adresse du serveur MCP Groundcover").input(
        f'claude mcp add groundcover --transport http {URL} --header "Authorization: Bearer secret-abc" '
        f'--header "X-Timezone: Europe/Paris"')
    _champ(at, "CUCUMBER_GROUNDCOVER_FILTER").input("namespace:recette")
    _enregistrer(at)
    env = dotenv_values(tmp_path / ".env")
    assert env[mcp_servers.URL_ENV] == URL and env[mcp_servers.ENABLED_ENV] == "1"
    assert env[mcp_servers.HEADERS_ENV] == "X-Timezone: Europe/Paris"
    assert env["CUCUMBER_GROUNDCOVER_FILTER"] == "namespace:recette"
    assert "secret-abc" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_adresse_refusee_rien_enregistre(monkeypatch, tmp_path):
    at = _configuration(monkeypatch, tmp_path, "AUTRE=1\n")
    _champ(at, "Adresse du serveur MCP Groundcover").input("https://x.atlassian.net/mcp")
    _enregistrer(at)
    assert "Configuration non enregistrée" in at.error[0].value
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "AUTRE=1\n"


def test_variables_du_manager_lecture_seule_et_non_reecrites(monkeypatch, tmp_path):
    environ = {config_commune.VARIABLE_LISTE: "GROUNDCOVER_API_URL,GROUNDCOVER_BACKEND_ID,GROUNDCOVER_API_KEY",
               "GROUNDCOVER_API_URL": "https://api.manager", "GROUNDCOVER_BACKEND_ID": "backend-manager",
               "GROUNDCOVER_API_KEY": "cle-secrete-manager"}
    config_commune.relever(environ)
    for nom in ("GROUNDCOVER_API_URL", "GROUNDCOVER_BACKEND_ID", "GROUNDCOVER_API_KEY"):
        monkeypatch.setenv(nom, environ[nom])
    # Le .env porte d'autres valeurs : celles du manager l'emportent (reappliquer) et ne sont jamais réécrites
    at = _configuration(monkeypatch, tmp_path, "GROUNDCOVER_API_URL=https://api.locale\n")
    cle, adresse, backend = (_champ(at, n) for n in ("GROUNDCOVER_API_KEY", "GROUNDCOVER_API_URL",
                                                       "GROUNDCOVER_BACKEND_ID"))
    assert cle.disabled and adresse.disabled and backend.disabled
    assert cle.value == "" and adresse.value == "https://api.manager" and backend.value == "backend-manager"
    assert [i for i in at.info if "Transmises par le manager" in i.value]
    _champ(at, "CUCUMBER_GROUNDCOVER_FILTER").input("namespace:recette")
    _enregistrer(at)
    texte = (tmp_path / ".env").read_text(encoding="utf-8")
    env = dotenv_values(tmp_path / ".env")
    assert env["GROUNDCOVER_API_URL"] == "https://api.locale"
    assert "GROUNDCOVER_BACKEND_ID" not in env and "GROUNDCOVER_API_KEY" not in env
    assert "cle-secrete-manager" not in texte and env["CUCUMBER_GROUNDCOVER_FILTER"] == "namespace:recette"


def test_filtre_de_commun_toml_signale(monkeypatch, tmp_path):
    monkeypatch.setenv("SAVOYE_CONFIG_DIR", _commun(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120)
    at.session_state["nav_page"] = "configuration"
    at.session_state["cs_project"] = "clientx"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [c for c in at.caption if "commun.toml" in c.value and FILTRE in c.value]
    assert _champ(at, "CUCUMBER_GROUNDCOVER_FILTER").value == ""
