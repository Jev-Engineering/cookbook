"""Adversarial checks on the recipe guard's backend-derived call evidence (#213).

Every rule has a case that must pass and cases that must fail. The recipe-27 defect (one example
decided twice, the stored-response count still matching the README) is reproduced end to end:
the old proxy passes it, the audited route fails it and names the replay key.
"""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path

import pytest

from jev_cookbook import Noul, replay_key
from jev_cookbook._canonical import canonical_json
from jev_cookbook.accounting import (
    AUDIT_PREFIX,
    BUDGET_FILE,
    NOTE_BEGIN,
    NOTE_END,
    PROFILE_COUNTERS,
    parse_budget,
    render_budget_note,
)

spec = importlib.util.spec_from_file_location(
    "request_audit_for_tests", Path(__file__).with_name("request_audit.py")
)
audit_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_guard)

SETUP = """from jev_cookbook import AuditedBackend, get_backend, Noul
backend = AuditedBackend(get_backend(script=lambda state, qs, rng: {"present": 0.9}))
questions = {"present": Noul(instructions="The package is present.")}
"""
CALLS = 'for state in ("a", "a", "b"):\n    backend.decide(state, questions)'
FINAL = "print(backend.audit_json())"

SETUP_TWO = """from jev_cookbook import AuditedBackend, audit_json, get_backend, Noul
arm_a = AuditedBackend(get_backend(script=lambda state, qs, rng: {"present": 0.9}), label="arm-a")
arm_b = AuditedBackend(get_backend(script=lambda state, qs, rng: {"present": 0.1}), label="arm-b")
questions = {"present": Noul(instructions="The package is present.")}
"""
CALLS_TWO = (
    'for state in ("a", "b"):\n    arm_a.decide(state, questions)\n'
    'for state in ("a", "b", "c"):\n    arm_b.decide(state, questions)'
)
FINAL_TWO = "print(audit_json(arm_a, arm_b))"

QUESTIONS = {"present": Noul(instructions="The package is present.")}
KEY = {state: replay_key(state, QUESTIONS) for state in "abc"}


def execute(sources, monkeypatch):
    """Cells with the outputs a real execution of ``sources`` produces."""
    monkeypatch.delenv("JEV_COOKBOOK_LIVE", raising=False)
    namespace = {}
    out = []
    for index, source in enumerate(sources, 1):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            exec(source, namespace)
        out.append(
            {
                "cell_type": "code",
                "source": source,
                "execution_count": index,
                "outputs": [{"output_type": "stream", "name": "stdout", "text": stream.getvalue()}],
            }
        )
    return out


@pytest.fixture
def cells(monkeypatch):
    return execute((SETUP, CALLS, FINAL), monkeypatch)


@pytest.fixture
def two_cells(monkeypatch):
    return execute((SETUP_TWO, CALLS_TWO, FINAL_TWO), monkeypatch)


def alter_payload(cells, change):
    output = cells[-1]["outputs"][0]
    payload = json.loads(output["text"].removeprefix(AUDIT_PREFIX))
    change(payload)
    output["text"] = AUDIT_PREFIX + canonical_json(payload) + "\n"


def budget(requests, distinct=None, fixtures=None, label="main", **more):
    body = {"requests": requests, "fixtures": fixtures, **more}
    if distinct is not None:
        body["distinct"] = distinct
    return parse_budget({"schema": 1, "backends": {label: body}})


def two_arm_budget(a=2, b=3, **b_more):
    return parse_budget(
        {
            "schema": 1,
            "backends": {
                "arm-a": {"requests": a, "fixtures": None},
                "arm-b": {"requests": b, "fixtures": None, **b_more},
            },
        }
    )


# --------------------------------------------------------------------------------------------
# the evidence: what the notebook really did
# --------------------------------------------------------------------------------------------


def test_actual_execution_counts_duplicates_per_backend(cells):
    (evidence,) = audit_guard.audited_evidence(cells)
    assert evidence.label == "main"
    assert evidence.keys == (KEY["a"], KEY["a"], KEY["b"])
    assert evidence.profile_totals == {}


def test_several_audited_backends_each_keep_their_own_ledger(two_cells):
    first, second = audit_guard.audited_evidence(two_cells)
    assert (first.label, len(first.keys)) == ("arm-a", 2)
    assert (second.label, len(second.keys)) == ("arm-b", 3)
    # the key "a" is asked of both backends: two backends, two requests, not one shared one
    assert first.keys[0] == second.keys[0] == KEY["a"]


def test_a_single_backend_may_also_print_through_the_group_form(monkeypatch):
    sources = (SETUP.replace("AuditedBackend,", "AuditedBackend, audit_json,"), CALLS)
    cells = execute((*sources, "print(audit_json(backend))"), monkeypatch)
    assert len(audit_guard.audited_evidence(cells)[0].keys) == 3


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(schema=1),
        lambda p: p.update(schema=True),
        lambda p: p.update(extra=0),
        lambda p: p.pop("backends"),
        lambda p: p["backends"].append(p["backends"][0]),
        lambda p: p["backends"].clear(),
        lambda p: p["backends"][0].update(decide_calls=2),
        lambda p: p["backends"][0].update(decide_calls=True),
        lambda p: p["backends"][0].update(distinct_requests=3),
        lambda p: p["backends"][0].update(distinct_requests=True),
        lambda p: p["backends"][0].update(extra=0),
        lambda p: p["backends"][0].update(label="other"),
        lambda p: p["backends"][0].update(profile_totals={"unregistered": 1}),
        lambda p: p["backends"][0].update(profile_totals={}),
        lambda p: p["backends"][0]["calls"][0].update(returned=False),
        lambda p: p["backends"][0]["calls"][0].update(returned=1),
        lambda p: p["backends"][0]["calls"][0].update(replay_key="invalid"),
        lambda p: p["backends"][0]["calls"][0].update(extra=0),
        lambda p: p["backends"][0]["calls"][0].update(profile={"unregistered": 1}),
        lambda p: p["backends"][0]["calls"][0].update(profile={}),
        lambda p: p["backends"][0].pop("calls"),
    ],
)
def test_malformed_or_self_declared_summaries_fail(cells, change):
    alter_payload(cells, change)
    with pytest.raises(AssertionError):
        audit_guard.audited_evidence(cells)


