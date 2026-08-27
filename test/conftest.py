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
# The packaged reference config, not a live conf/config.yaml. The suite used
# to point at the latter -- a gitignored file that only exists on a machine
# where someone has configured the tool -- so 68 tests passed here and would
# have failed on a fresh clone or in CI.
from massmusictagger import roots as _roots
MMT_CONFIG = os.path.join(_roots.BUNDLED_CONF, 'config_sample.yaml')


@pytest.fixture
def mmt_config_path():
    return MMT_CONFIG
