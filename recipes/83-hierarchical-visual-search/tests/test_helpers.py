"""Exercise search policy boundaries independently of authored replay answers."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    BoxAnswer,
    ChoiceAnswer,
    Provenance,
    ReplayBackend,
    load_helpers,
    replay_key,
)
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def choice(stage, selected, probability=0.98):
    options = (
        ("tile_0", "tile_1", "tile_2", "tile_3", "none", "uncertain")
        if stage == "tile"
        else ("present", "none", "uncertain")
    )
    return ChoiceAnswer.from_probabilities(
        {
            option: probability if option == selected else (1 - probability) / (len(options) - 1)
            for option in options
        },
        Provenance.synthetic(),
    )


def box(confidence=0.98, **edges):
    return BoxAnswer(
        box=edges or {"left": 0.1, "top": 0.1, "right": 0.13, "bottom": 0.13},
        confidence=confidence,
        provenance=Provenance.synthetic(),
    )


class QueueBackend:
    """Fail immediately if the policy asks an extra or combined question."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def decide(self, state, questions, *, assets):
        assert len(questions) == 1
        index = len(self.requests)
        assert index < len(self.answers), "policy exceeded the permitted request sequence"
        name, answer = self.answers[index]
        assert tuple(questions) == (name,)
        self.requests.append((state, questions, assets))
        return {name: answer}


@pytest.fixture
def root():
    image = Image.new("RGB", (1024, 768), "#FEFEFE")
    image.putpixel((0, 0), (243, 134, 161))
    return helpers.View(image, (0, 0, 1024, 768))


def successful_backend(mode, location=None):
    location = box() if location is None else location
    if mode == "search":
        return QueueBackend(
            ("tile", choice("tile", "tile_3")),
            ("tile", choice("tile", "tile_3")),
            ("location", location),
        )
    return QueueBackend(("presence", choice("presence", "present")), ("location", location))


def test_nested_mapping_has_an_independent_pixel_oracle(root):
    backend = successful_backend("search", box(left=0.25, top=0.25, right=0.375, bottom=0.375))
    outcome = helpers.search(backend, root, policy="wide")

    # Bottom-right 640x512 crop, then bottom-right 448x384 crop, starts at (576,384).
    # The returned box occupies pixels (688,480)-(744,528), with exclusive end edges.
    assert outcome.status == "localized"
    assert outcome.box == pytest.approx(
        {"left": 688 / 1024, "top": 480 / 768, "right": 744 / 1024, "bottom": 528 / 768}
    )
    assert [next(iter(request[1])) for request in backend.requests] == [
        "tile",
        "tile",
        "location",
    ]
    assert outcome.calls == 3


@pytest.mark.parametrize(
    ("path", "edges"),
    [
        (("tile_0", "tile_3"), (308 / 448, 252 / 384, 332 / 448, 276 / 384)),
        (("tile_3", "tile_0"), (116 / 448, 124 / 384, 140 / 448, 148 / 384)),
    ],
)
def test_two_overlapping_paths_can_localize_the_same_marker(root, path, edges):
    left, top, right, bottom = edges
    backend = QueueBackend(
        ("tile", choice("tile", path[0])),
        ("tile", choice("tile", path[1])),
        ("location", box(left=left, top=top, right=right, bottom=bottom)),
    )
    outcome = helpers.search(backend, root, policy="wide")
    expected = {
        "left": 500 / 1024,
        "top": 380 / 768,
        "right": 524 / 1024,
        "bottom": 404 / 768,
    }
    assert outcome.box == pytest.approx(expected)
    assert helpers.hit(outcome, {"status": "present", "box": expected})


@pytest.mark.parametrize("mode", ["search", "direct"])
@pytest.mark.parametrize("budget", [0, 1, 2, 3, 20])
def test_budget_limits_actual_requests_even_with_certain_answers(root, mode, budget):
    backend = successful_backend(mode)
    outcome = getattr(helpers, mode)(backend, root, max_calls=budget)
    required = 3 if mode == "search" else 2
    assert outcome.calls == len(backend.requests) == min(budget, required)
    assert outcome.status == ("localized" if budget >= required else "review")
    if budget < required:
        assert outcome.reason == "request_budget"
        assert outcome.box is None


