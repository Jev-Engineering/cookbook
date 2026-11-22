"""README reproduction-install instructions, Markdown context and historical regressions.

The #470 limit controls are retained below. #592 strengthens the back-reference result and
adds paired controls for actual notebook reproduction versus tests/fixture generation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Loaded by path like test_new_recipe.py and test_recipe_guard.py do. Their loaders are not reused:
# importing either test file would run its module-level setup (tools/new_recipe.py, all of
# test_recipe_guard.py) to get 4 lines.
_spec = importlib.util.spec_from_file_location(
    "readme_install_for_own_test", Path(__file__).with_name("readme_install.py")
)
readme_install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(readme_install)
TEMPLATE_README = Path(__file__).resolve().parents[1] / "recipes" / "_template" / "README.md"

_INSTALL = 'pip install -e ".[dev,ml]"'


@pytest.mark.parametrize(
    "words",
    [
        "For byte-for-byte outputs, install",
        "For BYTE-FOR-BYTE outputs, install",
        "For byte for byte outputs, install",
        "To reproduce the outputs, install",
    ],
)
def test_a_reproduction_paragraph_is_recognised_by_its_synonyms(words):
    readme = f"# Recipe\n\n{words} `{_INSTALL}` and run the notebook.\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_a_tests_paragraph_that_says_byte_identical_is_not_refused():
    # #470 code review at 672b254, finding 1: "byte-identical" also describes what the tests check
    # (docs/recipe-template.md), so it does not make a paragraph a reproduction paragraph.
    readme = (
        f"# Recipe\n\nRun the tests with `{_INSTALL}`; they check responses.json is"
        " byte-identical to dump_responses.\n"
    )
    assert readme_install.combined_reproduction_installs(readme) == []


def test_an_ml_recipes_back_reference_sentence_is_refused_as_on_main():
    """Historical name retained: #592 intentionally strengthens the old wrong refusal to pass.

    A quoted extra is not an install command. Keep the actual reproduction install refused
    when mutated; this makes the fix narrower than exempting the entire paragraph.
    """
    historical = (
        'Run tests with `pip install -e ".[dev,ml]"`.\n\n'
        "Reproducing the committed outputs uses "
        '`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`; '
        "`.[dev]` above is for `ruff` and `pytest`.\n"
    )
    assert "`.[dev]` above is for" in historical
    readme = historical.replace("`.[dev]` above is for", "`.[dev,ml]` above is for", 1)
    assert readme != historical
    assert "`.[dev,ml]` above is for" in readme
    assert readme_install.combined_reproduction_installs(readme) == []
    old = readme_install.with_pre_162_reproduction_install(readme)
    assert old != readme
    assert len(readme_install.combined_reproduction_installs(old)) == 1


def test_current_template_back_reference_wording_has_its_own_control():
    readme = TEMPLATE_README.read_text("utf-8")
    assert "the `dev` extra above adds `ruff` and `pytest`" in readme
    assert "`.[dev]` above is for" not in readme
    assert readme_install.combined_reproduction_installs(readme) == []
    old = readme_install.with_pre_162_reproduction_install(readme)
    assert old != readme
    assert len(readme_install.combined_reproduction_installs(old)) == 1


@pytest.mark.parametrize(
    "readme",
    [
        # #470 Gate B at 95a3d4f, findings 1-3 and 6: refused there, passed on main. The word
        # "regenerate" alone does not make a paragraph a reproduction paragraph.
        f"To regenerate the notebook fixtures, run `{_INSTALL}`.\n",
        f"To regenerate the output fixtures, run `{_INSTALL}`.\n",
        f"To regenerate the outputs of `tools/render_catalog.py`, run `{_INSTALL}`.\n",
        f"To regenerate the notebook’s fixtures, run `{_INSTALL}`.\n",
        "10. Install:\n\n    ```bash\n"
        f"    {_INSTALL}\n"
        "    python tools/execute_notebook.py x  # regenerate the committed outputs\n    ```\n",
        f"<!-- regenerate the committed outputs -->\nInstall `{_INSTALL}` to run pytest.\n",
        # #470 Gate B at 1d670fb, finding 1: the tests' fence after a reproduction paragraph
        "Reproducing the outputs byte for byte needs "
        '`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`. To run the tests:\n\n'
        f"```bash\n{_INSTALL}\npytest recipes/NN\n```\n",
    ],
)
def test_what_main_does_not_refuse_is_not_refused(readme):
    assert readme_install.combined_reproduction_installs(readme) == []


def test_paragraphs_are_split_by_blank_lines_only_as_on_main():
    # blank (or whitespace-only) lines split, nothing else does
    readme = "One\nline.\n\n  \nTwo.\n```bash\nx\n```\n"
    assert readme_install.paragraphs(readme) == ["One line.", "Two. ```bash x ```"]


@pytest.mark.parametrize(
    "intro",
    [
        "To reproduce the committed outputs, start from a clean venv. From the repository root:",
        "To reproduce the committed outputs (see the docs, e.g. step 6) run:",
        "To reproduce the committed outputs (i.e. the committed notebook results), run:",
        "**To reproduce the committed outputs:**",
        "## Reproduce the committed outputs",
        "## Regenerate committed notebook outputs",
        "To regenerate the committed notebook outputs:",
        "For byte-identical outputs, install:",
        "For byte identical outputs, install:",
        "To obtain bit-for-bit outputs, install:",
    ],
)
def test_a_reproduction_introduction_owns_its_following_fence(intro):
    bad = f"{intro}\n\n```sh\n{_INSTALL}\n```\n"
    assert len(readme_install.combined_reproduction_installs(bad)) == 1
    assert readme_install.combined_reproduction_installs(bad.replace(".[dev,ml]", ".[ml]")) == []


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("close", ["```", ""])
@pytest.mark.parametrize("container", ["plain", "list", "quote"])
def test_shared_markdown_reader_handles_containers_and_unclosed_fences(ending, close, container):
    lines = ["Reproduce the committed notebook outputs:", "", "```sh", _INSTALL]
    if close:
        lines.append(close)
    if container == "list":
        lines = ["10. Reproduce the committed notebook outputs:", ""] + [
            "    " + line for line in lines[2:]
        ]
    elif container == "quote":
        lines = ["> " + line for line in lines]
    readme = ending.join(lines) + ending
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


@pytest.mark.parametrize(
    "extras",
    ["ml,dev", "dev, ml", " ml , dev ", "dev,ml,live", "live,ml,dev", "DEV,ML"],
)
def test_combined_extras_are_a_set_not_one_literal_spelling(extras):
    readme = f"To reproduce the outputs run `pip install -e '.[{extras}]'`.\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1
    assert readme_install.combined_reproduction_installs(readme.replace(extras, "ml,live")) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "byte-for-byte",
        "byte for byte",
        "byte-for byte",
        "byte-\nfor-byte",
        "byte-for-\nbyte",
        "byte\u2011for\u2011byte",
        "byte\u2010identical",
        "byte identical",
        "bit-for-bit",
        "byte\u2014for\u2014byte",
    ],
)
def test_equality_phrases_require_reproduction_intent_not_a_test_assertion(phrase):
    reproduce = f"For {phrase} outputs, install `{_INSTALL}`.\n"
    tests = f"Run the tests with `{_INSTALL}`; they check that outputs are {phrase}.\n"
    assert len(readme_install.combined_reproduction_installs(reproduce)) == 1
    assert readme_install.combined_reproduction_installs(tests) == []


@pytest.mark.parametrize(
    "prose",
    [
        "To regenerate the notebook fixtures, run",
        "To regenerate the output fixtures, run",
        "To regenerate the notebook\u2019s fixtures, run",
        "To regenerate the outputs of `tools/render_catalog.py`, run",
        "To regenerate committed outputs of `tools/render_catalog.py`, run",
        "Run the tests with",
    ],
)
def test_fixture_and_catalog_generation_are_not_notebook_reproduction(prose):
    assert readme_install.combined_reproduction_installs(f"{prose} `{_INSTALL}`.\n") == []


@pytest.mark.parametrize("word", ["reproduce", "regenerate"])
def test_code_and_html_comments_cannot_establish_reproduction_intent(word):
    readme = (
        f"<!-- {word} the committed outputs -->\n\n"
        f"Run the tests:\n\n```sh\n# {word} the committed outputs\n{_INSTALL}\npytest\n```\n"
    )
    assert readme_install.combined_reproduction_installs(readme) == []


def test_heading_default_yields_to_an_explicit_local_tests_instruction():
    readme = f"## Reproduce the outputs\n\nTo run the tests:\n\n```sh\n{_INSTALL}\n```\n"
    assert readme_install.combined_reproduction_installs(readme) == []
    assert (
        len(
            readme_install.combined_reproduction_installs(
                readme.replace("To run the tests:", "Install:")
            )
        )
        == 1
    )


def test_reproduction_command_before_a_local_tests_intro_remains_checked():
    readme = (
        f"Reproducing the outputs needs `{_INSTALL}`. To run the tests:\n\n"
        f"```sh\n{_INSTALL}\npytest\n```\n"
    )
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_list_item_instruction_does_not_leak_into_the_next_item():
    readme = (
        "1. Reproduce the committed outputs:\n\n"
        "   ```sh\n   pip install -e '.[ml]'\n   ```\n\n"
        f"2. Run tests:\n\n   ```sh\n   {_INSTALL}\n   ```\n"
    )
    assert readme_install.combined_reproduction_installs(readme) == []


def test_an_unrelated_heading_resets_reproduction_context():
    readme = f"## Reproduce outputs\n\nUse the pinned environment.\n\n## Tests\n\n`{_INSTALL}`\n"
    assert readme_install.combined_reproduction_installs(readme) == []


def test_an_indented_code_block_is_an_install_block_but_not_prose_intent():
    readme = f"To reproduce the outputs:\n\n    {_INSTALL}\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1
    assert (
        readme_install.combined_reproduction_installs(f"    # reproduce outputs\n    {_INSTALL}\n")
        == []
    )


def test_html_block_does_not_manufacture_a_fence_or_an_instruction():
    readme = f"<div>\n```\nreproduce the outputs\n{_INSTALL}\n```\n</div>\n\nRun tests.\n"
    assert readme_install.combined_reproduction_installs(readme) == []


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\v", "\f", "\x85"])
def test_non_line_separators_do_not_invent_fence_boundaries(separator):
    readme = f"Intro{separator}~~~\nTo reproduce the outputs run `{_INSTALL}`.\n~~~\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1


def test_every_published_readme_and_template_keeps_its_accepted_install_verdict():
    """Per-file cohort, documented tests substitution and pre162 negative controls.

    This captures the same fifty-one published files and template that pass the main rule;
    no code or test substitutes notebook execution for the README-only property.
    """
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "recipes").glob("*/README.md"))
    assert len(paths) >= 52
    tested = 0
    for path in paths:
        readme = path.read_text("utf-8")
        assert readme_install.combined_reproduction_installs(readme) == [], path
        if readme_install.TEST_INSTALL in readme:
            documented = readme_install.with_documented_test_install(readme)
            assert readme_install.combined_reproduction_installs(documented) == [], path
            tested += 1
        if readme_install.REPRODUCTION_INSTALL in readme:
            old = readme_install.with_pre_162_reproduction_install(readme)
            assert len(readme_install.combined_reproduction_installs(old)) == 1, path
            wrapped = old.replace('".[dev,ml]" -c', '".[dev,ml]"\n-c')
            assert len(readme_install.combined_reproduction_installs(wrapped)) == 1, path
    assert tested > 0


def test_reproduction_purpose_can_follow_the_install_command():
    readme = f"Install `{_INSTALL}` to reproduce the committed outputs.\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1
    assert (
        readme_install.combined_reproduction_installs(
            readme.replace("to reproduce the committed outputs", "to run the tests")
        )
        == []
    )


def test_shell_comments_do_not_supply_a_command_or_constraints_to_another_line():
    readme = f"To reproduce the outputs:\n\n```sh\npip install -e '.[ml]' # {_INSTALL}\n```\n"
    assert readme_install.combined_reproduction_installs(readme) == []
    readme = f"Run the tests:\n\n```sh\n{_INSTALL}\n# constraints-notebooks\n```\n"
    assert readme_install.combined_reproduction_installs(readme) == []


def test_a_description_of_what_tests_reproduce_is_not_an_install_instruction():
    readme = f"Run the tests with `{_INSTALL}`; they reproduce the expected fixture bytes.\n"
    assert readme_install.combined_reproduction_installs(readme) == []


@pytest.mark.parametrize("apostrophe", ["'", "’"])
def test_regeneration_can_name_the_notebooks_outputs(apostrophe):
    readme = f"To regenerate the notebook{apostrophe}s outputs, run `{_INSTALL}`.\n"
    assert len(readme_install.combined_reproduction_installs(readme)) == 1
    assert (
        readme_install.combined_reproduction_installs(readme.replace("outputs", "fixtures")) == []
    )


@pytest.mark.parametrize(
    "path", [".github/constraints-notebooks.txt", "`.github/constraints-notebooks.txt`"]
)
def test_constraints_path_in_prose_restores_parent_intent(path):
    inline = f"Using {path}, install `{_INSTALL}`.\n"
    fenced = f"Using {path}, install:\n\n```sh\n{_INSTALL}\n```\n"
    assert len(readme_install.combined_reproduction_installs(inline)) == 1
    assert len(readme_install.combined_reproduction_installs(fenced)) == 1
    assert readme_install.combined_reproduction_installs(inline.replace(".[dev,ml]", ".[ml]")) == []


def test_constraints_path_in_a_prose_comment_or_shell_comment_is_not_intent():
    prose = f"<!-- Using .github/constraints-notebooks.txt -->\n\nRun tests with `{_INSTALL}`.\n"
    code = f"```sh\n# Using .github/constraints-notebooks.txt\n{_INSTALL}\n```\n"
    assert readme_install.combined_reproduction_installs(prose) == []
    assert readme_install.combined_reproduction_installs(code) == []


@pytest.mark.parametrize("printer", ["echo", "printf '%s'", "python -c"])
@pytest.mark.parametrize("formatted", ["fence", "inline"])
def test_printed_shell_argument_is_not_a_direct_install(printer, formatted):
    command = f"{printer} '{_INSTALL}'"
    text = f"```sh\n{command}\n```" if formatted == "fence" else f"`{command}`"
    readme = "To reproduce the outputs:\n\n" + text
    assert readme_install.combined_reproduction_installs(readme) == []
    direct = f"```sh\n{_INSTALL}\n```" if formatted == "fence" else f"`{_INSTALL}`"
    assert (
        len(readme_install.combined_reproduction_installs("To reproduce the outputs:\n\n" + direct))
        == 1
    )


def test_html_comment_delimiters_do_not_hide_commands_inside_a_fence():
    text = f"To reproduce outputs:\n\n```sh\n# <!--\n{_INSTALL}\n# -->\n```\n"
    assert len(readme_install.combined_reproduction_installs(text)) == 1
    assert readme_install.combined_reproduction_installs(text.replace(".[dev,ml]", ".[ml]")) == []


def test_html_attributes_cannot_supply_an_install_but_visible_code_can():
    text = f"To reproduce outputs, <span title='{_INSTALL}'>use the pinned install</span>.\n"
    assert readme_install.combined_reproduction_installs(text) == []
    text = f"To reproduce outputs, <span title='example > title'>`{_INSTALL}`</span>.\n"
    assert len(readme_install.combined_reproduction_installs(text)) == 1


def test_inline_html_attribute_cannot_supply_context_to_a_following_fence():
    text = (
        f"<span title='example > to reproduce outputs'>Run tests</span>:\n\n"
        f"```sh\n{_INSTALL}\n```\n"
    )
    assert readme_install.combined_reproduction_installs(text) == []


@pytest.mark.parametrize("literal", ["O'Reilly", 'a = "unterminated', "don't parse this as shell"])
def test_unrelated_inline_code_does_not_need_valid_shell_quoting(literal):
    text = f"The fixture contains the literal `{literal}`.\n"
    assert readme_install.combined_reproduction_installs(text) == []


@pytest.mark.parametrize("formatted", ["inline", "fence"])
def test_malformed_direct_install_remains_a_visible_failure(formatted):
    command = 'pip install -e ".[dev,ml]'
    text = f"`{command}`" if formatted == "inline" else f"```sh\n{command}\n```\n"
    with pytest.raises(ValueError, match="quotation"):
        readme_install.combined_reproduction_installs(text)


@pytest.mark.parametrize(
    "argument",
    [
        "-c .github/constraints-notebooks.txt",
        '-c ".github/constraints-notebooks.txt"',
        "--constraint='.github/constraints-notebooks.txt'",
        "-c\n.github/constraints-notebooks.txt",
    ],
)
def test_unformatted_install_retains_its_trailing_constraints_argument(argument):
    text = f"Install {_INSTALL} {argument}.\n"
    assert len(readme_install.combined_reproduction_installs(text)) == 1
    assert readme_install.combined_reproduction_installs(text.replace(".[dev,ml]", ".[ml]")) == []
    assert (
        readme_install.combined_reproduction_installs(f"Install {_INSTALL} to run the tests.\n")
        == []
    )


def test_trailing_prose_apostrophe_does_not_become_part_of_a_shell_command():
    text = f"Install {_INSTALL} to reproduce the user's committed outputs.\n"
    assert len(readme_install.combined_reproduction_installs(text)) == 1


# Controls added while porting #592 to main (mutation survivors: each paired control below failed
# to fail one single-line mutant of tests/readme_install.py in the prepared source).


def test_a_dev_only_install_is_not_a_combined_install_even_in_a_reproduction_context():
    text = 'To reproduce the committed outputs:\n\n```sh\npip install -e ".[dev]"\n```\n'
    assert readme_install.combined_reproduction_installs(text) == []
    assert (
        len(readme_install.combined_reproduction_installs(text.replace("[dev]", "[dev,ml]"))) == 1
    )


def test_a_list_item_restores_the_enclosing_reproduction_instruction_when_it_closes():
    text = (
        "Reproduce the committed outputs byte for byte:\n\n"
        "- To run the tests:\n\n"
        "  ```sh\n"
        '  pip install -e ".[dev,ml]"\n'
        "  ```\n\n"
        "```sh\n"
        'pip install -e ".[dev,ml]"\n'
        "```\n"
    )
    # Only the block after the list is under the reproduction instruction again.
    assert len(readme_install.combined_reproduction_installs(text)) == 1


def test_an_html_comment_cannot_supply_reproduction_intent_even_if_it_contains_a_gt():
    text = f"Run the tests with `{_INSTALL}` <!-- a > reproduce the committed outputs -->.\n"
    assert readme_install.combined_reproduction_installs(text) == []
    assert len(readme_install.combined_reproduction_installs(text.replace("<!-- a > ", ""))) == 1


@pytest.mark.parametrize("flag", ["-e", "--editable"])
def test_both_editable_spellings_are_direct_installs(flag):
    text = f'To reproduce the committed outputs:\n\n```sh\npip install {flag} ".[dev,ml]"\n```\n'
    assert len(readme_install.combined_reproduction_installs(text)) == 1


def test_a_shell_comment_after_a_tests_install_is_not_a_constraints_argument():
    text = (
        "To run the tests:\n\n```sh\n"
        'pip install -e ".[dev,ml]"  # not the constraints-notebooks.txt stack\n```\n'
    )
    assert readme_install.combined_reproduction_installs(text) == []


# B1 of the PR #641 review (seat A): a dev+ml install that names the notebook constraints file was
# refused on main whatever the pip options, prompt or wrapper around it. Each spelling below must
# stay refused, in a fence and in inline code, with and without a reproduction introduction.

_CONSTRAINT = "-c .github/constraints-notebooks.txt"
_SPELLINGS = [
    f'pip install -e ".[dev,ml]" {_CONSTRAINT}',
    f'pip install {_CONSTRAINT} -e ".[dev,ml]"',
    f'pip install -q -e ".[dev,ml]" {_CONSTRAINT}',
    f'pip install --upgrade -e ".[dev,ml]" {_CONSTRAINT}',
    f'python -m pip install -U -e ".[dev,ml]" {_CONSTRAINT}',
    f'uv pip install -e ".[dev,ml]" {_CONSTRAINT}',
    f'$ pip install -e ".[dev,ml]" {_CONSTRAINT}',
    f'> pip install -e ".[dev,ml]" {_CONSTRAINT}',
    f'PS> py -m pip install -e ".[dev,ml]" {_CONSTRAINT}',
    f'sudo pip install -e ".[dev,ml]" {_CONSTRAINT}',
    f'PIP_NO_CACHE_DIR=1 pip install -e ".[dev,ml]" {_CONSTRAINT}',
    f'echo go && pip install -e ".[dev,ml]" {_CONSTRAINT}',
    'pip install --constraint=.github/constraints-notebooks.txt -e ".[dev,ml]"',
    f'pip install --no-cache-dir -r requirements.txt -e ".[dev,ml]" {_CONSTRAINT}',
]


@pytest.mark.parametrize("command", _SPELLINGS)
@pytest.mark.parametrize("formatted", ["fence", "inline"])
@pytest.mark.parametrize("intro", ["Install:", "To reproduce the committed outputs:"])
def test_a_constrained_dev_ml_install_is_refused_whatever_surrounds_it(command, formatted, intro):
    text = f"```sh\n{command}\n```\n" if formatted == "fence" else f"`{command}`\n"
    assert len(readme_install.combined_reproduction_installs(f"{intro}\n\n{text}")) == 1
    ok = text.replace(".[dev,ml]", ".[ml]")
    assert readme_install.combined_reproduction_installs(f"{intro}\n\n{ok}") == []


@pytest.mark.parametrize(
    "command",
    [
        'pip install -q -e ".[dev,ml]"',
        'pip install -c .github/constraints.txt -e ".[dev,ml]"',
        '$ uv pip install --upgrade -e ".[dev,ml]"',
    ],
)
def test_an_unconstrained_dev_ml_install_still_depends_on_the_introduction(command):
    block = f"```sh\n{command}\n```\n"
    assert readme_install.combined_reproduction_installs(f"To run the tests:\n\n{block}") == []
    reproduce = f"To reproduce the committed outputs:\n\n{block}"
    assert len(readme_install.combined_reproduction_installs(reproduce)) == 1


def test_a_dev_ml_install_wrapped_across_lines_with_options_is_refused():
    text = (
        "```sh\npip install \\\n  -q \\\n  -e \\\n"
        '  ".[dev,ml]" \\\n  -c .github/constraints-notebooks.txt\n```\n'
    )
    assert len(readme_install.combined_reproduction_installs(text)) == 1
    split = 'To reproduce the outputs:\n\n```sh\npip install \\\n-e ".[dev,ml]"\n```\n'
    assert len(readme_install.combined_reproduction_installs(split)) == 1
    assert readme_install.combined_reproduction_installs(split.replace(".[dev,ml]", ".[ml]")) == []


def test_reproducible_in_the_middle_of_a_sentence_is_not_reproduction_intent():
    text = f"The runs are reproducible, so run the suite with `{_INSTALL}`.\n"
    assert readme_install.combined_reproduction_installs(text) == []
    assert (
        len(readme_install.combined_reproduction_installs(f"To reproduce, run `{_INSTALL}`.")) == 1
    )


@pytest.mark.parametrize("options", ["-q", "--upgrade", f"{_CONSTRAINT}"])
def test_an_unformatted_install_with_options_before_the_target_is_recognised(options):
    text = f'To reproduce the committed outputs, run pip install {options} -e ".[dev,ml]".\n'
    assert len(readme_install.combined_reproduction_installs(text)) == 1
    assert readme_install.combined_reproduction_installs(text.replace(".[dev,ml]", ".[ml]")) == []


# Launcher forms pinned after the #641 reviews (seat A): no constraints file on the line, so only
# the parsed command and the reproduction introduction decide. Each must be refused in a
# reproduction section and allowed in a tests section.


@pytest.mark.parametrize(
    "command",
    [
        "py -m pip install .[dev,ml]",
        "py -3.14 -m pip install .[dev,ml]",
        'py -3 -m pip install -e ".[dev,ml]"',
        'sudo -H pip install -e ".[dev,ml]"',
        'sudo -E -H python -m pip install -e ".[dev,ml]"',
    ],
)
@pytest.mark.parametrize("formatted", ["fence", "inline"])
def test_launcher_and_sudo_forms_are_refused_in_a_reproduction_section(command, formatted):
    block = f"```sh\n{command}\n```\n" if formatted == "fence" else f"`{command}`\n"
    reproduce = f"To reproduce the committed outputs:\n\n{block}"
    assert len(readme_install.combined_reproduction_installs(reproduce)) == 1
    assert readme_install.combined_reproduction_installs(f"To run the tests:\n\n{block}") == []
    assert readme_install.combined_reproduction_installs(reproduce.replace("dev,ml", "ml")) == []
