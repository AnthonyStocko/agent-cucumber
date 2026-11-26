"""
Défauts de l'agent lui-même (0 token) : ce que la boucle de correction autonome (cucumber_boucle, CLAUDE.md § 6)
envoie à agent-dev-tool-savoye en plus des échecs Jenkins.

Deux sources, gardées dans l'état de la génération :
- un lot resté en erreur de fichiers ou de compilation après toutes ses corrections (« erreur de … persistante ») :
  les contrôles déterministes et la boucle de correction de l'agent n'ont pas convergé ;
- un constat d'une correction qui met en cause l'agent : type « defaut_agent », ou constat « prouvé » dont le fichier
  est un fichier de l'agent (code, prompts, données de travail .tmp/cucumber/<client>/ comme lecons.json).
Chaque défaut devient un échec de la boucle, catégorie AGENT, avec un identifiant stable « lot<n>::<étape> ».
"""
import re

NATURE = "defaut_agent"
# Fichiers de l'agent : dépôt agent-cucumber (code, prompts) et ses données de travail par client
_AGENT_FILE = re.compile(r"(?:^|[\\/])(?:agent-cucumber|\.tmp[\\/]cucumber)(?:[\\/]|$)|^(?:tools|prompts)[\\/]|"
                         r"(?:^|[\\/])lecons\.json$", re.I)
MAX_PAR_LOT = 5


def agent_file(path: str) -> bool:
    return bool(_AGENT_FILE.search(str(path or "").strip()))


def is_agent_defect(constat: dict) -> bool:
    """Constat normalisé (cucumber_tools.normalize_constats) qui met en cause l'agent, pas le code testé."""
    if not isinstance(constat, dict):
        return False
    if constat.get("type") == NATURE:
        return True
    return constat.get("certitude") == "prouvé" and agent_file(constat.get("fichier", ""))


def record(lot: dict, fix_result: dict, etape: str) -> list:
    """Défauts de l'agent d'une réponse de correction, ajoutés au lot (sans doublon). Renvoie les nouveaux."""
    if not isinstance(lot, dict) or not isinstance(fix_result, dict) or not fix_result.get("constats"):
        return []
    from tools import cucumber_tools
    constats = cucumber_tools.normalize_constats(dict(fix_result))
    known = {d.get("detail") for d in lot.get("defauts_agent") or []}
    new = [{**c, "etape": etape} for c in constats if is_agent_defect(c) and c["detail"] not in known]
    if new:
        lot["defauts_agent"] = ((lot.get("defauts_agent") or []) + new)[-MAX_PAR_LOT:]
    return new


def failures(state: dict) -> list:
    """Échecs de la boucle (format cucumber_boucle.classer) pour les défauts de l'agent des lots de l'état."""
    out = []
    for lot in (state or {}).get("lots") or []:
        numero = lot.get("numero")
        check = lot.get("verification") or {}
        defects = lot.get("defauts_agent") or []
        stuck = lot.get("statut") == "erreur_compilation" and check.get("erreurs") and not check.get("environnement")
        if not stuck and not defects:
            continue
        etape = check.get("etape") or "fichiers"
        files = [f for f in lot.get("fichiers") or [] if isinstance(f, str)]
        cause = " ; ".join(f"{d['detail']}" + (f" ({d['fichier']}" + (f":{d['ligne']}" if d.get("ligne") else "")
                                                + ")" if d.get("fichier") else "")
                           + (f" — correction suggérée : {d['correction']}" if d.get("correction") else "")
                           for d in defects) or "corrections de l'agent sans convergence"
        message = ("\n".join(check.get("erreurs") or [])
                   if stuck else "défaut de l'agent signalé par une correction (lot terminé malgré lui)")
        out.append({"id": f"lot{numero}::{etape}", "fichier": next((f for f in files if f.endswith(".feature")), ""),
                    "titre": f"Lot {numero} : erreur de {etape} persistante" if stuck
                    else f"Lot {numero} : défaut de l'agent", "step": "", "message": message,
                    "categorie": "correction", "nature": NATURE, "cause": cause,
                    "trace": "\n".join(f"{d.get('preuve', '')} {d.get('extrait', '')}".strip() for d in defects)})
    return out
