"""Test configuration.

The application modules live in the repository root rather than in a package,
so the root has to be importable from here. pytest adds the directory holding
the test file, which is this one, not the root -- hence the explicit insert,
which also makes the tests work when run from inside this folder.

`unittest discover` needs `-t ..` (top level directory) to do the equivalent;
`run_unit_tests.bat` and `run_tests.sh` both pass it.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