def test_a_missing_backend_entry_in_a_multi_backend_audit_fails(two_cells):
    alter_payload(two_cells, lambda p: p["backends"].pop())
    with pytest.raises(AssertionError, match="exactly the notebook's audited backends"):
        audit_guard.audited_evidence(two_cells)


def test_reordered_entries_do_not_match_the_notebook(two_cells):
    alter_payload(two_cells, lambda p: p["backends"].reverse())
    with pytest.raises(AssertionError, match="does not match the notebook"):
        audit_guard.audited_evidence(two_cells)


@pytest.mark.parametrize(
    "source",
    [
        'print("JEV_REQUEST_AUDIT forged")',
        "if False:\n    print(backend.audit_json())",
        'print(backend.audit_json())\nbackend.decide("a", questions)',
        'print(backend.audit_json(), "extra")',
    ],
)
def test_final_source_must_emit_the_shared_audit(cells, source):
    cells[-1]["source"] = source
    with pytest.raises(AssertionError, match="final code cell"):
        audit_guard.audited_evidence(cells)


@pytest.mark.parametrize(
    "source",
    [
        "print(audit_json(arm_a))",
        "print(audit_json(arm_b, arm_a))",
        "print(arm_a.audit_json())",
        "print(audit_json(arm_a, arm_b, arm_a))",
        'print(audit_json(arm_a, arm_b))\nprint("x")',
    ],
)
def test_the_final_cell_of_a_multi_backend_notebook_names_every_backend_in_order(two_cells, source):
    two_cells[-1]["source"] = source
    with pytest.raises(AssertionError, match="final code cell"):
        audit_guard.audited_evidence(two_cells)


@pytest.mark.parametrize(
    "extra",
    [
        "backend = object()",
        "print = lambda *args: None",
        "AuditedBackend = lambda value: value",
        "get_backend = lambda **kwargs: None",
        "backend.audit_json = lambda: 'forged'",
        "backend.decide = lambda *args: None",
        "backend._calls.clear()",
        "other = get_backend(script=lambda *args: {})",
        "other = module.get_backend(script=lambda *args: {})",
        "other = AuditedBackend(get_backend(script=lambda *args: {}), label='third')",
        "def print(value):\n    pass",
        "from helpers import fake as backend",
        "from helpers import fake as print",
        "import helpers as get_backend",
        "if True:\n    from helpers import fake as AuditedBackend",
        "from helpers import *",
        "AuditedBackend.audit_json = lambda self: 'forged'",
        "setattr(AuditedBackend, 'audit_json', lambda self: 'forged')",
        "try:\n    pass\nexcept Exception as backend:\n    pass",
        "match {}:\n    case {'backend': backend}:\n        pass",
    ],
)
def test_rebinding_bypass_or_extra_backend_construction_fails(cells, extra):
    cells[1]["source"] += "\n" + extra
    with pytest.raises(AssertionError):
        audit_guard.audited_evidence(cells)


# A second backend the ledger cannot see. Each of these made the audit line accept a notebook
# whose second backend sent requests on its own budget (the recipe-37 defect), or hid a
# constructor behind a rename, a classmethod, a module attribute, a lookup by name or a subclass.
HIDDEN_BACKENDS = [
    "from jev_cookbook import get_backend as gb\nraw = gb(script=lambda *args: {})",
    "from jev_cookbook import ScriptedBackend as SB\nraw = SB(lambda *args: {})",
    "from jev_cookbook import ReplayBackend\nraw = ReplayBackend.from_json('other.json')",
    "from jev_cookbook import ReplayBackend as RB\nraw = RB.from_json('other.json')",
    "from jev_cookbook import ReplayBackend\nraw = ReplayBackend({})",
    "from jev_cookbook import LiveBackend\nraw = LiveBackend('jev-preview')",
    "from jev_cookbook.backends import ScriptedBackend\nraw = ScriptedBackend(lambda *args: {})",
    "import jev_cookbook\nraw = jev_cookbook.ReplayBackend.from_json('other.json')",
    "import jev_cookbook.backends as b\nraw = b.get_backend(script=lambda *args: {})",
    "import jev_cookbook as jc\nraw = jc.get_backend(script=lambda *args: {})",
    "from jev_cookbook.live import live_backend_from_env\nraw = live_backend_from_env()",
    "gb = get_backend\nraw = gb(script=lambda *args: {})",
    "make = ReplayBackend.from_json\nraw = make('other.json')",
    "class Mine(ScriptedBackend):\n    pass",
    "import jev_cookbook\nraw = getattr(jev_cookbook, 'get_backend')(script=lambda *args: {})",
    "import jev_cookbook\nraw = getattr(jev_cookbook, 'get_back' + 'end')(script=lambda *args: {})",
    "raw = getattr(__import__('jev_cookbook'), 'get_backend')(script=lambda *args: {})",
    "raw = globals()['get_backend'](script=lambda *args: {})",
    "raw = eval('get_backend')(script=lambda *args: {})",
    "exec('raw = get_backend(script=lambda *args: {})')",
    "import importlib\nraw = importlib.import_module('jev_cookbook').get_backend(script=lambda *a: {})",
    "import jev_cookbook\nraw = jev_cookbook.__dict__['get_backend'](script=lambda *args: {})",
    "name = 'get_backend'",
]


