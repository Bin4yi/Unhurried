import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import passport_store
from server.main import app

ROOT = Path(__file__).resolve().parent.parent
BLOB = {"v": 1, "kdf": "PBKDF2-SHA256", "rounds": 600000, "salt": "c2FsdA==", "iv": "aXY=",
        "ct": "Y2lwaGVy"}


def test_store_keeps_blob_as_is(tmp_path):
    passport_store.save("p_12345678", BLOB, tmp_path)
    assert json.loads((tmp_path / "p_12345678.json").read_text()) == BLOB
    assert passport_store.load("p_12345678", tmp_path) == BLOB
    assert passport_store.delete("p_12345678", tmp_path)
    assert passport_store.load("p_12345678", tmp_path) is None


@pytest.mark.parametrize("bad", [{"profile": {"timing": {}}}, {**BLOB, "plain": "x"},
                                 {**BLOB, "ct": 5}])
def test_store_rejects_anything_but_a_locked_blob(bad, tmp_path):
    with pytest.raises(passport_store.PassportError):
        passport_store.save("p_12345678", bad, tmp_path)


def test_bad_ids_rejected(tmp_path):
    for pid in ["../etc", "short", "a" * 80]:
        with pytest.raises(passport_store.PassportError):
            passport_store.save(pid, BLOB, tmp_path)


def test_profile_endpoints():
    c = TestClient(app)
    assert c.get("/profile/p_abcdefgh").status_code == 404
    assert c.post("/profile/p_abcdefgh", json=BLOB).json() == {"ok": True}
    assert c.get("/profile/p_abcdefgh").json() == BLOB
    assert c.post("/profile/p_abcdefgh", json={"plain": 1}).status_code == 400
    assert c.delete("/profile/p_abcdefgh").json() == {"deleted": True}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_crypto_round_trip_in_node():
    r = subprocess.run(["node", str(ROOT / "tests/js/passport_crypto.test.mjs")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
