"""Decision backends: hashing, replay, scripted determinism, provenance, offline use."""

import json
import os
import random
import subprocess
import sys

import pytest

from jev_cookbook import (
    Choice,
    ChoiceAnswer,
    DecisionResult,
    FixtureError,
    LiveBackendUnavailable,
    Noul,
    NoulAnswer,
    Provenance,
    ReplayBackend,
    ReplayMiss,
    Score,
    ScoreAnswer,
    ScriptedBackend,
    Usage,
    answer_from_dict,
    get_backend,
    question_from_dict,
    replay_key,
)
from jev_cookbook._canonical import canonical_json

STATE = {"document": "I was charged twice.\nPlease fix this."}


def questions():
    return {
        "billing": Noul(instructions="Is this ticket about billing?"),
        "tone": Choice(
            instructions="What is the customer's tone?",
            criteria={"calm": None, "frustrated": "annoyed", "angry": None},
        ),
        "urgency": Score(
            instructions="How urgent is this ticket?", criteria=["can wait", "this week", "today"]
        ),
    }


def script(state, qs, rng):
    return {"billing": 0.9, "tone": {"angry": 3, "calm": 1}, "urgency": [0, 1, 3]}


# ---------------------------------------------------------------- hashing


def test_key_is_pinned():
    """Golden value: changing it silently would orphan every stored fixture."""
    assert replay_key(STATE, questions()) == (
        "e86caba8277d9f979f0847ee3ac199679be725e4b7e83a7fd7a9525efce64549"
    )


def test_canonical_json_is_pinned():
    value = {"b": [1, 2.5, None, True], "a": "é\r\nx", "n": -0.0, "big": 10**20}
    assert canonical_json(value) == (
        '{"a":"\\u00e9\\nx","b":[1,2.5,null,true],"big":100000000000000000000,"n":0.0}'
    )


def test_key_is_repeatable_across_processes():
    probe = (
        "import json,sys;"
        "from jev_cookbook import *;"
        "qs={'a':Choice({'x':None,'y':'why'},'i'),'b':Score(['lo','hi'])};"
        "print(replay_key({'k':[1,2.5,'t']},qs))"
    )
    outs = {
        subprocess.run(
            [sys.executable, "-c", probe, str(i)],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": str(i)},
        ).stdout
        for i in (1, 2, 3)
    }
    assert len(outs) == 1


def test_key_ignores_dict_order_newline_style_and_choice_option_order():
    base = replay_key(STATE, questions())
    qs = questions()
    reordered = {k: qs[k] for k in reversed(list(qs))}
    reordered["tone"] = Choice(
        instructions="What is the customer's tone?",
        criteria={"angry": None, "frustrated": "annoyed", "calm": None},
    )
    crlf = {"document": "I was charged twice.\r\nPlease fix this."}
    assert replay_key(STATE, reordered) == base
    assert replay_key(crlf, qs) == base
    assert replay_key({"document": STATE["document"].replace("\n", "\r")}, qs) == base


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s, q: (dict(s, document="Different."), q),
        lambda s, q: (dict(s, extra=None), q),
        lambda s, q: (s, {**q, "billing": Noul(instructions="Is this about refunds?")}),
        lambda s, q: (s, {**q, "billing": Noul("Is this ticket about billing?", {"true": "x"})}),
        lambda s, q: (s, {**q, "billing": Choice({"yes": None, "no": None}, "x")}),
        lambda s, q: (
            s,
            {
                **q,
                "urgency": Score(["this week", "can wait", "today"], "How urgent is this ticket?"),
            },
        ),
        lambda s, q: (
            s,
            {**q, "urgency": Score(["can wait", "this week"], "How urgent is this ticket?")},
        ),
        lambda s, q: (
            s,
            {**q, "tone": Choice({"calm": None, "angry": None}, "What is the customer's tone?")},
        ),
        lambda s, q: (
            s,
            {
                **q,
                "tone": Choice(
                    {"calm": None, "frustrated": "upset", "angry": None},
                    "What is the customer's tone?",
                ),
            },
        ),
        lambda s, q: (s, {"renamed": q["billing"], "tone": q["tone"], "urgency": q["urgency"]}),
        lambda s, q: (s, {k: v for k, v in q.items() if k != "tone"}),
        lambda s, q: (dict(s, n=1), q),
    ],
)
def test_key_changes_when_the_request_changes(mutate):
    s, q = mutate(STATE, questions())
    assert replay_key(s, q) != replay_key(STATE, questions())