# The line every published notebook and the scaffolder's measured cell carry. It must pass.
RECORDED_DATES_LINE = (
    'dates = ", ".join(getattr(backend, "recorded_dates", ()) or ()) or "this run"'
)


@pytest.mark.parametrize(
    "line",
    [
        RECORDED_DATES_LINE,
        'dates = getattr(backend, "recorded_dates", ())',
        'dates = getattr(backend, "recorded_dates")',
        "value = getattr(questions, 'present', None)",
    ],
)
def test_a_getattr_with_a_written_out_attribute_is_allowed(cells, line):
    """``getattr(obj, "literal"[, default])`` cannot be a constructor lookup (a literal constructor
    name is rejected by the string rule), and the measured cell of every recipe uses it."""
    cells[1]["source"] += "\n" + line
    (evidence,) = audit_guard.audited_evidence(cells)
    assert evidence.label == "main"


@pytest.mark.parametrize(
    "line",
    [
        "import jev_cookbook\nraw = getattr(jev_cookbook, name)",
        "import jev_cookbook\nraw = getattr(jev_cookbook, 'get_' + 'backend')",
        "import jev_cookbook\nraw = getattr(jev_cookbook, f'get_{kind}')",
        "raw = getattr(backend)",
        "raw = getattr(*args)",
        "raw = getattr(backend, *names)",
        "raw = getattr(backend, name=1)",
        "raw = getattr(backend, 'a', 'b', 'c')",
        "g = getattr\nraw = g(backend, 'recorded_dates')",
        "raw = list(map(getattr, [backend], ['recorded_dates']))",
    ],
)
def test_a_getattr_with_a_computed_attribute_fails_and_names_the_cause(cells, line):
    cells[1]["source"] += "\n" + line
    with pytest.raises(AssertionError, match="getattr with a computed attribute name"):
        audit_guard.audited_evidence(cells)


def test_a_getattr_of_a_literal_constructor_name_is_still_rejected(cells):
    cells[1]["source"] += "\nimport jev_cookbook\nraw = getattr(jev_cookbook, 'get_backend')"
    with pytest.raises(AssertionError, match="names a backend constructor"):
        audit_guard.audited_evidence(cells)


@pytest.mark.parametrize(
    "line",
    [
        "import operator\nraw = operator.attrgetter('get_back' + 'end')(operator)",
        "from operator import attrgetter\nraw = attrgetter('get_back' + 'end')",
        "from operator import attrgetter as ag",
        "import operator\nraw = operator.methodcaller('get_back' + 'end')",
        "import builtins\nraw = builtins.getattr(builtins, 'get_back' + 'end')",
        "from builtins import getattr as g",
        "raw = __builtins__.getattr(backend, 'get_back' + 'end')",
        "import jev_cookbook\nraw = jev_cookbook.__getattr__('get_back' + 'end')",
        "import inspect\nraw = inspect.getattr_static(backend, 'get_back' + 'end')",
    ],
)
def test_other_computed_lookup_primitives_are_rejected_too(cells, line):
    cells[1]["source"] += "\n" + line
    with pytest.raises(AssertionError):
        audit_guard.audited_evidence(cells)


@pytest.mark.parametrize("extra", HIDDEN_BACKENDS)
def test_a_backend_the_ledger_cannot_see_is_rejected_in_every_spelling(cells, extra):
    cells[1]["source"] += "\n" + extra
    with pytest.raises(AssertionError):
        audit_guard.audited_evidence(cells)


def test_the_aliased_second_backend_that_made_four_extra_requests_is_rejected(monkeypatch):
    """The measured bypass: the audit line honestly reports 3 calls and a second, unaudited
    backend decides four more on its own budget."""
    sources = (
        SETUP
        + "from jev_cookbook import get_backend as gb\nraw = gb(script=lambda *a: {'present': 0.5})\n",
        CALLS + '\nfor state in ("d", "e", "f", "g"):\n    raw.decide(state, questions)',
        FINAL,
    )
    cells = execute(sources, monkeypatch)
    assert cells[-1]["outputs"][0]["text"].count('"returned":true') == 3  # the audit says 3
    with pytest.raises(AssertionError, match="alias hides a backend constructor"):
        audit_guard.audited_evidence(cells)


@pytest.mark.parametrize(
    "extra",
    [
        "from jev_cookbook import ReplayBackend",
        "from jev_cookbook import ScriptedBackend, ReplayBackend, LiveBackend",
        "from jev_cookbook.live import BudgetExceeded\ntry:\n    pass\nexcept BudgetExceeded:\n    pass",
    ],
)
def test_naming_a_constructor_without_using_it_is_not_a_second_backend(cells, extra):
    cells[1]["source"] += "\n" + extra
    audit_guard.audited_evidence(cells)


@pytest.mark.parametrize(
    "extra",
    [
        "arm_b = object()",
        "audit_json = lambda *backends: 'forged'",
        "arm_a.audit = lambda: {}",
        "third = get_backend(script=lambda *args: {})",
    ],
)
def test_a_second_audited_backend_is_protected_like_the_first(two_cells, extra):
    two_cells[1]["source"] += "\n" + extra
    with pytest.raises(AssertionError):
        audit_guard.audited_evidence(two_cells)


