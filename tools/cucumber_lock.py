"""
Verrou par client des générations Cucumber : une seule commande qui écrit dans l'espace de l'agent
(.tmp/cucumber/<client>/ : worktree, état, branche de travail) à la fois. Une seconde génération lancée sur le même
client (interface ou ligne de commande) recréerait le worktree pendant les corrections de la première.

Fichier .tmp/cucumber/<client>/generation.lock {"pid", "depart", "debut", "commande"}, créé de façon atomique ;
libéré à la sortie du processus. Verrou d'un processus terminé (arrêt brutal) : repris. Les commandes en lecture
seule (détection, profil, log serveur, import d'un run) ne le prennent pas.
"""
import atexit
import json
import os
import sys
from datetime import datetime

from tools import cucumber_tools
from agent_socle.verrou import LOCK_NAME, _windows_process, process_info, describe  # noqa: E402,F401 — extraits au socle


def lock_path(client: str) -> str:
    return os.path.join(cucumber_tools.cache_dir(client), LOCK_NAME)


def holder(client: str) -> dict:
    """Détenteur vivant du verrou du client ; {} si libre (verrou absent, illisible ou d'un processus terminé)."""
    try:
        with open(lock_path(client), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    alive, start = process_info(int(data.get("pid") or 0))
    if not alive or (data.get("depart") and start and data["depart"] != start):
        return {}
    return data


def acquire(client: str, command: str = ""):
    """
    Prend le verrou du client pour ce processus. Renvoie (True, '') ou (False, raison) si une autre génération
    vivante le détient. Libéré automatiquement à la sortie du processus.
    """
    path = lock_path(client)
    data = {"pid": os.getpid(), "depart": process_info(os.getpid())[1],
            "debut": datetime.now().isoformat(timespec="seconds"), "commande": command}
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            current = holder(client)
            if current:
                if int(current.get("pid") or 0) == os.getpid():
                    return True, ""
                return False, describe(current)
            try:
                os.remove(path)  # verrou d'un processus terminé : repris
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        atexit.register(release, client)
        return True, ""
    current = holder(client)
    return False, describe(current) if current else "verrou impossible à prendre"


def release(client: str) -> None:
    """Libère le verrou s'il appartient à ce processus."""
    path = lock_path(client)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if int(data.get("pid") or 0) == os.getpid():
        try:
            os.remove(path)
        except OSError:
            pass


def read_only(args) -> bool:
    """Commandes qui n'écrivent ni dans le worktree ni dans l'état de la génération : sans verrou."""
    return bool(getattr(args, "detect_only", False) or getattr(args, "profile_only", False)
                or getattr(args, "server_log", "") or getattr(args, "import_run", None) is not None
                or getattr(args, "import_url", ""))