def test_int_and_float_state_values_are_distinct_but_noul_criteria_none_is_equal():
    q = {"b": Noul("x")}
    assert replay_key({"v": 1}, q) != replay_key({"v": 1.0}, q)
    assert replay_key("s", {"b": Noul("x", {"true": None})}) == replay_key("s", q)


@pytest.mark.parametrize("bad", [None, {1: "x"}, {"a": float("nan")}, {"a": {1, 2}}, object()])
def test_bad_state_is_rejected(bad):
    with pytest.raises((TypeError, ValueError)):
        replay_key(bad, {"b": Noul("x")})


def test_bad_questions_are_rejected():
    with pytest.raises(ValueError):
        replay_key("s", {})
    with pytest.raises(TypeError):
        replay_key("s", {"b": {"type": "noul"}})
    with pytest.raises(ValueError):
        Choice({})
    with pytest.raises(ValueError):
        Score([])
    with pytest.raises(ValueError):
        Score("abc")
    with pytest.raises(ValueError):
        Noul("x", {"maybe": "y"})


def test_question_round_trip():
    for q in questions().values():
        assert question_from_dict(json.loads(json.dumps(q.to_dict()))) == q
    with pytest.raises(ValueError):
        question_from_dict({"type": "noul", "oops": 1})


# ----------------------------------------------------------------- replay


def recorded_result():
    prov = Provenance.recorded("model-string-from-api", "2026-01-31")
    return DecisionResult(
        {
            "billing": NoulAnswer(0.98, prov),
            "tone": ChoiceAnswer(
                "angry", {"calm": 0.1, "frustrated": 0.1, "angry": 0.8}, 0.7, prov
            ),
            "urgency": ScoreAnswer(
                1.7,
                {0: 0.0, 1: 0.3, 2: 0.7},
                0.9,
                {0: "can wait", 1: "this week", 2: "today"},
                prov,
            ),
        },
        "model-string-from-api",
        Usage(120, 14),
    )


def test_mixed_request_round_trips_recorded_through_json():
    qs = questions()
    stored = json.loads(json.dumps(recorded_result().to_dict()))
    backend = ReplayBackend({replay_key(STATE, qs): stored})
    got = backend.decide(STATE, qs)
    assert got == recorded_result()
    assert got.model == "model-string-from-api"
    assert got.usage == Usage(120, 14)
    assert got.choices["tone"].choice == "angry"
    assert got["billing"].noul == 0.98
    assert got.scores["urgency"].legend[2] == "today"
    assert got.to_dict() == stored


def test_replay_miss_names_the_key_and_never_fabricates():
    qs = questions()
    backend = ReplayBackend({})
    with pytest.raises(ReplayMiss) as err:
        backend.decide(STATE, qs)
    assert err.value.key == replay_key(STATE, qs)
    assert replay_key(STATE, qs) in str(err.value)
    assert "never invents" in str(err.value)
    stored = {replay_key(STATE, qs): recorded_result().to_dict()}
    with pytest.raises(ReplayMiss):
        ReplayBackend(stored).decide({"document": "other"}, qs)


def test_replay_rejects_fixture_that_does_not_fit_the_questions():
    qs = questions()
    key = replay_key(STATE, qs)
    wrong_type = recorded_result().to_dict()
    wrong_type["answers"]["billing"] = wrong_type["answers"]["tone"]
    with pytest.raises(FixtureError, match=key):
        ReplayBackend({key: wrong_type}).decide(STATE, qs)
    missing = recorded_result().to_dict()
    del missing["answers"]["urgency"]
    with pytest.raises(FixtureError, match=key):
        ReplayBackend({key: missing}).decide(STATE, qs)
    fewer = {**qs, "urgency": Score(["a", "b"])}
    with pytest.raises(FixtureError, match="levels"):
        ReplayBackend({replay_key(STATE, fewer): recorded_result().to_dict()}).decide(STATE, fewer)