@pytest.mark.parametrize(
    "setup",
    [
        # no label on the second wrapper: both would be "main"
        SETUP_TWO.replace(', label="arm-b"', ""),
        SETUP_TWO.replace('label="arm-b"', 'label="arm-a"'),
        SETUP_TWO.replace('label="arm-b"', "label=name"),
        SETUP_TWO.replace('label="arm-b"', 'label="Arm B"'),
        SETUP_TWO.replace('label="arm-b"', 'name="arm-b"'),
        SETUP_TWO.replace("arm_b = ", "arm_a = "),
        SETUP_TWO.replace("audit_json, ", ""),
        SETUP_TWO.replace("import AuditedBackend, audit_json", "import AuditedBackend"),
    ],
)
def test_labels_and_bindings_of_several_backends_must_be_literal_and_distinct(two_cells, setup):
    two_cells[0]["source"] = setup
    with pytest.raises(AssertionError):
        audit_guard.audited_evidence(two_cells)


def test_fake_import_is_not_shared_evidence(cells):
    cells[0]["source"] = cells[0]["source"].replace("from jev_cookbook", "from fake")
    with pytest.raises(AssertionError, match="shared AuditedBackend"):
        audit_guard.audited_evidence(cells)


def test_a_fake_audit_json_import_is_not_shared_evidence(two_cells):
    two_cells[0]["source"] = (
        two_cells[0]["source"].replace(
            "import AuditedBackend, audit_json,", "import AuditedBackend,"
        )
        + "\nfrom fake import audit_json"
    )
    with pytest.raises(AssertionError):
        audit_guard.audited_evidence(two_cells)


def test_relative_import_cannot_supply_shared_evidence(cells):
    cells[0]["source"] = cells[0]["source"].replace("from jev_cookbook", "from .jev_cookbook")
    with pytest.raises(AssertionError, match="relative"):
        audit_guard.audited_evidence(cells)


def test_duplicate_json_fields_and_duplicate_output_are_rejected(cells):
    output = cells[-1]["outputs"][0]
    original = output["text"]
    output["text"] = original.replace('"schema":2,', '"schema":2,"schema":2,')
    with pytest.raises(AssertionError, match="canonical"):
        audit_guard.audited_evidence(cells)
    output["text"] = original * 2
    with pytest.raises(AssertionError, match="exactly"):
        audit_guard.audited_evidence(cells)


def test_missing_or_reordered_execution_evidence_is_rejected(cells):
    cells[0]["execution_count"] = None
    with pytest.raises(AssertionError, match="execution evidence"):
        audit_guard.audited_evidence(cells)
    cells[0]["execution_count"] = 5
    with pytest.raises(AssertionError, match="in order"):
        audit_guard.audited_evidence(cells)


def test_missing_output_cannot_fall_back_to_legacy_count(cells):
    cells[-1]["outputs"] = []
    with pytest.raises(AssertionError):
        audit_guard.audited_evidence(cells)


def test_unaudited_notebook_retains_legacy_route(cells):
    legacy = copy.deepcopy(cells[:2])
    legacy[0]["source"] = "from jev_cookbook import get_backend"
    assert audit_guard.audited_evidence(legacy) is None


# --------------------------------------------------------------------------------------------
# the extension point: a registered profile is accepted, checked and declared
# --------------------------------------------------------------------------------------------


def test_an_unregistered_profile_is_rejected_and_a_registered_one_is_verified(monkeypatch):
    monkeypatch.setitem(
        PROFILE_COUNTERS, "extras", lambda state, qs, assets: 2 if state == "b" else 0
    )
    cells = execute((SETUP, CALLS, FINAL), monkeypatch)
    (evidence,) = audit_guard.audited_evidence(cells)
    assert evidence.profile_totals == {"extras": 2}
    audit_guard.check_against_declaration(
        [evidence], budget(3, 2, profile={"extras": 2}), Path("unused")
    )
    with pytest.raises(AssertionError, match="profile"):
        audit_guard.check_against_declaration([evidence], budget(3, 2), Path("unused"))
    with pytest.raises(AssertionError, match="profile"):
        audit_guard.check_against_declaration(
            [evidence], budget(3, 2, profile={"extras": 1}), Path("unused")
        )
    alter_payload(cells, lambda p: p["backends"][0]["profile_totals"].update(extras=9))
    with pytest.raises(AssertionError, match="profile totals"):
        audit_guard.audited_evidence(cells)
    monkeypatch.delitem(PROFILE_COUNTERS, "extras")
    with pytest.raises(AssertionError, match="unknown profile"):
        audit_guard.audited_evidence(cells)  # committed while registered, read after it was not


# --------------------------------------------------------------------------------------------
# the declaration: count, repeats (naming the key), inventory
# --------------------------------------------------------------------------------------------


def evidence_of(cells):
    return audit_guard.audited_evidence(cells)


def test_declared_repeats_pass_and_undeclared_repeats_fail_naming_the_key(cells):
    evidence = evidence_of(cells)
    audit_guard.check_against_declaration(evidence, budget(3, 2), Path("unused"))
    with pytest.raises(AssertionError) as caught:
        audit_guard.check_against_declaration(evidence, budget(3), Path("unused"))
    message = str(caught.value)
    assert KEY["a"] in message and KEY["b"] not in message
    assert "decided the same request 2 times" in message and "1 repeated key(s)" in message


@pytest.mark.parametrize(
    "requests,distinct,expected",
    [
        (4, 2, r"made 3 decide\(\) calls"),
        (2, 1, r"made 3 decide\(\) calls"),
        (2, 2, "decided the same request"),
        (3, 3, "decided the same request"),
        (3, 1, "made 2 distinct requests"),
    ],
)
def test_a_declaration_that_differs_from_the_execution_fails(cells, requests, distinct, expected):
    with pytest.raises(AssertionError, match=expected):
        audit_guard.check_against_declaration(
            evidence_of(cells), budget(requests, distinct), Path("unused")
        )


