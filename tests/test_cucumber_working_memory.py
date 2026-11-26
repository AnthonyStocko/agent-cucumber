"""Mémoire de travail d'un lot : consigne injectée, contenu relu à chaque appel, persistance dans l'état."""
from tools import cucumber_working_memory as wm


def test_block_injects_rules_and_current_content(tmp_path, monkeypatch):
    monkeypatch.delenv("CUCUMBER_WORKING_MEMORY", raising=False)
    lot = {"numero": 7}
    first = wm.block(str(tmp_path), lot, 45)
    assert "memoire_lot_7.md" in first and "premier appel" in first and "tour 45" in first
    (tmp_path / "memoire_lot_7.md").write_text("# Lot 7\n## Faits établis\n- FAT.L53.01.00.3 : storage_allowed=false",
                                                encoding="utf-8")
    assert "storage_allowed=false" in wm.block(str(tmp_path), lot, 45)
    wm.save(str(tmp_path), lot)
    assert "storage_allowed=false" in lot["memoire_travail"]


def test_memory_restored_from_state_in_new_run_dir(tmp_path):
    lot = {"numero": 3, "memoire_travail": "# Lot 3\n- piste écartée : réserves ACS"}
    out = wm.block(str(tmp_path / "nouveau"), lot)
    assert "réserves ACS" in out and (tmp_path / "nouveau" / "memoire_lot_3.md").exists()


def test_oversized_memory_asks_for_compaction(tmp_path):
    (tmp_path / "memoire_lot_1.md").write_text("x" * (wm.MAX_CHARS + 100), encoding="utf-8")
    assert "COMPACTE" in wm.block(str(tmp_path), {"numero": 1})


def test_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CUCUMBER_WORKING_MEMORY", "0")
    assert wm.block(str(tmp_path), {"numero": 1}) == ""
