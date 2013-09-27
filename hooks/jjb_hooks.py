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
    relation_get,
    relation_set,
    Hooks,
    UnregisteredHookError,
)


hooks = Hooks()


@hooks.hook()
def install():
    if not os.path.exists(common.CONFIG_DIR):
        os.mkdir(common.CONFIG_DIR)
    jjb.install()


@hooks.hook()
def config_changed():
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
        # check if we need to update gerrit and have all the settings
        if relation_ids('gerrit-configurator'):
            admin_username = relation_get('admin_username')
            admin_email = relation_get('admin_email')
            if admin_username and admin_email:
                gerrit.update_gerrit()
            else:
                # error
                log('Not updating gerrit until we have relation settings.')
                return False

        jjb.update_jenkins()

        # check if we have zuul relationship
        if relation_ids('zuul-configurator'):
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