def test_one_more_repeat_than_declared_fails_even_when_the_total_still_fits(monkeypatch):
    more = CALLS.replace('("a", "a", "b")', '("a", "a", "b", "b")')
    cells = execute((SETUP, more, FINAL), monkeypatch)
    with pytest.raises(AssertionError, match="4 decide"):
        audit_guard.check_against_declaration(evidence_of(cells), budget(3, 2), Path("unused"))
    audit_guard.check_against_declaration(evidence_of(cells), budget(4, 2), Path("unused"))


def test_the_declared_backends_must_be_the_audited_backends(cells, two_cells):
    with pytest.raises(AssertionError, match="declares backends"):
        audit_guard.check_against_declaration(
            evidence_of(cells), budget(3, 2, label="other"), Path("unused")
        )
    with pytest.raises(AssertionError, match="declares backends"):
        audit_guard.check_against_declaration(evidence_of(two_cells), budget(3, 2), Path("unused"))


def test_each_backend_of_several_is_checked_against_its_own_declaration(two_cells):
    evidence = evidence_of(two_cells)
    audit_guard.check_against_declaration(evidence, two_arm_budget(), Path("unused"))
    with pytest.raises(AssertionError, match="'arm-a' made 2"):
        audit_guard.check_against_declaration(evidence, two_arm_budget(a=3), Path("unused"))
    with pytest.raises(AssertionError, match="'arm-b' made 3"):
        audit_guard.check_against_declaration(evidence, two_arm_budget(b=4), Path("unused"))


def write_inventory(folder, keys):
    (folder / "fixtures").mkdir(exist_ok=True)
    (folder / "fixtures" / "responses.json").write_text(json.dumps(dict.fromkeys(keys, {})))


@pytest.mark.parametrize(
    "keys",
    [set(), {"0" * 64}, {KEY["a"], KEY["b"], "0" * 64}, {KEY["a"]}],
)
def test_inventory_gaps_fail_even_when_counts_can_match(cells, tmp_path, keys):
    write_inventory(tmp_path, keys)
    with pytest.raises(AssertionError, match="inventory"):
        audit_guard.check_against_declaration(
            evidence_of(cells), budget(3, 2, "fixtures/responses.json"), tmp_path
        )


def test_the_exact_inventory_passes_and_a_missing_declared_file_fails(cells, tmp_path):
    with pytest.raises(AssertionError, match="not found"):
        audit_guard.check_against_declaration(
            evidence_of(cells), budget(3, 2, "fixtures/responses.json"), tmp_path
        )
    write_inventory(tmp_path, {KEY["a"], KEY["b"]})
    audit_guard.check_against_declaration(
        evidence_of(cells), budget(3, 2, "fixtures/responses.json"), tmp_path
    )


def test_stored_answers_cannot_be_dodged_by_declaring_no_fixtures(cells, tmp_path):
    """A replay recipe that declares ``fixtures: null`` would never have its unused or missing
    stored answers counted (recipe 49 stores two answers its notebook never asks for)."""
    write_inventory(tmp_path, {KEY["a"], KEY["b"]})
    with pytest.raises(AssertionError, match="declares no backend that replays it"):
        audit_guard.check_against_declaration(evidence_of(cells), budget(3, 2), tmp_path)
    audit_guard.check_against_declaration(
        evidence_of(cells), budget(3, 2, "fixtures/responses.json"), tmp_path
    )


# --------------------------------------------------------------------------------------------
# the README: rendered, never typed
# --------------------------------------------------------------------------------------------

DECLARED = budget(3, 2)
README_HEAD = "# Recipe\n\n## Switch to live\n\nLive calls are opt-in.\n\n"
README_TAIL = "\n## What was and was not measured\n\n- N: 3\n"


def readme_with(block):
    return README_HEAD + block + README_TAIL


def test_the_rendered_paragraph_passes():
    audit_guard.check_readme_note(readme_with(render_budget_note(DECLARED)), DECLARED)


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda b: b.replace("**3**", "**2**"), "differs from the one rendered"),
        (lambda b: b.replace("=3", "=2"), "differs from the one rendered"),
        (lambda b: b.replace("retries included", "retries excluded"), "differs"),
        (lambda b: b + b, "exactly one"),
        (lambda b: b.replace(NOTE_END, ""), "exactly one"),
        (lambda b: b.replace(NOTE_BEGIN, ""), "exactly one"),
        (lambda b: "", "exactly one"),
        (lambda b: NOTE_END + "\n" + b.replace(NOTE_END, ""), "differs|out of order"),
    ],
)
def test_a_hand_edited_missing_or_doubled_paragraph_fails(mutate, expected):
    with pytest.raises(AssertionError, match=expected):
        audit_guard.check_readme_note(readme_with(mutate(render_budget_note(DECLARED))), DECLARED)


@pytest.mark.parametrize(
    "readme",
    [
        "# Recipe\n\n" + render_budget_note(DECLARED),
        "# Recipe\n\n## Switch to live\n\n## Other\n\n" + render_budget_note(DECLARED),
        render_budget_note(DECLARED) + "\n## Switch to live\n",
    ],
    ids=["no-section", "wrong-section", "before-section"],
)
def test_the_paragraph_must_sit_in_the_switch_to_live_section(readme):
    with pytest.raises(AssertionError, match="Switch to live"):
        audit_guard.check_readme_note(readme, DECLARED)


