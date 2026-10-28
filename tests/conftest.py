import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _runs_in_tmp(tmp_path, monkeypatch):
    """Keep test logs out of the real runs/ folder."""
    monkeypatch.chdir(tmp_path)
    os.environ.setdefault("META_API_KEY", "test-key")
