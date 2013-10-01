import json
import os
import shutil
import subprocess
import sys

import common

from charmhelpers.core.hookenv import (
    charm_dir, config, log, relation_ids, relation_get, related_units, ERROR)
from charmhelpers.fetch import apt_install

PACKAGES = ['git', 'python-pip']
CONFIG_DIR = '/etc/jenkins_jobs'
JJB_CONFIG = os.path.join(CONFIG_DIR, 'jenkins_jobs.ini')

JOBS_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'jenkins_jobs')
CHARM_CONTEXT_DUMP = os.path.join(common.CI_CONFIG_DIR, 'charm_context.json')

# locaiton of various assets Makefile target creates.
TARBALL = 'jenkins-job-builder.tar.gz'
LOCAL_PIP_DEPS = 'jenkins-job-builder_reqs'
LOCAL_JOBS_CONFIG = 'job-configs'

JJB_CONFIG_TEMPLATE = """
[jenkins]
user=%(username)s
password=%(password)s
url=%(jenkins_url)s
"""


def install():
    """
    Install jenkins-job-builder from a remote git repository or a locally
    bundled copy shipped with the charm.
    """
    if not os.path.isdir(CONFIG_DIR):
        os.mkdir(CONFIG_DIR)
    apt_install(PACKAGES, fatal=True)
    src = config('jjb-install-source')
    tarball = os.path.join(charm_dir(), 'files', TARBALL)

    if os.path.isfile(tarball):
        log('Installing jenkins-job-builder from bundled file: %s.' % tarball)
        install_from_file(tarball)
    elif src.startswith('git://'):
        log('Installing jenkins-job-builder from remote git: %s.' % src)
        install_from_git(src)
    else:
        m = ('Must specify a git url as install source or bundled source with '
             'the charm.')
        log(m, ERROR)
        raise Exception(m)


def _clean_tmp_dir(tmpdir):
    tmpdir = os.path.join('/tmp', 'jenkins-job-builder')
    if os.path.exists(tmpdir):
        if os.path.isfile(tmpdir):
            os.unlink(tmpdir)
        else:
            shutil.rmtree(tmpdir)


def install_from_file(tarball):
    log('*** Installing from local tarball: %s.' % tarball)
    outdir = os.path.join('/tmp', 'jenkins-job-builder')
    _clean_tmp_dir(outdir)

    os.chdir(os.path.dirname(outdir))
    cmd = ['tar', 'xfz', tarball]
    subprocess.check_call(cmd)
    os.chdir(outdir)
    deps = os.path.join(charm_dir(), 'files', LOCAL_PIP_DEPS)
    cmd = ['pip', 'install', '--no-index',
           '--find-links=file://%s' % deps, '-r', 'tools/pip-requires']
    subprocess.check_call(cmd)
    cmd = ['python', './setup.py', 'install']
    subprocess.check_call(cmd)
    log('*** Installed from local tarball.')


def install_from_git(repo):
    # assumes internet access
    log('*** Installing from remote git repository: %s' % repo)
    outdir = os.path.join('/tmp', 'jenkins-job-builder')
    _clean_tmp_dir(outdir)
    cmd = ['git', 'clone', repo, outdir]
    subprocess.check_call(cmd)
    os.chdir(outdir)
    cmd = ['python', 'setup.py', 'install']
    subprocess.check_call(cmd)


def write_jjb_config():
    log('*** Writing jenkins-job-builder config: %s.' % JJB_CONFIG)

    jenkins = {}
    for rid in relation_ids('jenkins-configurator'):
        for unit in related_units(rid):
            jenkins = {
                'jenkins_url': relation_get('jenkins_url', rid=rid, unit=unit),
                'username': relation_get('admin_username', rid=rid, unit=unit),
                'password': relation_get('admin_password', rid=rid, unit=unit),
            }

            if (None not in jenkins.itervalues() and
               '' not in jenkins.itervalues()):
                with open(JJB_CONFIG, 'wb') as out:
                    out.write(JJB_CONFIG_TEMPLATE % jenkins)
                log('*** Wrote jenkins-job-builder config: %s.' % JJB_CONFIG)
                return True

    log('*** Not enough data in principle relation. Not writing config.')
    return False


def jenkins_context():
    for rid in relation_ids('jenkins-configurator'):
        for unit in related_units(rid):
            return relation_get(rid=rid, unit=unit)


def config_context():
    ctxt = {}
    for k, v in config().iteritems():
        if k == 'misc-config':
            _misc = v.split(' ')
            for ms in _misc:
                if '=' in ms:
                    x, y = ms.split('=')
                    ctxt.update({x: y})
        else:
            ctxt.update({k: v})
    return ctxt


def save_context(outfile=CHARM_CONTEXT_DUMP):
    '''dumps principle relation context and config to a json file for
    use by jenkins-job-builder repo update hook'''
    log('Saving current charm context to %s.' % CHARM_CONTEXT_DUMP)
    ctxt = {}
    ctxt.update(jenkins_context())
    ctxt.update(config_context())
    with open(CHARM_CONTEXT_DUMP, 'w') as out:
        out.write(json.dumps(ctxt))


def update_jenkins():
    if not relation_ids('jenkins-configurator'):
        return

    log("*** Updating jenkins.")
    if not write_jjb_config():
        # not enough in relation state to write config, skip update for now.
        return

    if not os.path.isdir(JOBS_CONFIG_DIR):
        log('Could not find jobs-config directory at expected location, '
            'skipping jenkins-jobs update (%s)' % JOBS_CONFIG_DIR, ERROR)
        return

    hook = os.path.join(JOBS_CONFIG_DIR, 'update')
    if not os.path.isfile(hook):
        log('Could not find jobs-config update hook at expected location: %s' %
            hook, ERROR)
        sys.exit(1)

    # install any packages that the repo says we need as dependencies.
    pkgs = required_packages()
    if pkgs:
        apt_install(pkgs, fatal=True)

    # run repo setup scripts.
    setupd = os.path.join(common.CI_CONFIG_DIR, 'setup.d')
    if os.path.isdir(setupd):
        cmd = ["run-parts", setupd]
        log('Running repo setup.')
        subprocess.check_call(cmd)

    save_context()
    # inform hook where to find the context json dump
    os.environ['JJB_CHARM_CONTEXT'] = CHARM_CONTEXT_DUMP
    os.environ['JJB_JOBS_CONFIG_DIR'] = JOBS_CONFIG_DIR
    log('Calling jenkins-job-builder repo update hook: %s.' % hook)
    subprocess.check_call(hook)

    # call jenkins-jobs to actually update jenkins
    # TODO: Call 'jenkins-job test' to validate configs before updating?
    log('Updating jobs in jenkins.')
    cmd = ['jenkins-jobs', '--flush-cache', 'update', JOBS_CONFIG_DIR]
    subprocess.check_call(cmd)


def required_packages():
    control = common.load_control()
    if control and 'required_jenkins_packages' in control:
        return control['required_jenkins_packages']


def required_plugins():
    control = common.load_control()
    if control and 'required_jenkins_plugins' in control:
        return control['required_jenkins_plugins']
