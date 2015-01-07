import os

import common


def is_valid_config_repo(location):
    if location and (location.startswith('lp:') or location.startswith('bzr')):
        return True

    return False


def is_ci_configured():
    return os.path.isdir(common.CI_CONFIG_DIR)
