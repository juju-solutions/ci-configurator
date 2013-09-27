import os

import common

from charmhelpers.core.hookenv import log

ZUUL_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'zuul')


def update_zuul():
    log("*** Updating zuul.")
    if not os.path.isdir(ZUUL_CONFIG_DIR):
        log('Could not find zuul config directory at expected location, '
            'skipping zuul update (%s)' % ZUUL_CONFIG_DIR)
        return
