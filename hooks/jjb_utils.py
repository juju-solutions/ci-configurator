import json
import os
import shutil
import subprocess
import sys

from charmhelpers.core.hookenv import (
    charm_dir, config, log, relation_ids, relation_get, related_units, ERROR)

PACKAGES = ['git', 'python-pip']
CONFIG_DIR = '/etc/jenkins_jobs'
JJB_CONFIG = os.path.join(CONFIG_DIR, 'jenkins_jobs.ini')
JOBS_CONFIG_DIR = os.path.join(CONFIG_DIR, 'jobs-config')
CHARM_CONTEXT_DUMP = os.path.join(CONFIG_DIR, 'charm_context.json')

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


def update_configs_from_charm(bundled_configs):
    log('*** Updating %s from local configs dir: %s' %
        (JOBS_CONFIG_DIR, bundled_configs))
    if os.path.exists(JOBS_CONFIG_DIR):
        shutil.rmtree(JOBS_CONFIG_DIR)
    shutil.copytree(bundled_configs, JOBS_CONFIG_DIR)


def update_configs_from_repo(repo, revision=None):
    log('*** Updating %s from remote repo: %s' %
        (JOBS_CONFIG_DIR, repo))

    if (os.path.isdir(JOBS_CONFIG_DIR) and
       not os.path.isdir(os.path.join(JOBS_CONFIG_DIR, '.bzr'))):
        shutil.rmtree(JOBS_CONFIG_DIR)

    if not os.path.exists(JOBS_CONFIG_DIR):
        cmd = ['bzr', 'branch', repo]
        if revision and revision != 'trunk':
            cmd += ['-r', revision]
        subprocess.check_call(cmd)
        return

    cmds = []
    if revision == 'trunk':
        log('Ensuring %s is up to date.' % JOBS_CONFIG_DIR)
        cmds.append(['bzr', 'revert'])
        cmds.append(['bzr', 'pull'])
    elif revision:
        log('Ensuring %s is on revision %s.' % (JOBS_CONFIG_DIR, revision))
        cmds.append(['bzr', 'update', '-r', revision])

    if cmds:
        os.chdir(JOBS_CONFIG_DIR)
        log('Running bzr: cmds')
        [subprocess.check_call(c) for c in cmds]


def write_jjb_config():
    log('*** Writing jenkins-job-builder config: %s.' % JJB_CONFIG)

    jenkins = {}
    for rid in relation_ids('jenkins-job-builder'):
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
    for rid in relation_ids('jenkins-job-builder'):
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
    if not write_jjb_config():
        # not enough in relation state to write config, skip update for now.
        return

    if not os.path.isdir(JOBS_CONFIG_DIR):
        log('Could not find jobs-config directory at expected location: %s.' %
            JOBS_CONFIG_DIR, ERROR)
        sys.exit(1)

    hook = os.path.join(JOBS_CONFIG_DIR, 'update')
    if not os.path.isfile(hook):
        log('Could not find jobs-config update hook at expected location: %s' %
            hook, ERROR)
        sys.exit(1)

    save_context()
    # inform hook where to find the context json dump
    os.environ['JJB_CHARM_CONTEXT'] = CHARM_CONTEXT_DUMP
    os.environ['JJB_JOBS_CONFIG_DIR'] = JOBS_CONFIG_DIR
    log('Calling jenkins-job-builder update hook: %s.' % hook)
    subprocess.check_call(hook)