def test_a_stale_paragraph_fails_when_the_declaration_moves():
    stale = readme_with(render_budget_note(DECLARED))
    with pytest.raises(AssertionError, match="differs from the one rendered"):
        audit_guard.check_readme_note(stale, budget(4, 2))


@pytest.mark.parametrize(
    "prose",
    [
        "In live mode this notebook makes exactly one call for each of the 40 examples.",
        "This notebook makes exactly **3** calls.",
        "It makes exactly 3 requests.",
        "Set JEV_COOKBOOK_LIVE_MAX_REQUESTS=40 before running.",
        "Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS = 40` before running.",
    ],
)
def test_a_second_hand_typed_count_outside_the_paragraph_fails(prose):
    readme = readme_with(render_budget_note(DECLARED)) + "\n" + prose + "\n"
    with pytest.raises(AssertionError, match="outside the rendered block"):
        audit_guard.check_readme_note(readme, DECLARED)


# The cap and count phrasings the published READMEs use, which the two literal shapes above miss.
UNSHAPED_COUNT_PROSE = [
    "Raise `JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at least **99** before running this notebook live.",
    "Set it to 99 or higher before running this notebook live.",
    "raise `JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at least 99",
    "raise JEV_COOKBOOK_LIVE_MAX_REQUESTS to at least **44**.",
    "This notebook makes **74** calls in live mode.",
    "In live mode this notebook sends 74 requests.",
    "This notebook issues 99 live requests in total.",
    "A live run of this notebook costs 99 requests.",
    "It sends one request per example, 99 in all.",
    "Of the 192 task-level calls, 158 ask a request already asked.",
    "99 is above the default budget of 25, so raise the cap first.",
    "The budget is 99.",
    "Live mode needs a cap of at least 99.",
    "A run can use up to 99 attempts.",
]


@pytest.mark.parametrize("prose", UNSHAPED_COUNT_PROSE)
def test_a_count_or_cap_in_other_words_outside_the_paragraph_fails(prose):
    section = README_HEAD + render_budget_note(DECLARED) + "\n" + prose + "\n" + README_TAIL
    with pytest.raises(AssertionError, match="outside the rendered block"):
        audit_guard.check_readme_note(section, DECLARED)


# Sentences that carry a digit only a precision device of the scan exempts. Each is red when its
# device is removed (see the pull request body); the install sentence is the real one every
# published README carries.
LINK_STRIP_PROSE = "See [the request budget guard](../../docs/live-2.md#budget-guard) for retries."
VERSION_STRIP_PROSE = "Tested on Python 3.14 with jev-1.13.0, one request at a time."
CLAIM_WORD_PROSE = (
    'Install the SDK (`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1`'
    " and `JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a"
    " dependency of this repository), or record answers with the recorder described in"
    " [docs/live.md](../../docs/live.md)."
)


@pytest.mark.parametrize(
    "prose",
    [LINK_STRIP_PROSE, VERSION_STRIP_PROSE, CLAIM_WORD_PROSE],
    ids=["link-target-digit", "version-digit", "install-line-without-claim-word"],
)
def test_digits_that_only_a_precision_device_exempts_are_not_counts(prose):
    readme = README_HEAD + render_budget_note(DECLARED) + "\n" + prose + "\n" + README_TAIL
    audit_guard.check_readme_note(readme, DECLARED)
    assert audit_guard.stray_count_sentences(prose) == []


@pytest.mark.parametrize(
    "prose",
    [
        "The live backend's default request budget is 25 (`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, "
        "[docs/live.md](../../docs/live.md)); every attempt counts against that budget.",
        'Install the SDK (`pip install -e ".[live]"`) on Python 3.14 and set `TYPESAFE_API_KEY`.',
        "See [docs/live.md](../../docs/live.md#budget-guard) for retries.",
        "Pin a versioned model such as `jev-1.13.0`.",
    ],
)
def test_ordinary_live_section_prose_is_not_mistaken_for_a_count(prose):
    readme = README_HEAD + render_budget_note(DECLARED) + "\n" + prose + "\n" + README_TAIL
    audit_guard.check_readme_note(readme, DECLARED)


def test_the_measurements_section_may_state_numbers_freely():
    """Only the budget section is read: N in '## What was and was not measured' is not a cap."""
    readme = readme_with(render_budget_note(DECLARED)) + "- N: 36 validation and 36 test calls.\n"
    audit_guard.check_readme_note(readme, DECLARED)


def test_the_stray_count_scan_names_the_sentence_and_how_many_more():
    readme = (
        README_HEAD
        + render_budget_note(DECLARED)
        + "\nSet it to 99 or higher. This notebook makes 74 calls.\n"
        + README_TAIL
    )
    with pytest.raises(AssertionError, match=r"'Set it to 99 or higher\.' and 1 more"):
        audit_guard.check_readme_note(readme, DECLARED)


def test_naming_the_variable_without_a_number_is_not_a_second_count():
    readme = (
        readme_with(render_budget_note(DECLARED)) + "\n`JEV_COOKBOOK_LIVE_MAX_REQUESTS` caps it.\n"
    )
    audit_guard.check_readme_note(readme, DECLARED)


# --------------------------------------------------------------------------------------------
# the route: declaration, audited notebook and rendered paragraph come together
# --------------------------------------------------------------------------------------------


