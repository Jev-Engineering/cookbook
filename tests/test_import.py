import subprocess
import sys

import jev_cookbook


def test_package_has_version():
    assert isinstance(jev_cookbook.__version__, str)
    assert jev_cookbook.__version__


def test_import_does_not_load_optional_sdk():
    code = (
        "import sys, jev_cookbook; "
        "sys.exit(1 if any(m.split('.')[0] == 'typesafe' for m in sys.modules) else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
