"""Settings for the test suite: the real settings in ``test`` mode."""

import os

os.environ["LEASEKEEP_ENV"] = "test"

from leasekeep.settings import *  # noqa: F403