def test_malformed_stored_response_fails_when_loaded():
    good = recorded_result().to_dict()
    no_prov = json.loads(json.dumps(good))
    del no_prov["answers"]["billing"]["provenance"]
    extra = dict(good, surprise=1)
    for bad in (no_prov, extra, {"model": "m", "usage": {}, "answers": []}):
        with pytest.raises(FixtureError, match="k1"):
            ReplayBackend({"k1": bad})


def test_from_json_and_get_backend_with_path(tmp_path):
    qs = questions()
    path = tmp_path / "fx.json"
    path.write_text(json.dumps({replay_key(STATE, qs): recorded_result().to_dict()}))
    assert ReplayBackend.from_json(path).decide(STATE, qs) == recorded_result()
    assert get_backend(fixtures=str(path)).decide(STATE, qs) == recorded_result()
    path.write_text("[]")
    with pytest.raises(FixtureError):
        ReplayBackend.from_json(path)


# --------------------------------------------------------------- provenance


def test_provenance_rules():
    assert Provenance.synthetic().to_dict() == {"source": "synthetic", "model": None, "date": None}
    assert Provenance.from_dict(Provenance.recorded("m", "2026-02-03").to_dict()).date == (
        "2026-02-03"
    )
    for bad in (
        lambda: Provenance("synthetic", "m", None),
        lambda: Provenance("recorded"),
        lambda: Provenance("recorded", "m", "2026-2-3"),
        lambda: Provenance("recorded", "m", "20260203"),
        lambda: Provenance("recorded", "", "2026-02-03"),
        lambda: Provenance("guessed"),
        lambda: NoulAnswer(0.5, None),
    ):
        with pytest.raises((ValueError, TypeError)):
            bad()


def test_answer_validation():
    p = Provenance.synthetic()
    for bad in (
        lambda: NoulAnswer(1.5, p),
        lambda: NoulAnswer(True, p),
        lambda: ChoiceAnswer("z", {"a": 1.0}, 1.0, p),
        lambda: ScoreAnswer(0.0, {0: 1.0, 2: 0.0}, 1.0, {0: "a", 2: "b"}, p),
        lambda: ScoreAnswer(5.0, {0: 1.0, 1: 0.0}, 1.0, {0: "a", 1: "b"}, p),
    ):
        with pytest.raises((ValueError, TypeError)):
            bad()
    with pytest.raises(ValueError):
        answer_from_dict({"type": "noul", "noul": 0.5})


def test_every_scripted_answer_carries_synthetic_provenance():
    result = ScriptedBackend(script, seed=1).decide(STATE, questions())
    assert len(result.answers) == 3
    for answer in result.answers.values():
        assert answer.provenance == Provenance.synthetic()
        assert answer.to_dict()["provenance"]["source"] == "synthetic"


# ----------------------------------------------------------------- scripted


def test_scripted_is_deterministic_and_seeded():
    def noisy(state, qs, rng):
        return {"billing": rng.random(), "tone": "calm", "urgency": [1, 1, 1]}

    a = ScriptedBackend(noisy, seed=7).decide(STATE, questions())
    b = ScriptedBackend(noisy, seed=7).decide(STATE, questions())
    c = ScriptedBackend(noisy, seed=8).decide(STATE, questions())
    other = ScriptedBackend(noisy, seed=7).decide({"document": "x"}, questions())
    assert a == b
    assert a["billing"].noul != c["billing"].noul
    assert a["billing"].noul != other["billing"].noul
    # Mersenne Twister's random() stream is fixed across platforms and versions.
    assert random.Random(12345).random() == 0.41661987254534116
    assert ScriptedBackend(noisy, seed=7).rng_for(STATE, questions()).random() == (
        ScriptedBackend(noisy, seed=7).rng_for(STATE, questions()).random()
    )


def test_scripted_builds_typed_answers_from_specs():
    r = ScriptedBackend(script).decide(STATE, questions())
    assert r.model == "synthetic-scripted"
    assert r.usage == Usage(None, None)
    assert r["billing"].noul == 0.9
    tone = r["tone"]
    assert tone.choice == "angry"
    assert tone.probabilities == {"calm": 0.25, "frustrated": 0.0, "angry": 0.75}
    assert tone.confidence == pytest.approx(0.625)
    urgency = r["urgency"]
    assert urgency.score == pytest.approx(1.75)
    assert urgency.legend == {0: "can wait", 1: "this week", 2: "today"}
    assert 0 <= urgency.confidence <= 1
    sure = ScriptedBackend(lambda s, q, g: {"t": "calm"}).decide("s", {"t": q_choice()})
    assert sure["t"].confidence == 1.0


