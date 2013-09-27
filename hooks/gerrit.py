import os
import subprocess

import common

from charmhelpers.core.hookenv import log, relation_ids, WARNING

GERRIT_INIT_SCRIPT = '/etc/init.d/gerrit'
GERRIT_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'gerrit')
THEME_DIR = os.path.join(GERRIT_CONFIG_DIR, 'theme')
HOOKS_DIR = os.path.join(GERRIT_CONFIG_DIR, 'hooks')


# start gerrit application
def start_gerrit():
    try:
        subprocess.check_call([GERRIT_INIT_SCRIPT, "start"])
    except:
        pass


# stop gerrit application
def stop_gerrit():
    try:
        subprocess.check_call([GERRIT_INIT_SCRIPT, "stop"])
    except:
        pass


def update_theme():
    # TODO (adam_g)
    # These installation destinations needs to come from principle via relation
    theme_dest = '/home/gerrit2/review_site/etc/'
    static_dest = '/home/gerrit2/review_site/static/'

    if not os.path.isdir(THEME_DIR):
        log('Gerrit theme directory not found @ %s, skipping theme refresh.' %
            THEME_DIR, level=WARNING)
        return False

    theme_orig = os.path.join(THEME_DIR, 'files')
    static_orig = os.path.join(THEME_DIR, 'static')

    if False in [os.path.isdir(theme_orig), os.path.isdir(static_orig)]:
        log('Theme directory @ %s missing required subdirs: files, static. '
            'Skipping theme refresh.' % THEME_DIR, level=WARNING)
        return False

    log('Installing theme from %s to %s.' % (theme_orig, theme_dest))
    common.sync_dir(theme_orig, theme_dest)
    log('Installing static files from %s to %s.' % (theme_orig, theme_dest))
    common.sync_dir(static_orig, static_dest)

    return True


def update_hooks():
    # TODO (adam_g)
    # These installation destinations needs to come from principle via relation
    hooks_dest = '/home/gerrit2/review_site/hooks/'

    if not os.path.isdir(HOOKS_DIR):
        log('Gerrit hooks directory not found @ %s, skipping hooks refresh.' %
            HOOKS_DIR, level=WARNING)
        return False

    # TODO:
    # The hooks require some dynamic data (git server, admin_username)
    # etc.  Need to find a way to either pass it in via:
    #  - a common file sourced by hooks that contains stuff as environment
    #    variables
    #       OR
    #  - some basic templating on the script itself.
    log('Installing gerrit hooks in %s to %s.' % (HOOKS_DIR, hooks_dest))
    common.sync_dir(HOOKS_DIR, hooks_dest)
    return True


def update_permissions():
    # TODO
    return False


def update_gerrit():
    if not relation_ids('gerrit-configurator'):
        return

    log("*** Updating gerrit.")
    if not os.path.isdir(GERRIT_CONFIG_DIR):
        log('Could not find gerrit config directory at expected location, '
            'skipping gerrit update (%s)' % GERRIT_CONFIG_DIR)
        return
    restart_req = False
    restart_req = update_theme()
    restart_req = update_hooks()
    restart_req = update_permissions()

    if restart_req:
        stop_gerrit()
        start_gerrit()
