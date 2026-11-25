"""
Configuration propre à agent-cucumber (page ⚙️ Configuration de son IHM) : Groundcover, accès à l'API et serveur MCP.

- Champs : composant commun agent_socle.ihm_groundcover (le même que la page Configuration d'agent-scrum-master).
- Écriture : le .env lu par l'agent (celui de AGENT_DATA_DIR, que main.py charge), jamais une variable transmise par
  le manager (SAVOYE_VARIABLES : prioritaire, en lecture seule) ; aucun jeton MCP (refusé par le composant).
- Filtre des logs : CUCUMBER_GROUNDCOVER_FILTER, à défaut `logs.groundcover_filtre` de l'application du même nom
  dans commun.toml du manager (SAVOYE_CONFIG_DIR) ; repli appliqué à l'environnement du processus, jamais écrit.
- Messages du socle (mcp_servers) : ils désignent la page de cet agent (PAGE).

0 token, sans Streamlit.
"""
import os

from agent_socle import config_commune, env_tools, mcp_servers, projets

FILTER_ENV = "CUCUMBER_GROUNDCOVER_FILTER"
PAGE = "onglet ⚙️ Configuration d'agent-cucumber, section Serveurs MCP"
# Suffixes des secrets enregistrés tels quels (les autres valeurs sans espaces superflus), comme agent-scrum-master
SECRET_SUFFIXES = ("_TOKEN", "_SECRET", "_PASSWORD", "_API_KEY")


def designer_page() -> None:
    """Les messages de mcp_servers (« Tester », « Se connecter à Groundcover ») renvoient à la page de cet agent."""
    mcp_servers.definir_page(PAGE)


def filtre_application(client: str, dossier: str = "") -> str:
    """`logs.groundcover_filtre` de l'application `client` de commun.toml ('' si absente, illisible ou sans filtre)."""
    if not (client or "").strip():
        return ""
    application = projets.applications(dossier).get(client.strip()) or {}
    return str((application.get("logs") or {}).get("groundcover_filtre", "") or "").strip()


def filtre(client: str = "", dossier: str = "") -> dict:
    """Filtre gcQL effectif et sa source : {"valeur", "source": "env" | "commun.toml" | ""}."""
    valeur = os.getenv(FILTER_ENV, "").strip()
    if valeur:
        return {"valeur": valeur, "source": "env"}
    valeur = filtre_application(client, dossier)
    return {"valeur": valeur, "source": "commun.toml" if valeur else ""}


def appliquer_filtre(client: str, dossier: str = "") -> str:
    """
    À défaut de CUCUMBER_GROUNDCOVER_FILTER, celui de l'application du client (commun.toml) est placé dans
    l'environnement du processus (groundcover_tools et la CLI lancée par Claude le lisent). Renvoie le filtre repris
    ('' si rien n'a changé). Jamais écrit dans le .env.
    """
    effectif = filtre(client, dossier)
    if effectif["source"] != "commun.toml":
        return ""
    os.environ[FILTER_ENV] = effectif["valeur"]
    return effectif["valeur"]


def a_ecrire(valeurs: dict) -> dict:
    """Valeurs à écrire dans le .env : variables du manager écartées ; secrets tels quels, le reste sans espaces."""
    return {nom: valeur if nom.endswith(SECRET_SUFFIXES) else str(valeur).strip()
            for nom, valeur in (valeurs or {}).items() if not config_commune.geree(nom)}


def enregistrer(env_path: str, valeurs: dict) -> dict:
    """Écrit les valeurs dans le .env de l'agent (relecture contrôlée par write_env) ; renvoie ce qui a été écrit."""
    ecrites = a_ecrire(valeurs)
    if ecrites:
        env_tools.write_env(env_path, ecrites)
    return ecrites
