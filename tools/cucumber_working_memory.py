"""
Mémoire de travail d'un lot (0 token) : un fichier Markdown que l'agent tient à jour quand son contexte grossit,
et qui est réinjecté au début de CHAQUE appel du lot (écriture, revue, corrections de fichiers, de compilation et
après exécution). La discipline (quand écrire, format, ce qu'il ne faut jamais y mettre) est dans
prompts/cucumber_memoire_travail.md.

- Le fichier vit dans le dossier d'exécution (cwd de Claude Code, écriture autorisée) : memoire_lot_<n>.md.
- Son contenu est recopié dans l'état du lot (lot["memoire_travail"]) après chaque appel : « Reprendre » ou un
  nouveau dossier d'exécution le retrouvent (le fichier est recréé à partir de l'état).
- Le bloc injecté est borné (MAX_CHARS) ; au-delà, l'agent reçoit la consigne de compacter.

CUCUMBER_WORKING_MEMORY=0 : désactivée.
"""
import os
from string import Template

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT = os.path.join(RACINE, "prompts", "cucumber_memoire_travail.md")
MAX_CHARS = 6000
MAX_LINES = 60
_EMPTY = "(vide : premier appel du lot ; crée le fichier au premier fait établi)"


def enabled() -> bool:
    return os.getenv("CUCUMBER_WORKING_MEMORY", "1").strip().lower() not in ("0", "false", "non", "off")


def path(run_dir: str, lot: dict) -> str:
    return os.path.join(run_dir, f"memoire_lot_{lot.get('numero', 'x')}.md")


def _read(file: str) -> str:
    try:
        with open(file, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def block(run_dir: str, lot: dict, alert_turn="") -> str:
    """Consigne et contenu actuel de la mémoire du lot ; le fichier est recréé depuis l'état s'il manque."""
    if not enabled() or not isinstance(lot, dict) or not run_dir:
        return ""
    file = path(run_dir, lot)
    content = _read(file)
    if not content and lot.get("memoire_travail"):
        content = lot["memoire_travail"]
        try:
            os.makedirs(run_dir, exist_ok=True)
            with open(file, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass
    content = content.strip()
    if len(content) > MAX_CHARS:
        content = (content[:MAX_CHARS] + f"\n… (tronqué : {len(content)} caractères, limite {MAX_CHARS}) — "
                   f"COMPACTE ce fichier avant toute autre action.")
    with open(PROMPT, encoding="utf-8") as f:
        template = Template(f.read())
    return template.safe_substitute(fichier=file.replace("\\", "/"), contenu=content or _EMPTY,
                                    lot=lot.get("numero", ""), max_lignes=MAX_LINES,
                                    tour_alerte=alert_turn or "d'alerte").rstrip() + "\n\n"


def save(run_dir: str, lot: dict) -> None:
    """Contenu du fichier gardé dans l'état du lot (persisté par save_state de l'appelant)."""
    if not enabled() or not isinstance(lot, dict) or not run_dir:
        return
    content = _read(path(run_dir, lot)).strip()
    if content:
        lot["memoire_travail"] = content[:MAX_CHARS * 2]