@pytest.mark.parametrize("depth", [0, 1])
def test_depth_limit_never_falls_through_to_a_box(root, depth):
    backend = QueueBackend(*[("tile", choice("tile", "tile_0"))] * depth)
    outcome = helpers.search(backend, root, max_depth=depth)
    assert (outcome.status, outcome.reason, outcome.calls) == ("review", "depth_limit", depth)
    assert len(backend.requests) == depth
    assert outcome.box is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"gate": -0.01},
        {"gate": 1.01},
        {"gate": float("nan")},
        {"gate": float("inf")},
        {"gate": True},
        {"max_calls": -1},
        {"max_calls": 1.5},
        {"max_calls": True},
    ],
)
@pytest.mark.parametrize("mode", ["search", "direct"])
def test_invalid_limits_are_rejected_before_a_request(root, mode, arguments):
    backend = QueueBackend()
    with pytest.raises(ValueError):
        getattr(helpers, mode)(backend, root, **arguments)
    assert not backend.requests


@pytest.mark.parametrize("depth", [-1, 3, 1.5, True])
def test_invalid_depth_is_rejected_before_a_request(root, depth):
    with pytest.raises(ValueError):
        helpers.search(QueueBackend(), root, max_depth=depth)


def test_unknown_policy_and_unusable_tile_sizes_do_not_spend_calls(root):
    with pytest.raises(ValueError, match="policy"):
        helpers.search(QueueBackend(), root, policy="unknown")
    tiny = helpers.View(Image.new("RGB", (300, 300)), (0, 0, 300, 300))
    backend = QueueBackend()
    outcome = helpers.search(backend, tiny)
    assert (outcome.status, outcome.reason, outcome.calls) == ("review", "tile_size", 0)
    assert not backend.requests


@pytest.mark.parametrize("mode", ["search", "direct"])
def test_whole_image_none_is_terminal_and_records_no_rectangle(root, mode):
    stage = "tile" if mode == "search" else "presence"
    backend = QueueBackend((stage, choice(stage, "none")))
    outcome = getattr(helpers, mode)(backend, root)
    assert (outcome.status, outcome.calls, outcome.box) == ("absent", 1, None)
    actions, reviews = helpers.record_outcome("absent", outcome)
    assert len(actions) == len(reviews) == 0


def test_none_in_a_selected_crop_does_not_claim_global_absence(root):
    backend = QueueBackend(
        ("tile", choice("tile", "tile_0")),
        ("tile", choice("tile", "none")),
    )
    outcome = helpers.search(backend, root)
    assert (outcome.status, outcome.reason, outcome.calls) == (
        "review",
        "selected_branch_has_no_target",
        2,
    )
    assert outcome.box is None


@pytest.mark.parametrize("mode", ["search", "direct"])
@pytest.mark.parametrize("selected", ["none", "uncertain"])
def test_low_confidence_fallbacks_stop_without_box(root, mode, selected):
    stage = "tile" if mode == "search" else "presence"
    backend = QueueBackend((stage, choice(stage, selected, probability=0.55)))
    outcome = getattr(helpers, mode)(backend, root, gate=0.7)
    assert outcome.status == "review"
    assert outcome.calls == 1
    assert outcome.box is None


@pytest.mark.parametrize("mode", ["search", "direct"])
def test_certain_uncertainty_is_review_and_never_coverage(root, mode):
    stage = "tile" if mode == "search" else "presence"
    backend = QueueBackend((stage, choice(stage, "uncertain", probability=1)))
    outcome = getattr(helpers, mode)(backend, root, gate=0)
    actions, reviews = helpers.record_outcome("ambiguous", outcome)
    assert len(actions) == 0
    assert len(reviews) == 1
    metrics = helpers.summarize([outcome], [{"status": "review", "box": None}])
    assert metrics["hits"] == 1
    assert metrics["coverage"] == 0
    assert metrics["review"] == 1


@pytest.mark.parametrize("mode", ["search", "direct"])
def test_unknown_option_is_review_even_at_full_confidence(root, mode):
    stage = "tile" if mode == "search" else "presence"
    backend = QueueBackend((stage, SimpleNamespace(choice="foreign", confidence=1.0)))
    outcome = getattr(helpers, mode)(backend, root)
    assert outcome.status == "review"
    assert outcome.calls == 1
    assert outcome.box is None