def q_choice():
    return Choice({"calm": None, "angry": None})


def test_scripted_rejects_bad_scripts():
    qs = questions()
    bad = [
        {"billing": 0.5},  # missing names
        {"billing": 0.5, "tone": "nope", "urgency": [1, 1, 1]},
        {"billing": 0.5, "tone": "calm", "urgency": [1, 1]},
        {"billing": 2, "tone": "calm", "urgency": [1, 1, 1]},
        {"billing": 0.5, "tone": "calm", "urgency": [0, 0, 0]},
        {
            "billing": ChoiceAnswer("a", {"a": 1.0}, 1.0, Provenance.synthetic()),
            "tone": "calm",
            "urgency": [1, 1, 1],
        },
    ]
    for spec in bad:
        with pytest.raises(ValueError):
            ScriptedBackend(lambda s, q, g, spec=spec: spec).decide(STATE, qs)
    recorded = NoulAnswer(0.5, Provenance.recorded("m", "2026-01-01"))
    with pytest.raises(ValueError, match="synthetic"):
        ScriptedBackend(lambda s, q, g: {"b": recorded}).decide("s", {"b": Noul()})
    with pytest.raises(TypeError):
        ScriptedBackend(script, seed="1")


# --------------------------------------------------------------- get_backend


def test_get_backend_offline_modes(monkeypatch):
    monkeypatch.delenv("JEV_COOKBOOK_LIVE", raising=False)
    assert isinstance(get_backend(script=script), ScriptedBackend)
    assert isinstance(get_backend(fixtures={}), ReplayBackend)
    with pytest.raises(ValueError):
        get_backend()
    with pytest.raises(ValueError):
        get_backend(fixtures={}, script=script)
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "0")
    assert isinstance(get_backend(fixtures={}), ReplayBackend)


def test_live_flag_never_falls_back_to_replay(monkeypatch):
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
    with pytest.raises(LiveBackendUnavailable, match="JEV_COOKBOOK_LIVE"):
        get_backend(fixtures={})
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "true")
    with pytest.raises(ValueError, match="must be 1"):
        get_backend(fixtures={})


def test_offline_backends_work_without_the_sdk():
    probe = r"""
import importlib.abc, sys

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"typesafe", "typesafe_sdk"}:
            raise ImportError("blocked: " + name)

sys.meta_path.insert(0, Block())
from jev_cookbook import Noul, ReplayBackend, get_backend, replay_key
q = {"b": Noul("x")}
r = get_backend(script=lambda s, qs, g: {"b": 0.25}).decide("s", q)
fx = {replay_key("s", q): r.to_dict()}
assert ReplayBackend(fx).decide("s", q) == r
assert "typesafe_sdk" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", probe], check=True)


def test_score_levels_are_int_keys_in_memory_and_strings_in_json():
    stored = {
        "type": "score",
        "score": 0.4,
        "probabilities": {"0": 0.6, "1": 0.4},
        "confidence": 0.2,
        "legend": {"0": "low", "1": "high"},
        "provenance": {"source": "synthetic", "model": None, "date": None},
    }
    answer = answer_from_dict(stored)
    assert answer.probabilities == {0: 0.6, 1: 0.4}
    assert answer.legend == {0: "low", 1: "high"}
    assert answer.to_dict() == stored
    assert json.loads(json.dumps(answer.to_dict())) == stored


def test_stored_response_example_in_the_docs_parses():
    import pathlib
    import re

    text = (pathlib.Path(__file__).parent.parent / "docs" / "backends.md").read_text("utf-8")
    block = re.search(r"```json\n(.*?)\n```", text, re.S).group(1)
    result = DecisionResult.from_dict(json.loads(block))
    assert result.to_dict() == json.loads(block)
    assert set(result.answers) == {"billing", "tone", "urgency"}
