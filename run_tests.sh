#!/bin/bash
# Runs the whole test suite on Linux/macOS.
#
# Kivy opens a window while the tests run -- the editor tests build real widgets
# and fail without a window provider -- so this needs a display.
cd "$(dirname "$0")"
source kivy_venv/bin/activate
export KIVY_NO_ARGS=1

if python -c "import pytest" 2>/dev/null; then
    if python -c "import pytest_cov" 2>/dev/null; then
        python -m pytest -q --cov --cov-report=term
    else
        python -m pytest -q
    fi
else
    echo "pytest not installed; using unittest discovery."
    python -m unittest discover -s tests -t . -p "test_*.py"
fi