@pytest.mark.parametrize("mode", ["search", "direct"])
@pytest.mark.parametrize("confidence", [None, 0.2])
def test_missing_or_low_box_confidence_is_not_treated_as_certainty(root, mode, confidence):
    backend = successful_backend(mode, box(confidence=confidence))
    outcome = getattr(helpers, mode)(backend, root)
    expected = (
        "box confidence unavailable" if confidence is None else "confidence below the threshold"
    )
    assert (outcome.status, outcome.reason, outcome.box) == ("review", expected, None)
    actions, reviews = helpers.record_outcome("unknown-confidence", outcome)
    assert len(actions) == 0
    assert len(reviews) == 1


@pytest.mark.parametrize("mode", ["search", "direct"])
def test_missing_box_confidence_remains_unknown_at_a_zero_gate(root, mode):
    backend = successful_backend(mode, box(confidence=None))
    outcome = getattr(helpers, mode)(backend, root, gate=0)
    assert (outcome.status, outcome.reason) == ("review", "box confidence unavailable")


@pytest.mark.parametrize("mode", ["search", "direct"])
def test_reported_box_confidence_exactly_at_the_gate_is_accepted(root, mode):
    backend = successful_backend(mode, box(confidence=0.7))
    outcome = getattr(helpers, mode)(backend, root, gate=0.7)
    assert outcome.status == "localized"


@pytest.mark.parametrize("mode", ["search", "direct"])
@pytest.mark.parametrize(
    "edges",
    [
        {},
        {"left": 0.2, "top": 0.2, "right": 0.2, "bottom": 0.3},
        {"left": 0.3, "top": 0.2, "right": 0.2, "bottom": 0.3},
        {"left": -0.01, "top": 0.2, "right": 0.03, "bottom": 0.3},
        {"left": 0.99, "top": 0.2, "right": 1.01, "bottom": 0.3},
        {"left": 0.2, "top": float("nan"), "right": 0.3, "bottom": 0.3},
        {"left": 0.2, "top": 0.2, "right": float("inf"), "bottom": 0.3},
    ],
)
def test_invalid_geometry_is_review_without_clamping_it_into_a_result(root, mode, edges):
    backend = successful_backend(mode, SimpleNamespace(box=edges, confidence=0.99))
    outcome = getattr(helpers, mode)(backend, root)
    assert (outcome.status, outcome.reason, outcome.box) == ("review", "invalid_box", None)


@pytest.mark.parametrize("mode", ["search", "direct"])
def test_full_view_rectangle_is_not_a_small_marker(root, mode):
    backend = successful_backend(mode, box(left=0, top=0, right=1, bottom=1))
    outcome = getattr(helpers, mode)(backend, root)
    assert (outcome.status, outcome.reason, outcome.box) == ("review", "marker_size", None)


def test_gate_accepts_its_boundary_and_rejects_a_lower_choice(root):
    tile = choice("tile", "tile_0", probability=0.75)
    backend = QueueBackend(("tile", tile), ("tile", tile), ("location", box()))
    assert helpers.search(backend, root, gate=tile.confidence).status == "localized"
    backend = QueueBackend(("tile", tile))
    outcome = helpers.search(backend, root, gate=tile.confidence + 0.001)
    assert (outcome.status, outcome.reason, outcome.calls) == (
        "review",
        "confidence below the threshold",
        1,
    )


def test_gold_does_not_repair_a_confident_wrong_localization(root):
    outcome = helpers.search(successful_backend("search"), root)
    gold = {
        "status": "present",
        "box": {"left": 0.01, "top": 0.01, "right": 0.03, "bottom": 0.04},
    }
    assert outcome.status == "localized"
    assert not helpers.hit(outcome, gold)
    metrics = helpers.summarize([outcome], [gold])
    assert metrics["coverage"] == metrics["risk"] == 1
    assert metrics["wrong_accepted"] == 1
    assert metrics["mean_iou_all_present"] == 0
    actions, reviews = helpers.record_outcome("wrong-but-accepted", outcome)
    assert len(reviews) == 0
    assert len(actions) == 1
    assert actions.to_dicts()[0]["executed"] is False


