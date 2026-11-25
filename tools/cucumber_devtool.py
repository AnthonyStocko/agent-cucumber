"""
Client de l'API locale d'agent-dev-tool-savoye (boucle de correction autonome, CLAUDE.md § 6).

- API de dev-tool : 127.0.0.1, port et jeton dans <dev-tool>/.tmp/api.json (écrit au démarrage de son IHM),
  en-tête X-Jeton ; GET /sante, POST /demandes, GET /demandes/<id>.
- dev-tool hors ligne : démarré par le mécanisme existant du manager, le canal de commande de son superviseur
  (POST /agents/dev-tool/demarrer, jeton de <manager>/.tmp/superviseur.json). Rien n'est lancé autrement.

Dossiers : AGENT_DEV_TOOL_DIR, sinon le dossier frère agent-dev-tool-savoye ; manager : parent de SAVOYE_CONFIG_DIR
(transmis par le superviseur), sinon le dossier frère agent-manager-savoye. Aucun secret ici : les jetons locaux ne
sont ni journalisés ni écrits ailleurs.
"""
import json
import os
import time
import urllib.error
import urllib.request

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOM_AGENT = "dev-tool"


class DevToolErreur(Exception):
    pass


def dossier_devtool() -> str:
    return os.getenv("AGENT_DEV_TOOL_DIR", "").strip() or os.path.join(os.path.dirname(RACINE), "agent-dev-tool-savoye")


def dossier_manager() -> str:
    config = os.getenv("SAVOYE_CONFIG_DIR", "").strip()
    return os.path.dirname(os.path.abspath(config)) if config else os.path.join(os.path.dirname(RACINE),
                                                                              "agent-manager-savoye")


def _lire_json(chemin: str) -> dict:
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _appel(url: str, jeton: str, methode: str = "GET", corps: dict = None, delai: float = 30.0) -> dict:
    donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8") if corps is not None else (
        b"" if methode == "POST" else None)
    requete = urllib.request.Request(url, method=methode, data=donnees,
                                     headers={"X-Jeton": jeton, "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(requete, timeout=delai) as reponse:
            return json.loads(reponse.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read().decode("utf-8")).get("erreur", str(e))
        except ValueError:
            message = str(e)
        raise DevToolErreur(f"{methode} {url.split('/', 3)[-1]} : {message}") from e
    except OSError as e:
        raise DevToolErreur(f"{methode} injoignable : {e}") from e


class ClientDevTool:
    """Transport des demandes de la boucle. `ouvrir`, `attendre` : injectables pour les tests."""

    def __init__(self, dossier: str = "", manager: str = "", appel=_appel, attendre=time.sleep):
        self.dossier = dossier or dossier_devtool()
        self.manager = manager or dossier_manager()
        self.appel = appel
        self.attendre = attendre

    def _api(self) -> dict:
        infos = _lire_json(os.path.join(self.dossier, ".tmp", "api.json"))
        if not infos.get("port") or not infos.get("jeton"):
            raise DevToolErreur("API de dev-tool non publiée (.tmp/api.json absent)")
        return infos

    def en_ligne(self) -> bool:
        try:
            infos = self._api()
            return self.appel(f"http://127.0.0.1:{infos['port']}/sante", infos["jeton"], delai=5).get("etat") == "ok"
        except DevToolErreur:
            return False

    def demarrer(self, delai: float = 240.0, pas: float = 5.0) -> None:
        """Démarre dev-tool par le superviseur du manager si son API ne répond pas, puis attend qu'elle réponde."""
        if self.en_ligne():
            return
        sup = _lire_json(os.path.join(self.manager, ".tmp", "superviseur.json"))
        if not sup.get("port") or not sup.get("jeton"):
            raise DevToolErreur("superviseur du manager introuvable : dev-tool ne peut pas être démarré "
                                "(lancer le manager avec lancer.bat)")
        self.appel(f"http://127.0.0.1:{sup['port']}/agents/{NOM_AGENT}/demarrer", sup["jeton"], "POST")
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.en_ligne():
                return
            self.attendre(pas)
        raise DevToolErreur(f"dev-tool démarré par le superviseur mais son API ne répond pas après {int(delai)} s")

    def envoyer(self, demande: dict) -> str:
        infos = self._api()
        reponse = self.appel(f"http://127.0.0.1:{infos['port']}/demandes", infos["jeton"], "POST", demande)
        if not reponse.get("id"):
            raise DevToolErreur(f"demande refusée par dev-tool : {reponse.get('erreur') or reponse}")
        return reponse["id"]

    def resultat(self, identifiant: str, delai: float = 4 * 3600.0, pas: float = 20.0) -> dict:
        """Réponse de dev-tool à la demande (attente bornée ; dev-tool redémarré entre-temps : relu sur son API)."""
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            try:
                infos = self._api()
                etat = self.appel(f"http://127.0.0.1:{infos['port']}/demandes/{identifiant}", infos["jeton"])
            except DevToolErreur:
                etat = {}
            if etat.get("etat") == "termine":
                return etat.get("reponse") or {"statut": "erreur", "raison": "réponse vide"}
            self.attendre(pas)
        return {"statut": "erreur", "raison": f"pas de réponse de dev-tool après {int(delai)} s"}

    def demander(self, demande: dict) -> dict:
        self.demarrer()
        return self.resultat(self.envoyer(demande))
