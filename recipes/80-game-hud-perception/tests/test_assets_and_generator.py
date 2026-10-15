import importlib.util
import subprocess
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def load_generator(path):
    spec = importlib.util.spec_from_file_location("recipe80_fixture_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_generator(tmp_path):
    recipe = tmp_path / "recipe80"
    recipe.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (recipe / name).write_bytes((RECIPE / name).read_bytes())
    return recipe


def run_generator(recipe, *args):
    return subprocess.run(
        [sys.executable, str(recipe / "build_fixtures.py"), *args],
        capture_output=True,
        text=True,
    )


def test_generator_reproduces_all_original_images(tmp_path):
    recipe = copy_generator(tmp_path)
    done = run_generator(recipe)
    assert done.returncode == 0, done.stderr
    for original in (RECIPE / "assets").iterdir():
        assert (recipe / "assets" / original.name).read_bytes() == original.read_bytes()


def test_malformed_response_file_is_also_protected(tmp_path):
    module = load_generator(RECIPE / "build_fixtures.py")
    path = tmp_path / "responses.json"
    path.write_text("not JSON")
    assert module.protected_response_file(path)
