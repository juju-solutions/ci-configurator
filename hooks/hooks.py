#!/usr/bin/python

import os
import sys

import gerrit
import jjb
import zuul

import common

from charmhelpers.core.hookenv import (
    charm_dir,
    config,
    log,
    relation_ids,
    relation_set,
    Hooks,
    UnregisteredHookError,
)


hooks = Hooks()


@hooks.hook()
def install():
    common.ensure_user()
    if not os.path.exists(common.CONFIG_DIR):
        os.mkdir(common.CONFIG_DIR)
    jjb.install()


@hooks.hook()
def config_changed():
    # setup identity to reach private LP resources
    common.ensure_user()
    common.install_ssh_keys()
    lp_user = config('lp-login')
    if lp_user:
        cmd = ['bzr', 'launchpad-login', lp_user]
        common.run_as_user(cmd=cmd, user=common.CI_USER)

    conf_repo = config('config-repo')
    bundled_repo = os.path.join(charm_dir(), common.LOCAL_CONFIG_REPO)

    have_repo = False
    if os.path.exists(bundled_repo) and os.path.isdir(bundled_repo):
        common.update_configs_from_charm(bundled_repo)
        have_repo = True
    elif conf_repo and (conf_repo.startswith('lp:')
                        or conf_repo.startswith('bzr')):
        have_repo = True
        common.update_configs_from_repo(
            conf_repo, config('config-repo-revision'))

    if have_repo:
        gerrit.update_gerrit()
        jjb.update_jenkins()
        zuul.update_zuul()
    else:
        log('Not updating resources until we have a config-repo configured.')

    for rid in relation_ids('jenkins-configurator'):
        jenkins_configurator_relation_joined(rid)


@hooks.hook()
def upgrade_charm():
    config_changed()


@hooks.hook()
def jenkins_configurator_relation_joined(rid=None):
    """
    Inform jenkins of any plugins our tests may require, as defined in the
    control.yml of the config repo
    """
    plugins = jjb.required_plugins()
    if plugins:
        relation_set(required_plugins=' '.join(plugins), relation_id=rid)


@hooks.hook(
    'jenkins-configurator-relation-changed',
    'gerrit-configurator-relation-changed',
    'zuul-configurator-relation-changed',
)
def configurator_relation_changed():
    config_changed()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))


if __name__ == '__main__':
    main()