def make_recipe(tmp_path, cells, *, declaration=DECLARED, readme=None, inventory=None):
    folder = tmp_path / "example"
    (folder / "fixtures").mkdir(parents=True)
    keys = inventory if inventory is not None else {KEY["a"], KEY["b"]}
    write_inventory(folder, keys)
    (folder / "notebook.ipynb").write_text(json.dumps({"cells": cells}))
    if declaration is not None:
        body = {
            "schema": 1,
            "backends": {
                b.label: {
                    "requests": b.requests,
                    "distinct": b.distinct,
                    "fixtures": "fixtures/responses.json",
                }
                for b in declaration.backends
            },
        }
        (folder / BUDGET_FILE).write_text(json.dumps(body))
    if readme is None:
        readme = readme_with(render_budget_note(declaration or DECLARED))
        if declaration is None:
            readme = LEGACY_README
    (folder / "README.md").write_text(readme)
    return folder


def declared_with_inventory(requests, distinct):
    return budget(requests, distinct, fixtures="fixtures/responses.json")


def test_a_complete_route_returns_the_declared_total(cells, tmp_path):
    declaration = declared_with_inventory(3, 2)
    folder = make_recipe(tmp_path, cells, declaration=declaration)
    assert audit_guard.audit_recipe(folder, cells) == 3


LEGACY_README = "## Switch to live\nThis notebook makes exactly 2 calls.\n## What was\n"


def legacy_cells(cells):
    legacy = copy.deepcopy(cells[:2])
    legacy[0]["source"] = "from jev_cookbook import get_backend"
    return legacy


def test_neither_declaration_nor_audit_nor_paragraph_is_the_legacy_route(cells, tmp_path):
    legacy = legacy_cells(cells)
    folder = make_recipe(tmp_path, legacy, declaration=None, readme=LEGACY_README)
    assert audit_guard.audit_recipe(folder, legacy) is None


@pytest.mark.parametrize("marker", [NOTE_BEGIN, NOTE_END, NOTE_BEGIN + "\n" + NOTE_END])
def test_a_rendered_paragraph_without_a_declaration_or_an_audit_fails(cells, tmp_path, marker):
    """The third direction: a README that reads like audited output while nothing audits it
    (for a scripted recipe the legacy proxy would skip, so nothing at all would check it)."""
    legacy = legacy_cells(cells)
    readme = LEGACY_README.replace("## What was", marker + "\n## What was")
    folder = make_recipe(tmp_path, legacy, declaration=None, readme=readme)
    with pytest.raises(AssertionError, match="come together or not at all"):
        audit_guard.audit_recipe(folder, legacy)


def test_the_full_rendered_paragraph_alone_fails_with_an_actionable_message(cells, tmp_path):
    legacy = legacy_cells(cells)
    folder = make_recipe(
        tmp_path, legacy, declaration=None, readme=readme_with(render_budget_note(DECLARED))
    )
    with pytest.raises(AssertionError, match=f"no {BUDGET_FILE} and no audited notebook"):
        audit_guard.audit_recipe(folder, legacy)


def test_an_audited_notebook_without_a_declaration_fails(cells, tmp_path):
    folder = make_recipe(tmp_path, cells, declaration=None)
    with pytest.raises(AssertionError, match=BUDGET_FILE):
        audit_guard.audit_recipe(folder, cells)


def test_a_declaration_without_an_audited_notebook_fails(cells, tmp_path):
    legacy = copy.deepcopy(cells[:2])
    legacy[0]["source"] = "from jev_cookbook import get_backend"
    folder = make_recipe(tmp_path, legacy, declaration=declared_with_inventory(3, 2))
    with pytest.raises(AssertionError, match="emits no audit line"):
        audit_guard.audit_recipe(folder, legacy)


def test_a_malformed_declaration_file_fails_rather_than_falling_back(cells, tmp_path):
    folder = make_recipe(tmp_path, cells, declaration=declared_with_inventory(3, 2))
    (folder / BUDGET_FILE).write_text('{"schema": 1, "backends": {}}')
    with pytest.raises(ValueError, match="at least one"):
        audit_guard.audit_recipe(folder, cells)


def load_guard():
    guard_spec = importlib.util.spec_from_file_location(
        "recipe_guard_for_audit_tests", Path(__file__).with_name("test_recipe_guard.py")
    )
    guard = importlib.util.module_from_spec(guard_spec)
    guard_spec.loader.exec_module(guard)
    return guard


def run_guard(guard, folder, monkeypatch):
    monkeypatch.setattr(guard, "RECIPES_DIR", folder.parent)
    guard.test_the_live_budget_note_matches_the_request_audit({"slug": folder.name})


def test_the_guard_passes_a_complete_audited_recipe(cells, tmp_path, monkeypatch):
    folder = make_recipe(tmp_path, cells, declaration=declared_with_inventory(3, 2))
    run_guard(load_guard(), folder, monkeypatch)


def test_the_guard_fails_an_audited_recipe_whose_readme_count_was_edited(
    cells, tmp_path, monkeypatch
):
    declaration = declared_with_inventory(3, 2)
    readme = readme_with(render_budget_note(declaration).replace("**3**", "**2**"))
    folder = make_recipe(tmp_path, cells, declaration=declaration, readme=readme)
    with pytest.raises(AssertionError, match="differs from the one rendered"):
        run_guard(load_guard(), folder, monkeypatch)


