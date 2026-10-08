"""The CI network guard (tools/netguard/sitecustomize.py) and a notebook that tries the network.

Nothing here reaches a network: with the guard on, every non-loopback attempt fails before a packet
is sent, and the one test that needs a reachable address uses loopback.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import nbformat
import pytest

REPO = Path(__file__).resolve().parent.parent
GUARD_DIR = REPO / "tools" / "netguard"
EXECUTE = REPO / "tools" / "execute_notebook.py"
# Built from parts so no key-shaped literal is committed.
PLACEHOLDER_KEY = "-".join(["placeholder", "credential", "z" * 10])


def guarded_env(**extra):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(GUARD_DIR)
    env.update(extra)
    return env


def run_python(code, **extra):
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=guarded_env(**extra),
        timeout=60,
        check=False,
    )


def test_guard_is_loaded_by_pythonpath_alone():
    result = run_python("import socket, sys; print(socket.socket.connect.__module__)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "sitecustomize"


@pytest.mark.parametrize(
    "attempt",
    [
        "socket.create_connection(('192.0.2.1', 80), timeout=5)",
        "socket.socket().connect(('192.0.2.1', 80))",
        "socket.socket().connect_ex(('192.0.2.1', 80))",
        "socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'x', ('192.0.2.1', 53))",
        "socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'x', 0, ('192.0.2.1', 53))",
        "socket.socket(socket.AF_INET6).connect(('2001:db8::1', 80, 0, 0))",
        "socket.getaddrinfo('api.typesafe.ai', 443)",
        "socket.gethostbyname('api.typesafe.ai')",
        "socket.gethostbyname_ex('api.typesafe.ai')",
        "socket.gethostbyaddr('192.0.2.1')",
        "urllib.request.urlopen('https://api.typesafe.ai/', timeout=5)",
        "urllib.request.urlopen('http://192.0.2.1/', timeout=5)",
    ],
)
def test_outbound_attempts_fail_at_once_with_a_clear_error(attempt):
    code = f"""
        import socket, time, urllib.request
        start = time.monotonic()
        try:
            {attempt}
        except OSError as error:
            print("blocked", type(error).__name__, "network access is blocked" in str(error))
        else:
            print("REACHED")
        print("seconds", round(time.monotonic() - start, 1))
    """
    result = run_python(code)
    assert result.returncode == 0, result.stderr
    first, second = result.stdout.splitlines()
    assert first.startswith("blocked"), result.stdout
    # urllib wraps the OSError in a URLError, whose text names the guard; the others raise it.
    assert first.endswith("True"), result.stdout
    assert float(second.split()[1]) < 3, "the refusal must be immediate, not a timeout"


def test_loopback_and_unix_sockets_still_work():
    code = """
        import socket
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname(), timeout=5)
        peer, _ = server.accept()
        client.sendall(b"ping")
        print(peer.recv(4).decode(), socket.gethostbyname("localhost"))
        print(socket.getaddrinfo("127.0.0.1", 80)[0][0].name)
    """
    result = run_python(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[0] == "ping"


def test_loopback_predicate():
    # Read the pure helper without installing the guard into this test process: run the source
    # up to the final install() call.
    source = (GUARD_DIR / "sitecustomize.py").read_text(encoding="utf-8")
    namespace = {"__name__": "guard_helpers"}
    exec(compile(source.rsplit("\ninstall()", 1)[0], str(GUARD_DIR), "exec"), namespace)
    is_loopback = namespace["_is_loopback"]
    for host in ("127.0.0.1", "127.9.9.9", "::1", "localhost", "LOCALHOST", None, "", b"127.0.0.1"):
        assert is_loopback(host), host
    for host in ("192.0.2.1", "8.8.8.8", "2001:db8::1", "api.typesafe.ai", "0.0.0.0", 7):
        assert not is_loopback(host), host


def make_recipe(tmp_path, *cells):
    folder = tmp_path / "recipe"
    folder.mkdir()
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell(textwrap.dedent(c)) for c in cells]
    nbformat.write(nb, folder / "notebook.ipynb")
    return folder


def execute(folder, env):
    return subprocess.run(
        [sys.executable, str(EXECUTE), str(folder)],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        check=False,
    )


def test_notebook_that_calls_the_typesafe_api_fails_with_the_guard(tmp_path):
    folder = make_recipe(
        tmp_path,
        "import urllib.request",
        "urllib.request.urlopen('https://api.typesafe.ai/v1/system-one', timeout=5)",
    )
    before = (folder / "notebook.ipynb").read_bytes()
    result = execute(folder, guarded_env())
    assert result.returncode == 1, result.stdout + result.stderr
    assert "network access is blocked" in result.stderr
    assert (folder / "notebook.ipynb").read_bytes() == before


def test_notebook_that_clears_the_live_switch_still_cannot_reach_out(tmp_path):
    # The executor strips JEV_COOKBOOK_* and TYPESAFE_* from the kernel, so a cell that sets them
    # itself is the only way to ask for the live path; the guard must still hold.
    folder = make_recipe(
        tmp_path,
        "import os, socket",
        f"""
        os.environ["JEV_COOKBOOK_LIVE"] = "1"
        os.environ["TYPESAFE_API_KEY"] = "{PLACEHOLDER_KEY}"
        os.environ["TYPESAFE_BASE_URL"] = "https://api.typesafe.ai"
        socket.create_connection(("api.typesafe.ai", 443), timeout=5)
        """,
    )
    result = execute(folder, guarded_env(JEV_COOKBOOK_LIVE="1", TYPESAFE_API_KEY=PLACEHOLDER_KEY))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "network access is blocked" in result.stderr


def test_offline_notebook_runs_clean_under_the_guard(tmp_path):
    folder = make_recipe(tmp_path, "print('offline')")
    result = execute(folder, guarded_env())
    assert result.returncode == 0, result.stdout + result.stderr
    nb = json.loads((folder / "notebook.ipynb").read_text(encoding="utf-8"))
    assert nb["cells"][0]["outputs"][0]["text"] == ["offline\n"]


def test_live_backend_call_is_blocked_with_the_sdk_installed(tmp_path):
    pytest.importorskip("typesafe_sdk")
    folder = make_recipe(
        tmp_path,
        f"""
        import os
        os.environ["JEV_COOKBOOK_LIVE"] = "1"
        os.environ["JEV_COOKBOOK_LIVE_MODEL"] = "jev-probe"
        os.environ["TYPESAFE_API_KEY"] = "{PLACEHOLDER_KEY}"
        from jev_cookbook import Noul, get_backend
        backend = get_backend(fixtures={{}})
        try:
            backend.decide("a state", {{"q": Noul(instructions="This is a statement.")}})
        except Exception as error:
            print(type(error).__name__)
            raise
        """,
    )
    result = execute(folder, guarded_env())
    assert result.returncode == 1, result.stdout + result.stderr
    assert "LiveCallError" in result.stderr or "network access is blocked" in result.stderr
