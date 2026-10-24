"""Matched comparison, safety boundaries, image identity, and non-gold baseline checks."""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageFont

from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(choice, probability=0.90):
    return ChoiceAnswer.from_probabilities(
        {o: probability if o == choice else (1 - probability) / 2 for o in helpers.OPTIONS},
        Provenance.synthetic(),
    )


def test_state_has_only_pixels_and_instruction_and_identical_keys_for_both_arms():
    backends = helpers.make_backends(RECIPE)
    for e in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(e.fields, RECIPE)
        assert set(state) == {"sign", "instruction"}
        assert list(questions["verify"].criteria) == ["match", "contradiction", "insufficient"]
        assert e.replay_keys == (replay_key(state, questions, assets=assets),)
        for backend in backends.values():
            assert backend.decide(state, questions, assets=assets).source == "synthetic"
    files = [
        json.loads((RECIPE / "fixtures" / name).read_text()) for name in helpers.FILES.values()
    ]
    assert set(files[0]) == set(files[1])
    assert files[0] != files[1]


@pytest.mark.parametrize("choice", ["match", "contradiction", "insufficient", "execute"])
@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -0.1, 1.1, True, "high"])
def test_missing_invalid_confidence_and_unknown_answers_never_act(choice, confidence):
    result = helpers.route(SimpleNamespace(choice=choice, confidence=confidence), 0.5)
    assert result.outcome == "review"


def test_insufficient_always_reviews_and_threshold_is_inclusive():
    assert helpers.route(answer("insufficient", 1), 0).outcome == "review"
    clear = answer("match")
    assert helpers.route(clear, clear.confidence).outcome == "accepted"
    assert helpers.route(clear, clear.confidence + 1e-8).outcome == "review"
    assert helpers.route(answer("contradiction"), 1).reason == "confidence below the threshold"


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf"), None])
def test_invalid_threshold_stops(threshold):
    with pytest.raises(ValueError):
        helpers.route(answer("match"), threshold)


def test_stored_answers_are_not_all_right():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    for backend in helpers.make_backends(RECIPE).values():

        def decide(e, backend=backend):
            state, questions, assets = helpers.build_request(e.fields, RECIPE)
            return backend.decide(state, questions, assets=assets)["verify"]

        validation = [e for e in examples if e.split == "validation"]
        named = [
            (decide(e), labels[e.id]) for e in validation if decide(e).choice != "insufficient"
        ]
        threshold = select_confidence_threshold(
            [a.choice == gold for a, gold in named],
            [a.confidence for a, _ in named],
            target_accuracy=1.0,
        )
        assert threshold == helpers.choose_policy(
            [decide(e) for e in validation], [labels[e.id] for e in validation]
        )
        test = [e for e in examples if e.split == "test"]
        wrong_and_confident = [
            e.id
            for e in test
            if decide(e).choice != labels[e.id]
            and decide(e).confidence >= threshold
            and helpers.route(decide(e), threshold).outcome == "accepted"
        ]
        assert "t03" in wrong_and_confident


def test_threshold_objective_is_pinned_to_production_source():
    source = inspect.getsource(helpers.choose_policy)
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    source = "".join(next(c for c in notebook["cells"] if c["id"] == "python-rule")["source"])
    assert "helpers.choose_policy" in source
    assert "MappingProxyType" in source
    assert 'select_split(examples, "test")' not in source


def test_image_bytes_and_instruction_change_replay_identity(tmp_path):
    e = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(e.fields, RECIPE)
    key = replay_key(state, questions, assets=assets)
    assert replay_key({**state, "instruction": "Exit right."}, questions, assets=assets) != key
    with Image.open(RECIPE / e.fields["image"]) as image:
        image.putpixel((1, 1), (0, 0, 0))
        image.save(tmp_path / "changed.png")
    changed = image_asset(tmp_path / "changed.png")
    # Even a caller-reused opaque reference binds the new bytes into the key.
    assert replay_key(state, questions, assets={state["sign"]: changed}) != key
    assert image_reference(changed) != state["sign"]