def test_mean_iou_includes_present_misses_and_excludes_absent_gold():
    rectangle = {"left": 0.1, "top": 0.1, "right": 0.12, "bottom": 0.13}
    outcomes = [
        helpers.Outcome("localized", "test", rectangle, 3, ()),
        helpers.Outcome("review", "test", None, 1, ()),
        helpers.Outcome("absent", "test", None, 1, ()),
        helpers.Outcome("review", "test", None, 1, ()),
    ]
    labels = [
        {"status": "present", "box": rectangle},
        {"status": "present", "box": rectangle},
        {"status": "absent", "box": None},
        {"status": "review", "box": None},
    ]
    metrics = helpers.summarize(outcomes, labels)
    assert metrics["mean_iou_all_present"] == 0.5
    assert metrics["coverage"] == 0.5
    assert metrics["hits"] == 3
    assert metrics["risk"] == 0
    assert metrics["calls"] == 6


def test_request_state_excludes_gold_metadata_and_file_names(root, tmp_path):
    root.image.save(tmp_path / "neutral.png")
    root.image.save(tmp_path / "different-name.png")
    clean = helpers.load_view({"image": "neutral.png"}, tmp_path)
    contaminated = helpers.load_view(
        {
            "image": "different-name.png",
            "gold_box": [9, 18, 45, 67],
            "gold_tile": "tile_2",
            "status": "absent",
            "split": "test",
            "case_kind": "wrong_tile",
        },
        tmp_path,
    )
    for build in (
        helpers.presence_request,
        helpers.box_request,
        lambda view: helpers.tile_request(helpers.split_view(view, "wide")),
    ):
        first, second = build(clean), build(contaminated)
        assert replay_key(first[0], first[1], assets=first[2]) == replay_key(
            second[0], second[1], assets=second[2]
        )
        assert set(first[0]) <= {"target", "image"}
        assert "neutral.png" not in json.dumps(first[0])
        assert "different-name.png" not in json.dumps(second[0])


def test_cache_reuses_identical_requests_but_invalidates_when_pixels_change(root):
    backend = QueueBackend(
        ("presence", choice("presence", "present")),
        ("presence", choice("presence", "none")),
    )
    cache = helpers.RequestCache(backend)
    state, questions, assets = helpers.presence_request(root)
    first = cache.decide(state, questions, assets=assets)
    assert cache.decide(state, questions, assets=assets) is first
    changed = root.image.copy()
    changed.putpixel((17, 19), (0, 0, 0))
    state, questions, assets = helpers.presence_request(helpers.View(changed, root.bounds))
    second = cache.decide(state, questions, assets=assets)
    assert second["presence"].choice == "none"
    assert len(backend.requests) == len(cache.requests) == 2


def test_selection_rejects_test_data_before_loading_pixels_or_spending_calls():
    held_out = [SimpleNamespace(id="t01", split="test", fields={})]
    backend = QueueBackend()
    with pytest.raises(ValueError, match="validation"):
        helpers.select_policy(backend, held_out, {}, objective=helpers.OBJECTIVE)
    with pytest.raises(ValueError, match="validation"):
        helpers.select_direct_gate(backend, held_out, {})
    with pytest.raises(ValueError, match="objective"):
        helpers.select_policy(backend, [], {}, objective="tune on test")
    assert not backend.requests


def test_frozen_fixture_policies_leave_confident_wrong_answers_visible():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    cache = helpers.RequestCache(ReplayBackend.from_json(responses_path(RECIPE)))
    validation = select_split(examples, "validation")
    (policy, gate), _ = helpers.select_policy(
        cache, validation, labels, RECIPE, objective=helpers.OBJECTIVE
    )
    direct_gate, _ = helpers.select_direct_gate(cache, validation, labels, RECIPE)
    held_out = select_split(examples, "test")
    gold = [labels[example.id] for example in held_out]
    hierarchical = [
        helpers.search(cache, helpers.load_view(example.fields, RECIPE), policy=policy, gate=gate)
        for example in held_out
    ]
    baseline = [
        helpers.direct(cache, helpers.load_view(example.fields, RECIPE), gate=direct_gate)
        for example in held_out
    ]
    for outcomes in (hierarchical, baseline):
        metrics = helpers.summarize(outcomes, gold)
        assert metrics["wrong_accepted"] > 0
        assert 0 < metrics["coverage"] < 1
        assert metrics["risk"] > 0
        assert any(outcome.status == "absent" for outcome in outcomes)
        assert any(outcome.reason == "box confidence unavailable" for outcome in outcomes)


