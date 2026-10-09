"""Issue #161 item 3: ``tools/check_hygiene.py``'s ``_GENERIC_USERNAMES`` gains ``agent`` (this
container's own account name) and a few other common-word account names, without weakening the
local-username rule for a real, non-generic account name.

This file loads ``tools/check_hygiene.py`` the same way ``tests/test_hygiene.py`` does (by path,
since it is a script, not an installed package), as its own module so it does not share that
other file's module-level state.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "check_hygiene.py"

_spec = importlib.util.spec_from_file_location("check_hygiene_generic_usernames", SCRIPT)
hygiene = importlib.util.module_from_spec(_spec)
sys.modules["check_hygiene_generic_usernames"] = hygiene
_spec.loader.exec_module(hygiene)

_REAL_LOCAL_USERNAMES = hygiene._local_usernames


@pytest.fixture(autouse=True)
def _no_ambient_account(monkeypatch):
    """Start every test with the local-username rule off; the fixtures below turn it on
    explicitly, the same way tests/test_hygiene.py does."""
    monkeypatch.setattr(hygiene, "_local_usernames", lambda: frozenset())
    hygiene._username_pattern.cache_clear()
    yield
    hygiene._username_pattern.cache_clear()


@pytest.fixture
def real_account(monkeypatch):
    """Drive the REAL ``_local_usernames()`` (generic-word filter included) from fake
    environment variables, rather than stubbing ``_local_usernames`` itself -- stubbing it
    would bypass exactly the filter this test file is about."""
    monkeypatch.setattr(hygiene, "_local_usernames", _REAL_LOCAL_USERNAMES)
    for var in ("USER", "USERNAME", "LOGNAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(hygiene.getpass, "getuser", lambda: "")  # too short to match anything

    def use(**env: str) -> None:
        for var, value in env.items():
            monkeypatch.setenv(var, value)
        hygiene._username_pattern.cache_clear()

    yield use


def notebook(*, outputs=None) -> dict:
    return {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 1,
                "id": "c1",
                "metadata": {},
                "source": "x = 1",
                "outputs": outputs or [],
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def stream(text: str) -> dict:
    return {"output_type": "stream", "name": "stdout", "text": [text]}


def scan(tmp_path: Path, nb: dict):
    path = tmp_path / "notebook.ipynb"
    path.write_text(json.dumps(nb), encoding="utf-8")
    return hygiene.scan_file(path)


def rules(findings) -> set[str]:
    return {f.rule for f in findings}


NEW_GENERIC_NAMES = ("agent", "task", "worker", "sandbox", "service")


# --- the new names are in the set, long enough to need it, and filtered out by name ----


def test_new_names_are_in_the_generic_set_and_pass_the_minimum_length():
    for name in NEW_GENERIC_NAMES:
        assert name in hygiene._GENERIC_USERNAMES
        assert len(name) >= hygiene._MIN_USERNAME_LENGTH  # else length alone would already do it


def test_generic_username_list_still_excludes_short_words_by_length_alone():
    # "bot" is as common a container account name as the ones just added, but at 3 characters
    # it is already excluded by _MIN_USERNAME_LENGTH, so it was deliberately left out of
    # _GENERIC_USERNAMES: adding it would change nothing, since it never reaches that check.
    assert "bot" not in hygiene._GENERIC_USERNAMES
    assert len("bot") < hygiene._MIN_USERNAME_LENGTH


@pytest.mark.parametrize("name", NEW_GENERIC_NAMES)
def test_local_usernames_filters_out_each_new_name(name, monkeypatch):
    monkeypatch.setattr(hygiene, "_local_usernames", _REAL_LOCAL_USERNAMES)
    for var in ("USER", "USERNAME", "LOGNAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(hygiene.getpass, "getuser", lambda: "")
    monkeypatch.setenv("USER", name.upper())  # case-insensitive, like the existing entries
    assert hygiene._local_usernames() == frozenset()


# --- end to end: a container whose own account is one of the new names stays quiet -----


def test_new_generic_account_names_are_never_checked_by_name(real_account, tmp_path):
    for name in NEW_GENERIC_NAMES:
        real_account(USER=name)
        # Ordinary prose using the word, including as this container's own running-account
        # name -- the exact false positive that motivated adding "agent": printed stdout such
        # as "the agent will retry" tripped the local-username rule on ordinary prose.
        nb = notebook(outputs=[stream(f"the {name} will retry the request\n")])
        assert scan(tmp_path, nb) == [], name


def test_no_account_name_means_the_name_check_stays_off_too(real_account, tmp_path):
    real_account()  # every source empty/too-short, same as the pre-existing behaviour
    assert scan(tmp_path, notebook(outputs=[stream("agent, task, worker\n")])) == []


# --- the rule is NOT weakened for a real, non-generic account name ---------------------


def test_a_real_username_is_still_flagged_when_agent_is_also_a_reported_name(
    real_account, tmp_path
):
    # A container can report more than one name for the same account (USER, LOGNAME, ...);
    # one of them being a newly-generic word must not blind the check to another, real
    # personal name reported alongside it.
    real_account(USER="agent", LOGNAME="quillfeather")
    assert hygiene._local_usernames() == {"quillfeather"}  # "agent" filtered, "" too short
    found = scan(tmp_path, notebook(outputs=[stream("hello from QUILLFEATHER!\n")]))
    assert rules(found) == {"local-username"}
    assert all("quillfeather" not in (f.snippet + f.location).lower() for f in found)
    # Prose naming the generic word alone still raises nothing, confirming the real name
    # (not the generic one) is what triggered the finding above.
    assert scan(tmp_path, notebook(outputs=[stream("agent output follows\n")])) == []


def test_a_name_merely_containing_a_new_generic_word_is_still_a_real_checkable_username(
    real_account, tmp_path
):
    # "agentsmith" is not "agent": whole-word matching (tests/test_hygiene.py) already keeps
    # a longer word from matching the shorter generic one, and this new entry must not change
    # that boundary in the other direction either -- a real account literally named
    # "agentsmith" is still a real, non-generic username and must still be caught.
    real_account(USER="agentsmith")
    assert hygiene._local_usernames() == {"agentsmith"}
    found = scan(tmp_path, notebook(outputs=[stream("run by agentsmith today\n")]))
    assert rules(found) == {"local-username"}