def test_no_duplicate_images_or_identical_semantic_pairs_cross_split():
    seen = {}
    for e in load_inputs(RECIPE):
        asset = image_asset(RECIPE / e.fields["image"])
        digest = image_reference(asset)
        assert digest not in seen
        seen[digest] = e.split
    import importlib.util

    spec = importlib.util.spec_from_file_location("recipe96_rows", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pairs = {}
    for row in module.ROWS:
        if row[1] == "demo":
            continue
        identity = (row[2], row[3], row[10])
        assert identity not in pairs
        pairs[identity] = row[1]


def test_accented_glyphs_are_distinct_and_baseline_uses_only_observed_pixels():
    font = ImageFont.truetype(helpers.FONT, 28)
    assert bytes(font.getmask("À")) != bytes(font.getmask("A"))
    assert bytes(font.getmask("Á")) != bytes(font.getmask("A"))
    assert bytes(font.getmask("É")) != bytes(font.getmask("E"))
    image = helpers.render_sign("N'ENTREZ PAS", 0)
    assert helpers.baseline(image, "Entrada permitida.") == "contradiction"
    assert helpers.baseline(image, "Do not enter.") == "match"
    other = helpers.render_sign("ENTRÉE AUTORISÉE", 0)
    assert helpers.baseline(other, "Entrada permitida.") == "match"
    covered = helpers.render_sign("N'ENTREZ PAS", 0, covered=True)
    assert helpers.baseline(covered, "Entrada permitida.") == "insufficient"
    assert (
        helpers.baseline(helpers.render_sign("EXIT LEFT", 0, size=33), "Sortie à gauche.")
        == "insufficient"
    )
    source = inspect.getsource(helpers.baseline)
    assert all(name not in source for name in ("load_labels", "ROWS", "split", "example.id"))


def test_simulated_findings_do_not_execute_and_reviews_are_excluded():
    examples = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    answers = [answer("match"), answer("insufficient", 1)]
    decisions, log, queue = helpers.simulate(examples, answers, 0.5)
    assert len(log) == 1 and len(queue) == 1
    assert not log.to_dicts()[0]["executed"]
    numbers = helpers.metrics([a.choice for a in answers], decisions, ["match", "insufficient"])
    assert numbers["coverage"] == 0.5 and numbers["review"] == 1


class CountingBackend:
    mode = "synthetic"

    def __init__(self):
        self.calls = 0

    def decide(self, state, questions, *, assets):
        self.calls += 1
        return DecisionResult({"verify": answer("match")}, "synthetic")


def test_actual_26_calls_per_arm_52_total_and_unknown_accounting():
    examples = load_inputs(RECIPE)
    spies = [CountingBackend(), CountingBackend()]
    sessions = [
        helpers.ArmSession(spy, model) for spy, model in zip(spies, helpers.MODELS, strict=True)
    ]
    for session in sessions:
        for e in examples:
            session.decide(helpers.build_request(e.fields, RECIPE))
        session.decide(helpers.build_request(examples[0].fields, RECIPE))
        assert session.calls == 26
        assert len(session.accounting) == 26
        row = session.accounting[0]
        assert row["requested_model"] == session.requested_model
        assert all(
            row[k] is None
            for k in ("model", "input_tokens", "output_tokens", "latency_seconds", "cost_usd")
        )
        assert row["capture_dates"] == []
        state, questions, assets = helpers.build_request(examples[0].fields, RECIPE)
        with pytest.raises(RuntimeError, match="budget"):
            session.decide(({**state, "instruction": "New instruction"}, questions, assets))
    assert sum(s.calls for s in spies) == 52


def test_failed_attempts_spend_budget_and_wrong_returned_model_stops():
    class Fails(CountingBackend):
        def decide(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("backend failure")

    request = helpers.build_request(load_inputs(RECIPE)[0].fields, RECIPE)
    backend = Fails()
    session = helpers.ArmSession(backend, helpers.MODELS[0], limit=1)
    with pytest.raises(RuntimeError, match="failure"):
        session.decide(request)
    with pytest.raises(RuntimeError, match="budget"):
        session.decide(request)
    assert backend.calls == 1

    class WrongModel(CountingBackend):
        mode = "recorded"

        def decide(self, *args, **kwargs):
            provenance = Provenance.recorded("jev-1.14.0", "2026-10-14")
            a = ChoiceAnswer.from_probabilities(
                {"match": 0.9, "contradiction": 0.05, "insufficient": 0.05}, provenance
            )
            return DecisionResult({"verify": a}, "jev-1.14.0")

    with pytest.raises(ValueError, match="pinned"):
        helpers.ArmSession(WrongModel(), "jev-1.13.0").decide(request)


def test_recorder_requires_explicit_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("JEV_COOKBOOK_LIVE", raising=False)
    with pytest.raises(RuntimeError, match="explicit"):
        helpers.record_arms(RECIPE, tmp_path / "capture")
    assert not (tmp_path / "capture").exists()


def test_recording_protocol_keeps_identical_requests_and_actual_model_provenance(
    monkeypatch, tmp_path
):
    """Injected clients exercise the real recorder without using a network or credentials."""
    from jev_cookbook import LiveBackend

    calls = {model: [] for model in helpers.MODELS}

    class Client:
        def system_one(self, **kwargs):
            model = kwargs["model"]
            calls[model].append(kwargs)
            value = answer("match").to_dict()
            del value["provenance"]
            return {
                "model": model,
                "answers": {"verify": value},
                "usage": {"input_tokens": 42, "output_tokens": 3},
            }

    def factory(*, fixtures, model, images):
        assert images is True
        return LiveBackend(model, client=Client(), images=True, max_requests=26, max_retries=0)

    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
    monkeypatch.setattr(helpers, "get_backend", factory)
    destination = tmp_path / "capture"
    helpers.record_arms(RECIPE, destination)
    files = [json.loads((destination / helpers.FILES[m]).read_text()) for m in helpers.MODELS]
    assert set(files[0]) == set(files[1])
    for model, records in zip(helpers.MODELS, files, strict=True):
        assert len(calls[model]) == 26
        assert all(r["model"] == model for r in records.values())
        assert all(
            r["answers"]["verify"]["provenance"]["source"] == "recorded" for r in records.values()
        )
        assert all(r["usage"] == {"input_tokens": 42, "output_tokens": 3} for r in records.values())
        assert (destination / f"ledger-{model}.json").exists()
    for a, b in zip(calls[helpers.MODELS[0]], calls[helpers.MODELS[1]], strict=True):
        assert a["state"] == b["state"] and a["questions"] == b["questions"]
        assert a["assets"] == b["assets"]
    helpers.record_arms(RECIPE, destination)
    assert all(len(c) == 26 for c in calls.values())
