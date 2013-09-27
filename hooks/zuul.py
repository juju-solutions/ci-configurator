import os

import common

from charmhelpers.core.hookenv import log, INFO

ZUUL_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'zuul')
ZUUL_INIT_SCRIPT = "/etc/init.d/zuul"

# start and stop services
def start_zuul():
    log("*** Starting zuul server ***", INFO)
    try:
        subprocess.call([ZUUL_INIT_SCRIPT, "start"])
    except:
        pass
def stop_zuul():
    log("*** Stopping zuul server ***", INFO)
    try:
        subprocess.call([ZUUL_INIT_SCRIPT, "stop"])
    except:
        pass


def update_zuul():
    log("*** Updating zuul.")
    layout_path = '/etc/zuul/layout.yaml'

    if not os.path.isdir(ZUUL_CONFIG_DIR):
        log('Could not find zuul config directory at expected location, '
            'skipping zuul update (%s)' % ZUUL_CONFIG_DIR)
        return

    log('Installing layout from %s to %s.' % (ZUUL_CONFIG_DIR, layout_path))
    common.sync_dir(ZUUL_CONFIG_DIR, layout_path)

    stop_zuul()
    start_zuul()

    return True
