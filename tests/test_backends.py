"""Decision backends: hashing, replay, scripted determinism, provenance, offline use."""

import json
import os
import random
import subprocess
import sys

import pytest

from jev_cookbook import (
    Backend,
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
from jev_cookbook.answers import SYNTHETIC_MODEL, choice_confidence, score_confidence

STATE = {"document": "I was charged twice.\nPlease fix this."}
K1 = "0" * 64
K2 = "1" * 64


def ok_fixtures():
    return {K1: ScriptedBackend(script).decide(STATE, questions()).to_dict()}


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
    assert (
        replay_key(STATE, questions())
        == "86cf6500653d1e9aad424e9c7f741a92ae8eef321d10f99c12f2e3d6fbb84955"
    )


def test_key_is_pinned_for_non_ascii_text():
    """Fails if ``ensure_ascii`` changes: the hashed text is pure ASCII escapes."""
    state = {"d": "caf\u00e9 \u2603 \U0001f600"}
    assert canonical_json(state) == '{"d":"caf\\u00e9 \\u2603 \\ud83d\\ude00"}'
    assert (
        replay_key(state, {"b": Noul(instructions="\u00e9")})
        == "3be9e21c8b9dcc0deb4d4fae98524094a5d9be7e4fd2f1e7ad1df64f80d85b81"
    )


def test_canonical_json_is_pinned():
    value = {"b": [1, 2.5, None, True], "a": "\u00e9\r\nx", "n": -0.0, "big": 10**20}
    assert canonical_json(value) == (
        '{"b":[1,2.5,null,true],"a":"\\u00e9\\r\\nx","n":-0.0,"big":100000000000000000000}'
    )


def test_key_is_repeatable_across_processes():
    probe = (
        "import json,sys;"
        "from jev_cookbook import *;"
        "qs={'a':Choice(criteria={'x':None,'y':'why'},instructions='i'),'b':Score(criteria=['lo','hi'])};"
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


def test_key_order_rules():
    base = replay_key(STATE, questions())
    qs = questions()
    # Question names are sorted: their order never matters.
    assert replay_key(STATE, {k: qs[k] for k in reversed(list(qs))}) == base
    # State keys and Choice options are hashed in the order written.
    two = {"a": "1", "b": "2"}
    assert replay_key(two, qs) != replay_key({"b": "2", "a": "1"}, qs)
    reordered = dict(qs)
    reordered["tone"] = Choice(
        instructions="What is the customer's tone?",
        criteria={"angry": None, "frustrated": "annoyed", "calm": None},
    )
    assert replay_key(STATE, reordered) != base
    # Nothing else is normalized: newline style and negative zero change the key.
    assert replay_key({"document": STATE["document"].replace("\n", "\r\n")}, qs) != base
    n = {"b": Noul(instructions="x")}
    assert replay_key({"v": [0.0]}, n) != replay_key({"v": [-0.0]}, n)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s, q: (dict(s, document="Different."), q),
        lambda s, q: (dict(s, extra=None), q),
        lambda s, q: (s, {**q, "billing": Noul(instructions="Is this about refunds?")}),
        lambda s, q: (
            s,
            {
                **q,
                "billing": Noul(
                    instructions="Is this ticket about billing?", criteria={"true": "x"}
                ),
            },
        ),
        lambda s, q: (
            s,
            {**q, "billing": Choice(criteria={"yes": None, "no": None}, instructions="x")},
        ),
        lambda s, q: (
            s,
            {
                **q,
                "urgency": Score(
                    criteria=["this week", "can wait", "today"],
                    instructions="How urgent is this ticket?",
                ),
            },
        ),
        lambda s, q: (
            s,
            {
                **q,
                "urgency": Score(
                    criteria=["can wait", "this week"], instructions="How urgent is this ticket?"
                ),
            },
        ),
        lambda s, q: (
            s,
            {
                **q,
                "tone": Choice(
                    criteria={"calm": None, "angry": None},
                    instructions="What is the customer's tone?",
                ),
            },
        ),
        lambda s, q: (
            s,
            {
                **q,
                "tone": Choice(
                    criteria={"calm": None, "frustrated": "upset", "angry": None},
                    instructions="What is the customer's tone?",
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
    q = {"b": Noul(instructions="x")}
    assert replay_key({"v": 1}, q) != replay_key({"v": 1.0}, q)
    assert replay_key("s", {"b": Noul(instructions="x", criteria={"true": None})}) == replay_key(
        "s", q
    )


@pytest.mark.parametrize(
    "bad",
    [None, 1, 1.5, True, [1], ["a", 2], {1: "x"}, {"a": float("nan")}, {"a": {1, 2}}, object()],
)
def test_bad_state_is_rejected(bad):
    with pytest.raises((TypeError, ValueError)):
        replay_key(bad, {"b": Noul(instructions="x")})


def test_bad_questions_are_rejected():
    with pytest.raises(ValueError):
        replay_key("s", {})
    with pytest.raises(TypeError):
        replay_key("s", {"b": {"type": "noul"}})
    with pytest.raises(ValueError):
        Choice(criteria={})
    with pytest.raises(ValueError):
        Score(criteria=[])
    with pytest.raises(ValueError):
        Score(criteria="abc")
    with pytest.raises(ValueError):
        Noul(instructions="x", criteria={"maybe": "y"})


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
            "tone": ChoiceAnswer.from_probabilities(
                {"calm": 0.1, "frustrated": 0.1, "angry": 0.8}, prov
            ),
            "urgency": ScoreAnswer.from_probabilities(
                [0.0, 0.3, 0.7], ["can wait", "this week", "today"], prov
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
    backend = ReplayBackend({K1: recorded_result().to_dict()})
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
    fewer = {**qs, "urgency": Score(criteria=["a", "b"])}
    with pytest.raises(FixtureError, match="levels"):
        ReplayBackend({replay_key(STATE, fewer): recorded_result().to_dict()}).decide(STATE, fewer)


def test_malformed_stored_response_fails_when_loaded():
    good = recorded_result().to_dict()
    no_prov = json.loads(json.dumps(good))
    del no_prov["answers"]["billing"]["provenance"]
    extra = dict(good, surprise=1)
    for bad in (no_prov, extra, {"model": "m", "usage": {}, "answers": []}):
        with pytest.raises(FixtureError, match=K1):
            ReplayBackend({K1: bad})


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
    assert r.model == "synthetic"
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
    return Choice(criteria={"calm": None, "angry": None})


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
        ScriptedBackend(lambda s, q, g: {"b": recorded}).decide("s", {"b": Noul(instructions="b")})
    with pytest.raises(TypeError):
        ScriptedBackend(script, seed="1")


# --------------------------------------------------------------- get_backend


def test_get_backend_offline_modes(monkeypatch):
    monkeypatch.delenv("JEV_COOKBOOK_LIVE", raising=False)
    assert isinstance(get_backend(script=script), ScriptedBackend)
    assert isinstance(get_backend(fixtures=ok_fixtures()), ReplayBackend)
    with pytest.raises(ValueError):
        get_backend()
    with pytest.raises(ValueError):
        get_backend(fixtures=ok_fixtures(), script=script)
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "0")
    assert isinstance(get_backend(fixtures=ok_fixtures()), ReplayBackend)


def test_live_flag_never_falls_back_to_replay(monkeypatch):
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
    with pytest.raises(LiveBackendUnavailable, match="JEV_COOKBOOK_LIVE"):
        get_backend(fixtures=ok_fixtures())
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "true")
    with pytest.raises(ValueError, match="must be 1"):
        get_backend(fixtures=ok_fixtures())


def test_offline_backends_work_without_the_sdk():
    probe = r"""
import importlib.abc, sys

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"typesafe", "typesafe_sdk"}:
            raise ImportError("blocked: " + name)

sys.meta_path.insert(0, Block())
from jev_cookbook import Noul, ReplayBackend, get_backend, replay_key
q = {"b": Noul(instructions="x")}
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


# --------------------------------------------------- fix round 1 additions

PROV = Provenance.synthetic()
REC = Provenance.recorded("model-string-from-api", "2026-01-31")


def test_scripted_exact_values_are_pinned():
    """Same bytes on Python 3.10 and 3.14: sums use math.fsum, never builtin sum."""
    qs = {
        "c": Choice(criteria={"a": None, "b": None, "c": None}),
        "s": Score(criteria=["l0", "l1", "l2", "l3"]),
    }
    spec = {"c": {"a": 0.1, "b": 0.2, "c": 0.7}, "s": [0.1, 0.2, 0.3, 0.7]}
    r = ScriptedBackend(lambda st, q, g: spec).decide("x", qs)
    assert r["c"].probabilities == {"a": 0.1, "b": 0.2, "c": 0.7}
    assert r["c"].confidence == CHOICE_CONF
    assert dict(r["s"].probabilities) == SCORE_PROBS
    assert r["s"].score == SCORE_VALUE
    assert r["s"].confidence == SCORE_CONF


def test_scripted_answers_do_not_depend_on_call_order():
    def noisy(state, qs, rng):
        return {"billing": rng.random(), "tone": "calm", "urgency": [1, rng.random(), 1]}

    other = {"document": "another"}
    first = ScriptedBackend(noisy, seed=3)
    a1, b1 = first.decide(STATE, questions()), first.decide(other, questions())
    second = ScriptedBackend(noisy, seed=3)
    b2, a2 = second.decide(other, questions()), second.decide(STATE, questions())
    assert (a1, b1) == (a2, b2)
    assert first.decide(STATE, questions()) == a1


def test_replay_results_are_immutable_and_independent():
    qs = questions()
    backend = ReplayBackend({replay_key(STATE, qs): recorded_result().to_dict()})
    first = backend.decide(STATE, qs)
    with pytest.raises(TypeError):
        first.answers["extra"] = first["billing"]
    with pytest.raises(TypeError):
        first["tone"].probabilities["calm"] = 0.9
    with pytest.raises(TypeError):
        first["urgency"].legend[0] = "x"
    with pytest.raises(AttributeError):
        first["billing"].noul = 0.0
    exported = first.to_dict()
    exported["answers"]["billing"]["noul"] = 0.0
    exported["answers"]["tone"]["probabilities"]["calm"] = 0.9
    assert backend.decide(STATE, qs) == recorded_result()
    assert backend.decide(STATE, qs).to_dict() == recorded_result().to_dict()


def test_choice_validation():
    for bad in (
        lambda: ChoiceAnswer("calm", {"calm": 0.1, "angry": 0.9}, 0.8, PROV),  # not the top option
        lambda: ChoiceAnswer("angry", {"calm": 0.2, "angry": 0.9}, 0.8, PROV),  # sum above 1
        lambda: ChoiceAnswer("angry", {"calm": 0.1, "angry": 0.9}, 0.5, PROV),  # wrong confidence
        lambda: ChoiceAnswer("angry", {"calm": 0.1, "angry": 0.9}, 0.8, None),
    ):
        with pytest.raises((ValueError, TypeError)):
            bad()
    ok = ChoiceAnswer("angry", {"calm": 0.1, "angry": 0.9}, 0.8, PROV)
    assert ok.confidence == pytest.approx(0.8)
    assert ChoiceAnswer("a", {"a": 1.0}, 1.0, PROV).confidence == 1.0


def test_score_validation():
    levels = {0: "lo", 1: "mid", 2: "hi"}
    probs = {0: 0.2, 1: 0.3, 2: 0.5}
    good = ScoreAnswer.from_probabilities([0.2, 0.3, 0.5], ["lo", "mid", "hi"], PROV)
    assert good.score == pytest.approx(1.3)
    assert good.to_dict()["probabilities"] == {"0": 0.2, "1": 0.3, "2": 0.5}
    conf = good.confidence
    for bad in (
        lambda: ScoreAnswer(1.9, probs, conf, levels, PROV),  # score is not the weighted level
        lambda: ScoreAnswer(1.3, probs, conf + 0.3, levels, PROV),  # wrong confidence
        lambda: ScoreAnswer(1.3, {0: 0.2, 1: 0.3, 2: 0.6}, conf, levels, PROV),  # sums above 1
        lambda: ScoreAnswer(1.3, {"00": 0.2, "1": 0.3, "2": 0.5}, conf, levels, PROV),
        lambda: ScoreAnswer(1.3, {0: 0.2, "0": 0.3, 2: 0.5}, conf, levels, PROV),  # duplicate
        lambda: ScoreAnswer(1.3, probs, conf, {0: "lo", 1: 7, 2: "hi"}, PROV),
        lambda: ScoreAnswer(1.3, probs, conf, levels, None),
    ):
        with pytest.raises((ValueError, TypeError)):
            bad()


def test_formulas_match_the_published_ones():
    c = ChoiceAnswer.from_probabilities({"a": 0.5, "b": 0.3, "c": 0.2}, PROV)
    assert c.choice == "a"
    assert c.confidence == pytest.approx((0.5 - 1 / 3) / (1 - 1 / 3))
    s = ScoreAnswer.from_probabilities([0.0, 0.05, 0.9, 0.05, 0.0], list("abcde"), PROV)
    even = (2 + 1 + 0 + 1 + 2) / 5
    assert s.confidence == pytest.approx(1 - (0.05 + 0.05) / even)
    assert s.score == pytest.approx(2.0)


def test_decision_result_validation():
    rec = NoulAnswer(0.5, REC)
    syn = NoulAnswer(0.5, PROV)
    with pytest.raises(TypeError):
        DecisionResult({"a": {"type": "noul"}}, "model-string-from-api")
    with pytest.raises(ValueError, match="mix"):
        DecisionResult({"a": rec, "b": syn}, "model-string-from-api")
    with pytest.raises(ValueError, match="synthetic"):
        DecisionResult({"a": syn}, "gpt-looking-name")
    with pytest.raises(ValueError, match="different model"):
        DecisionResult({"a": rec}, "some-other-model")
    with pytest.raises(ValueError):
        DecisionResult({}, SYNTHETIC_MODEL)
    with pytest.raises(ValueError, match="synthetic"):
        Provenance.recorded(SYNTHETIC_MODEL, "2026-01-01")
    assert DecisionResult({"a": syn}, SYNTHETIC_MODEL).source == "synthetic"


def test_provenance_is_required_and_recorded_needs_a_date():
    base = recorded_result().to_dict()
    for name in ("billing", "tone", "urgency"):
        stored = json.loads(json.dumps(base))
        del stored["answers"][name]["provenance"]
        with pytest.raises(ValueError, match="provenance"):
            DecisionResult.from_dict(stored)
    for name in ("billing", "tone", "urgency"):
        stored = json.loads(json.dumps(base))
        stored["answers"][name]["provenance"]["date"] = None
        with pytest.raises(ValueError, match="date"):
            DecisionResult.from_dict(stored)
    with pytest.raises(ValueError, match="date"):
        Provenance("recorded", "m", None)


def test_question_strictness():
    for bad in (7, 1.5, True, [1], ["a", 2]):
        with pytest.raises(TypeError):
            replay_key(bad, {"b": Noul(instructions="x")})
    replay_key(["a", "b"], {"b": Noul(instructions="x")})
    replay_key("text", {"b": Noul(instructions="x")})
    with pytest.raises(TypeError):
        Noul("x")
    with pytest.raises(TypeError):
        Choice({"a": None})
    with pytest.raises(TypeError):
        Score(["a", "b"])
    with pytest.raises(ValueError):
        Score(criteria=["only one"])
    Score(criteria=[str(i) for i in range(10)])
    with pytest.raises(ValueError):
        Score(criteria=[str(i) for i in range(11)])
    for levels in (["a", ""], ["a", 1], ["a", None]):
        with pytest.raises(ValueError):
            Score(criteria=levels)
    Choice(criteria={str(i): None for i in range(255)})
    with pytest.raises(ValueError):
        Choice(criteria={str(i): None for i in range(256)})


def test_fixture_keys_must_be_lowercase_hex_and_unique(tmp_path):
    good = ok_fixtures()[K1]
    for bad_key in ("k1", "A" * 64, "0" * 63, "0" * 65, ""):
        with pytest.raises(FixtureError, match="64 lowercase hex"):
            ReplayBackend({bad_key: good})
    path = tmp_path / "dup.json"
    body = json.dumps(good)
    path.write_text("{" + json.dumps(K1) + ":" + body + "," + json.dumps(K1) + ":" + body + "}")
    with pytest.raises(FixtureError, match="duplicate"):
        ReplayBackend.from_json(path)
    with pytest.raises(FixtureError):
        ReplayBackend({})


def test_backend_mode_model_and_recorded_dates():
    rec = recorded_result()
    r1 = ReplayBackend({K1: rec.to_dict()})
    assert (r1.mode, r1.model, r1.recorded_dates) == (
        "recorded",
        "model-string-from-api",
        ("2026-01-31",),
    )
    later = DecisionResult(
        {"billing": NoulAnswer(0.5, Provenance.recorded("model-string-from-api", "2025-12-01"))},
        "model-string-from-api",
    )
    r2 = ReplayBackend({K1: rec.to_dict(), K2: later.to_dict()})
    assert r2.recorded_dates == ("2025-12-01", "2026-01-31")
    syn = ReplayBackend(ok_fixtures())
    assert (syn.mode, syn.model, syn.recorded_dates) == ("synthetic", SYNTHETIC_MODEL, ())
    scripted = get_backend(script=script)
    assert (scripted.mode, scripted.model) == ("scripted", SYNTHETIC_MODEL)
    for b in (r1, syn, scripted):
        assert isinstance(b, Backend)
    with pytest.raises(FixtureError, match="mix"):
        ReplayBackend({K1: rec.to_dict(), K2: ok_fixtures()[K1]})
    other_model = DecisionResult(
        {"billing": NoulAnswer(0.5, Provenance.recorded("another-model", "2026-01-01"))},
        "another-model",
    )
    with pytest.raises(FixtureError, match="more than one model"):
        ReplayBackend({K1: rec.to_dict(), K2: other_model.to_dict()})


CHOICE_CONF = 0.5499999999999999
SCORE_PROBS = {
    0: 0.07692307692307693,
    1: 0.15384615384615385,
    2: 0.23076923076923075,
    3: 0.5384615384615384,
}
SCORE_VALUE = 2.230769230769231
SCORE_CONF = 0.23076923076923073


def test_fixture_recipe_in_the_docs_runs(tmp_path, monkeypatch):
    import pathlib
    import re

    text = (pathlib.Path(__file__).parent.parent / "docs" / "backends.md").read_text("utf-8")
    block = re.search(r"```python\n# recipe: fixture\n(.*?)\n```", text, re.S).group(1)
    monkeypatch.chdir(tmp_path)
    exec(compile(block, "docs/backends.md", "exec"), {})
    assert (tmp_path / "fixtures.json").exists()


def test_score_levels_may_be_text_objects_or_arrays():
    levels = ["plain", {"label": "rich", "when": ["a", "b"]}, ["x", "y"]]
    q = {"s": Score(criteria=levels, instructions="r")}
    assert question_from_dict(json.loads(json.dumps(q["s"].to_dict()))) == q["s"]
    assert replay_key("t", q) == SCORE_OBJECT_KEY
    ans = ScoreAnswer.from_probabilities([0.2, 0.3, 0.5], levels, PROV)
    stored = json.loads(json.dumps(ans.to_dict()))
    assert stored["legend"]["1"] == {"label": "rich", "when": ["a", "b"]}
    assert answer_from_dict(stored) == ans
    for bad in (None, 3, True, 1.5, "", []):
        with pytest.raises((ValueError, TypeError)):
            Score(criteria=["ok", bad])
    with pytest.raises(ValueError):
        ScoreAnswer.from_probabilities([0.5, 0.5], ["a", None], PROV)


def test_question_values_are_text_object_array_or_none():
    Choice(criteria={"a": None, "b": {"k": 1}, "c": ["x"]}, instructions={"k": "v"})
    Noul(instructions=["a"], criteria={"true": {"k": "v"}, "false": None})
    for bad in (7, 1.5, True):
        for build in (
            lambda b: Noul(instructions=b),
            lambda b: Choice(criteria={"a": b}),
            lambda b: Choice(criteria={"a": None}, instructions=b),
            lambda b: Score(criteria=["a", "b"], instructions=b),
            lambda b: Noul(instructions="x", criteria={"true": b}),
        ):
            with pytest.raises(TypeError):
                build(bad)


def test_one_result_cannot_carry_two_dates():
    a = NoulAnswer(0.5, Provenance.recorded("m", "2026-01-01"))
    b = NoulAnswer(0.5, Provenance.recorded("m", "2026-01-02"))
    with pytest.raises(ValueError, match="one date"):
        DecisionResult({"a": a, "b": b}, "m")


SCORE_OBJECT_KEY = "01ce836f962ac8e4493652eed2909d95cb84570e0f03ad068be47cf8ec037a69"


# --------------------------------------------------- fix round 3 additions


def test_replay_never_hands_out_mutable_legend_values():
    levels = [{"covers": "low", "examples": ["a"]}, ["high", {"k": "v"}]]
    qs = {"s": Score(criteria=levels)}
    answer = ScoreAnswer.from_probabilities([0.4, 0.6], levels, REC)
    stored = DecisionResult({"s": answer}, REC.model).to_dict()
    backend = ReplayBackend({replay_key("t", qs): stored})
    first = backend.decide("t", qs)
    first["s"].legend[0]["covers"] = "TAMPERED"
    first["s"].legend[0]["examples"].append("x")
    first["s"].legend[1][1]["k"] = "TAMPERED"
    first.to_dict()["answers"]["s"]["legend"]["1"][0] = "TAMPERED"
    stored["answers"]["s"]["legend"]["0"]["covers"] = "TAMPERED"  # the caller's own dict
    again = backend.decide("t", qs)
    assert again["s"].legend[0] == {"covers": "low", "examples": ["a"]}
    assert again["s"].legend[1] == ["high", {"k": "v"}]
    assert again is not first
    assert again == DecisionResult({"s": answer}, REC.model)


def test_float_sums_use_fsum_so_python_3_10_matches_3_12_and_later():
    """Built-in ``sum`` is compensated only from Python 3.12, so each case below differs
    between 3.10 and 3.14 if a weight total, expected level or spread stops using ``math.fsum``.
    (The ``even`` term sums multiples of 0.5, which every summation order adds exactly, so no
    input can tell its ``fsum`` from ``sum``.)"""
    levels = [f"level {i}" for i in range(10)]
    tenths = ScriptedBackend(lambda st, q, g: {"s": [0.1] * 10})
    got = tenths.decide("x", {"s": Score(criteria=levels)})["s"]
    assert (
        list(got.probabilities.values()) == [0.1] * 10
    )  # weight total (sum gives 0.9999999999999999)
    assert got.score == 4.5  # expected level (sum gives 4.500000000000001)
    assert got.confidence == 0.0
    spread = ScoreAnswer.from_probabilities([0.23, 0.28, 0.31, 0.18], list("abcd"), PROV)
    assert spread.confidence == 0.07999999999999996  # spread (sum gives 0.08000000000000007)


def test_score_probabilities_must_sum_to_one():
    """Score and confidence below agree with the unnormalized probabilities, so only the
    sum rule can reject them."""
    probs = [0.1, 0.1]
    with pytest.raises(ValueError, match=r"sum to 1, they sum to 0\.2"):
        ScoreAnswer(0.1, {0: 0.1, 1: 0.1}, score_confidence(probs), {0: "a", 1: "b"}, PROV)
    with pytest.raises(ValueError, match=r"sum to 1, they sum to 0\.98"):
        ChoiceAnswer("a", {"a": 0.9, "b": 0.08}, choice_confidence([0.9, 0.08]), PROV)


def test_replay_rejects_a_stored_choice_with_other_options():
    qs = {"t": Choice(criteria={"calm": None, "angry": None})}
    other = ChoiceAnswer.from_probabilities({"happy": 0.2, "angry": 0.8}, REC)
    stored = DecisionResult({"t": other}, REC.model).to_dict()
    backend = ReplayBackend({replay_key("s", qs): stored})
    with pytest.raises(FixtureError, match="options"):
        backend.decide("s", qs)
    same = ChoiceAnswer.from_probabilities({"angry": 0.8, "calm": 0.2}, REC)  # order is free
    stored = DecisionResult({"t": same}, REC.model).to_dict()
    assert ReplayBackend({replay_key("s", qs): stored}).decide("s", qs)["t"] == same


def test_score_levels_reject_empty_objects_text_and_arrays():
    for empty in ("", [], {}):
        with pytest.raises(ValueError, match="Score level 1"):
            Score(criteria=["ok", empty])
    Score(criteria=[{"k": "v"}, ["x"]])


def _accepts(build):
    build()


def _rejects(build, match):
    with pytest.raises(ValueError, match=match):
        build()


def test_tolerances_are_pinned():
    """Each tolerance accepts an error just inside it and rejects one just outside."""
    levels = {0: "a", 1: "b"}

    def choice(eps):
        return lambda: ChoiceAnswer(
            "a", {"a": 0.5 + eps, "b": 0.5}, choice_confidence([0.5 + eps, 0.5]), PROV
        )

    def score(eps):
        probs = {0: 0.5, 1: 0.5 + eps}
        return lambda: ScoreAnswer(
            0.5 + eps, probs, score_confidence([0.5, 0.5 + eps]), levels, PROV
        )

    # probabilities sum to 1 within 2e-2
    for make in (choice, score):
        _accepts(make(1.9e-2))
        _rejects(make(2.1e-2), "sum to 1")

    # score equals the probability-weighted level within 5e-2
    probs = {0: 0.4, 1: 0.6}
    conf = score_confidence([0.4, 0.6])
    _accepts(lambda: ScoreAnswer(0.6 + 4.9e-2, probs, conf, levels, PROV))
    _rejects(lambda: ScoreAnswer(0.6 + 5.1e-2, probs, conf, levels, PROV), "probability-weighted")

    # confidence equals the published formula within 1e-2
    cconf = choice_confidence([0.3, 0.7])
    for delta in (9.9e-3, -9.9e-3):
        _accepts(lambda delta=delta: ChoiceAnswer("b", {"a": 0.3, "b": 0.7}, cconf + delta, PROV))
        _accepts(lambda delta=delta: ScoreAnswer(0.6, probs, conf + delta, levels, PROV))
    for delta in (1.01e-2, -1.01e-2):
        _rejects(
            lambda delta=delta: ChoiceAnswer("b", {"a": 0.3, "b": 0.7}, cconf + delta, PROV),
            "confidence",
        )
        _rejects(
            lambda delta=delta: ScoreAnswer(0.6, probs, conf + delta, levels, PROV), "confidence"
        )


def test_example_responses_from_the_typesafe_docs_are_accepted():
    """Values as printed (rounded to two decimals) on the Choice and Score pages."""
    rec = Provenance.recorded("jev-1.13.0", "2026-01-01")
    docs_choices = [  # (choice, probabilities, confidence)
        ("returns", {"shipping": 0.04, "billing": 0.35, "returns": 0.61}, 0.42),
        ("delayed", {"wrong_address": 0.0, "other": 0.26, "not_delivered": 0.0,
                     "damaged_in_transit": 0.0, "delayed": 0.74}, 0.67),
        ("returns", {"shipping": 0.0, "returns": 1.0, "billing": 0.0}, 1.0),
    ]  # fmt: skip
    for choice, probs, conf in docs_choices:
        assert ChoiceAnswer(choice, probs, conf, rec).choice == choice
    docs_scores = [  # (score, probabilities, confidence)
        (1.43, [0.0, 0.57, 0.43], 0.35),
        (1.86, [0.0, 0.14, 0.86, 0.0, 0.0], 0.89),
        (2.52, [0.0, 0.0, 0.48, 0.52], 0.52),
        (1.26, [0.0, 0.74, 0.26], 0.61),
        (3.0, [0.0, 0.0, 0.0, 1.0], 1.0),
    ]
    for score, probs, conf in docs_scores:
        legend = [f"level {i}" for i in range(len(probs))]
        answer = ScoreAnswer(score, dict(enumerate(probs)), conf, dict(enumerate(legend)), rec)
        assert answer.score == score
