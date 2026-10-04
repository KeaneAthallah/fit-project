from __future__ import annotations

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def corpus_root() -> pathlib.Path:
    """The raw filing corpus.

    Tests that quote a figure read it from the filing rather than hardcoding a
    number they merely believe, so a mapping change cannot quietly disagree
    with the source.
    """
    root = REPO_ROOT / "XBRL"
    if not root.is_dir():
        pytest.skip("XBRL corpus not present")
    return root