# The recipe-27 defect, end to end (#213). The notebook decides example "a" twice; the stored
# responses hold one entry per distinct request, so a README that says 2 matches them.
def test_recipe_27_passes_the_old_proxy_and_fails_the_audited_route(cells, tmp_path, monkeypatch):
    guard = load_guard()
    legacy_folder = tmp_path / "legacy"
    (legacy_folder / "fixtures").mkdir(parents=True)
    write_inventory(legacy_folder, {KEY["a"], KEY["b"]})
    legacy = copy.deepcopy(cells[:2])
    legacy[0]["source"] = "from jev_cookbook import get_backend"
    (legacy_folder / "notebook.ipynb").write_text(json.dumps({"cells": legacy}))
    (legacy_folder / "README.md").write_text(
        "## Switch to live\nThis notebook makes exactly 2 calls.\n## What was\n"
    )
    run_guard(guard, legacy_folder, monkeypatch)  # the proxy cannot see the repeat: it passes

    declaration = declared_with_inventory(2, 2)  # the README's honest-looking count
    audited = make_recipe(tmp_path, cells, declaration=declaration)
    with pytest.raises(AssertionError) as caught:
        run_guard(guard, audited, monkeypatch)
    assert KEY["a"] in str(caught.value) and "decided the same request 2 times" in str(caught.value)


def test_the_legacy_proxy_still_fails_a_count_that_differs_from_the_fixtures(
    cells, tmp_path, monkeypatch
):
    folder = tmp_path / "legacy"
    (folder / "fixtures").mkdir(parents=True)
    write_inventory(folder, {KEY["a"], KEY["b"]})
    legacy = copy.deepcopy(cells[:2])
    legacy[0]["source"] = "from jev_cookbook import get_backend"
    (folder / "notebook.ipynb").write_text(json.dumps({"cells": legacy}))
    (folder / "README.md").write_text(
        "## Switch to live\nThis notebook makes exactly 3 calls.\n## What was\n"
    )
    with pytest.raises(AssertionError, match="README states 3"):
        run_guard(load_guard(), folder, monkeypatch)


def test_a_second_get_backend_in_a_helper_is_not_a_separate_budget_the_audit_can_hide(
    monkeypatch,
):
    """The recipe-37 defect: a second backend has its own budget. In the notebook it cannot be
    constructed unwrapped (see the construction cases above); wrapped, it must be declared."""
    sources = (
        SETUP_TWO,
        CALLS_TWO,
        FINAL_TWO,
    )
    cells = execute(sources, monkeypatch)
    evidence = evidence_of(cells)
    with pytest.raises(AssertionError, match="declares backends"):
        audit_guard.check_against_declaration(evidence, budget(2, label="arm-a"), Path("unused"))


# --------------------------------------------------------------------------------------------
# #313: the image profile through the guard
# --------------------------------------------------------------------------------------------

IMAGE_SETUP = """import base64, io
from PIL import Image
from jev_cookbook import AuditedBackend, get_backend, Noul
backend = AuditedBackend(get_backend(script=lambda state, qs, rng: {n: 0.9 for n in qs}))
data = io.BytesIO()
Image.new("RGB", (280, 280), "pink").save(data, format="PNG")
assets = {"<ruler>": {"type": "image", "format": "png",
                       "data_base64": base64.b64encode(data.getvalue()).decode("ascii")}}
questions = {n: Noul(instructions="Does it fit <ruler>?") for n in ("a", "b", "c")}
"""
IMAGE_CALLS = (
    'backend.decide({"photo": "<ruler>"}, questions, assets=assets)\n'
    'backend.decide({"photo": "no image"}, {"a": Noul(instructions="Plain text?")})'
)


def test_image_counts_in_a_committed_audit_are_verified_and_compared_with_the_declaration(
    monkeypatch,
):
    cells = execute((IMAGE_SETUP, IMAGE_CALLS, FINAL), monkeypatch)
    (evidence,) = audit_guard.audited_evidence(cells)
    # Hand-computed: one reference in the state and one in each of three instructions = 4 copies of
    # one image on the first call; the second call carries no image and states nothing.
    assert evidence.profile_totals == {"images": 4, "distinct_images": 1}
    declared = budget(2, profile={"images": 4, "distinct_images": 1})
    audit_guard.check_against_declaration([evidence], declared, Path("unused"))
    for wrong in ({"images": 3, "distinct_images": 1}, {"images": 4}, {}):
        with pytest.raises(AssertionError, match="profile"):
            audit_guard.check_against_declaration(
                [evidence], budget(2, profile=wrong), Path("unused")
            )
    # A declaration of images for a text-only notebook is also a mismatch.
    text_only = audit_guard.audited_evidence(execute((SETUP, CALLS, FINAL), monkeypatch))[0]
    with pytest.raises(AssertionError, match="profile"):
        audit_guard.check_against_declaration(
            [text_only], budget(3, 2, profile={"images": 1, "distinct_images": 1}), Path("unused")
        )


@pytest.mark.parametrize(
    "change",
    [
        # fewer copies than distinct images cannot happen: every asset is placed at least once
        lambda call, p: call.update(profile={"images": 1, "distinct_images": 2}) or p,
        lambda call, p: call.update(profile={"images": 4}) or p,
        lambda call, p: call.update(profile={"distinct_images": 1}) or p,
    ],
)
def test_a_hand_edited_image_profile_fails_even_when_the_totals_are_rewritten_to_match(
    monkeypatch, change
):
    cells = execute((IMAGE_SETUP, IMAGE_CALLS, FINAL), monkeypatch)

    def alter(payload):
        entry = payload["backends"][0]
        change(entry["calls"][0], payload)
        totals = {}
        for call in entry["calls"]:
            for name, amount in call.get("profile", {}).items():
                totals[name] = totals.get(name, 0) + int(amount)
        entry["profile_totals"] = totals

    alter_payload(cells, alter)
    with pytest.raises(AssertionError, match="request audit"):
        audit_guard.audited_evidence(cells)


def test_an_unedited_image_profile_passes_the_same_rewrite(monkeypatch):
    cells = execute((IMAGE_SETUP, IMAGE_CALLS, FINAL), monkeypatch)
    alter_payload(cells, lambda payload: None)
    audit_guard.audited_evidence(cells)
