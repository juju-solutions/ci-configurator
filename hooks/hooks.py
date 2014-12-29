#!/usr/bin/python

import os
import sys

import common
import gerrit
import jjb
import zuul

from utils import (
    is_ci_configured,
    is_valid_config_repo,
)

from charmhelpers.fetch import apt_install, filter_installed_packages
from charmhelpers.canonical_ci import cron
from charmhelpers.core.hookenv import (
    charm_dir,
    config,
    log,
    DEBUG,
    INFO,
    relation_ids,
    related_units,
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
    apt_install(filter_installed_packages(common.PACKAGES), fatal=True)


def run_relation_hooks():
    """Run relation hooks (if relations exist) to ensure that configs are
    updated/accurate.
    """
    for rid in relation_ids('jenkins-configurator'):
        if related_units(relid=rid):
            log("Running jenkins-configurator-changed hook", level=DEBUG)
            jenkins_configurator_relation_changed(rid=rid)

    for rid in relation_ids('gerrit-configurator'):
        if related_units(relid=rid):
            log("Running gerrit-configurator-changed hook", level=DEBUG)
            gerrit_configurator_relation_changed(rid=rid)

    for rid in relation_ids('zuul-configurator'):
        if related_units(relid=rid):
            log("Running zuul-configurator-changed hook", level=DEBUG)
            zuul_configurator_relation_changed(rid=rid)


@hooks.hook()
def config_changed():
    # setup identity to reach private LP resources
    common.ensure_user()
    common.install_ssh_keys()

    lp_user = config('lp-login')
    if lp_user:
        cmd = ['bzr', 'launchpad-login', lp_user]
        common.run_as_user(cmd=cmd, user=common.CI_USER)

    # NOTE: this will overwrite existing configs so relation hooks will have to
    # re-run in order for settings to be re-applied.
    bundled_repo = os.path.join(charm_dir(), common.LOCAL_CONFIG_REPO)
    conf_repo = config('config-repo')
    if os.path.exists(bundled_repo) and os.path.isdir(bundled_repo):
        common.update_configs_from_charm(bundled_repo)
        run_relation_hooks()
    elif is_valid_config_repo(conf_repo):
        common.update_configs_from_repo(conf_repo,
                                        config('config-repo-revision'))
        run_relation_hooks()

    if config('schedule-updates'):
        schedule = config('update-frequency')
        cron.schedule_repo_updates(
            schedule, common.CI_USER, common.CI_CONFIG_DIR,
            jjb.JOBS_CONFIG_DIR)


@hooks.hook()
def upgrade_charm():
    config_changed()


@hooks.hook()
def jenkins_configurator_relation_joined(rid=None):
    """Install jenkins job builder.

    Also inform jenkins of any plugins our tests may require, as defined in
    the control.yml of the config repo.
    """
    jjb.install()
    plugins = jjb.required_plugins()
    if plugins:
        relation_set(relation_id=rid, required_plugins=' '.join(plugins))


@hooks.hook('jenkins-configurator-relation-changed')
def jenkins_configurator_relation_changed(rid=None):
    """Update/configure Jenkins installation.

    Also ensures that JJB and any required plugins are installed.
    """
    # Ensure jjb and any available plugins are installed before attempting
    # update.
    jenkins_configurator_relation_joined(rid=rid)

    if is_ci_configured():
        if os.path.isdir(jjb.CONFIG_DIR):
            jjb.update_jenkins()
        else:
            log("jjb not installed - skipping update", level=INFO)
    else:
        log('CI not yet configured - skipping jenkins update', level=INFO)


@hooks.hook('gerrit-configurator-relation-changed')
def gerrit_configurator_relation_changed(rid=None):
    """Update/configure Gerrit installation."""
    if is_ci_configured():
        gerrit.update_gerrit()
    else:
        log('CI not yet configured - skipping gerrit update', level=INFO)


@hooks.hook('zuul-configurator-relation-changed')
def zuul_configurator_relation_changed(rid=None):
    """Update/configure Zuul installation."""
    if is_ci_configured():
        zuul.update_zuul()
    else:
        log('CI not yet configured - skipping zuul update', level=INFO)


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))


if __name__ == '__main__':
    main()
