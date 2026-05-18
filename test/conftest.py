"""Shared test fixtures for massMusicTagger tests."""
import os
import sys
import pytest

# Ensure src/ is on the path for editable installs in test contexts
_SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Path to massMusicTagger's bundled config.yaml — used as the default base
# config in tests so discogstagger3's wheel doesn't need its own conf/ dir.
MMT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'conf', 'config.yaml')


@pytest.fixture
def mmt_config_path():
    return MMT_CONFIG
