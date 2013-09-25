#!/usr/bin/python

import os
import sys
import jjb_utils as jjb

from charmhelpers.core.hookenv import (
    charm_dir,
    config,
    log,
    Hooks,
    UnregisteredHookError,
    ERROR,
)

from charmhelpers.fetch import apt_install


hooks = Hooks()


@hooks.hook()
def install():
    if not os.path.isdir(jjb.CONFIG_DIR):
        os.mkdir(jjb.CONFIG_DIR)
    apt_install(jjb.PACKAGES, fatal=True)
    src = config('install-source')
    tarball = os.path.join(charm_dir(), 'files', jjb.TARBALL)

    if os.path.isfile(tarball):
        log('Installing jenkins-job-builder from bundled file: %s.' % tarball)
        jjb.install_from_file(tarball)
    elif src.startswith('git://'):
        log('Installing jenkins-job-builder from remote git: %s.' % src)
        jjb.install_from_git(src)
    else:
        m = ('Must specify a git url as install source or bundled source with '
             'the charm.')
        log(m, ERROR)
        raise Exception(m)


@hooks.hook()
def config_changed():
    dep_packages = config('required-packages').split(' ')
    if dep_packages:
        log('Installing packages as specified in config: %s.' % dep_packages)
        apt_install(dep_packages)
    conf_repo = config('jobs-config-repo')
    bundled_configs = os.path.join(charm_dir(), jjb.LOCAL_JOBS_CONFIG)
    if os.path.exists(bundled_configs) and os.path.isdir(bundled_configs):
        jjb.update_configs_from_charm(bundled_configs)
    elif conf_repo and (conf_repo.startswith('lp:')
                        or conf_repo.startswith('bzr')):
        jjb.update_configs_from_repo(conf_repo, config('job-config-revision'))
    jjb.update_jenkins()


@hooks.hook()
def upgrade_charm():
    config_changed()


@hooks.hook()
def jenkins_job_builder_relation_changed():
    config_changed()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))


if __name__ == '__main__':
    main()