def test_replayed_request_keys_cover_the_real_policy_paths():
    examples = load_inputs(RECIPE)
    stored = json.loads(responses_path(RECIPE).read_text("utf-8"))
    observed = set()
    for example in examples:
        cache = helpers.RequestCache(ReplayBackend.from_json(responses_path(RECIPE)))
        view = helpers.load_view(example.fields, RECIPE)
        for policy in helpers.POLICIES:
            helpers.search(cache, view, policy=policy, gate=0)
        helpers.direct(cache, view, gate=0)
        assert set(cache.requests) == set(example.replay_keys)
        observed.update(cache.requests)
    assert observed == set(stored)


def test_notebook_declares_the_same_objective_it_passes_to_selection():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    sources = ["".join(cell["source"]) for cell in notebook["cells"]]
    assert helpers.OBJECTIVE in "\n".join(sources)
    calls = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        calls.extend(
            node
            for node in ast.walk(ast.parse("".join(cell["source"])))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "helpers"
            and node.func.attr == "select_policy"
        )
    assert len(calls) == 1
    assert any(
        keyword.arg == "objective"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value == helpers.OBJECTIVE
        for keyword in calls[0].keywords
    )


def test_capture_requires_explicit_live_mode():
    with pytest.raises(ValueError, match="explicitly selected live"):
        helpers.CaptureBackend(
            SimpleNamespace(mode="synthetic"), "recorded.json", ledger_path="ledger.json"
        )


def test_capture_records_the_exact_image_request_before_replaying_it(root, monkeypatch, tmp_path):
    backend = SimpleNamespace(mode="live")
    target = tmp_path / "recorded.json"
    ledger = tmp_path / "ledger.json"
    request = helpers.presence_request(root)
    expected = choice("presence", "none")
    events = []

    def recorder(live, requests, output_path, *, ledger_path):
        assert live is backend
        assert requests == [request]
        assert output_path == target and ledger_path == ledger
        events.append("recorded")

    class RecordedReplay:
        @staticmethod
        def from_json(path):
            assert path == target
            assert events == ["recorded"]
            return RecordedReplay()

        def decide(self, state, questions, *, assets):
            assert (state, questions, assets) == request
            events.append("replayed")
            return {"presence": expected}

    monkeypatch.setattr(helpers, "record", recorder)
    monkeypatch.setattr(helpers, "ReplayBackend", RecordedReplay)
    captured = helpers.CaptureBackend(backend, target, ledger_path=ledger)
    result = captured.decide(request[0], request[1], assets=request[2])
    assert result["presence"] is expected
    assert events == ["recorded", "replayed"]


@pytest.mark.parametrize("gold_status", ["present", "absent"])
def test_failure_display_handles_live_runs_without_a_gold_rectangle(gold_status, capsys):
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = next(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code" and "failed_index = next(" in "".join(cell["source"])
    )
    rectangle = {"left": 0.1, "top": 0.1, "right": 0.13, "bottom": 0.14}
    outcome = helpers.Outcome("localized", "test", rectangle, 3, ())
    displayed = []
    scope = {
        "helpers": helpers,
        "json": json,
        "ActionLog": helpers.ActionLog,
        "ReviewQueue": helpers.ReviewQueue,
        "draw_boxes": lambda image, overlays: (image.size, set(overlays)),
        "display": displayed.append,
        "test": [
            SimpleNamespace(id="example", fields={"image": str(RECIPE / "assets/scene-14.png")})
        ],
        "test_labels": [
            {"status": gold_status, "box": rectangle if gold_status == "present" else None}
        ],
        "hierarchy_outcomes": [outcome],
    }
    exec(compile(source, "<notebook-failure-display>", "exec"), scope)
    if gold_status == "present":
        assert not displayed
        assert "no accepted wrong localization" in capsys.readouterr().out
    else:
        assert displayed == [((1024, 768), {"returned"})]
