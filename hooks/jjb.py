import json
import os
import shutil
import subprocess

import common

from charmhelpers.core.hookenv import (
    charm_dir, config, log, relation_ids, relation_get,
    related_units, ERROR)
from charmhelpers.canonical_ci.jenkins import (
    start_jenkins, stop_jenkins)
from charmhelpers.fetch import apt_install

PACKAGES = ['git', 'python-pip']
CONFIG_DIR = '/etc/jenkins_jobs'
JJB_CONFIG = os.path.join(CONFIG_DIR, 'jenkins_jobs.ini')

JENKINS_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'jenkins')
JOBS_CONFIG_DIR = os.path.join(JENKINS_CONFIG_DIR, 'jobs')
CHARM_CONTEXT_DUMP = os.path.join(common.CI_CONFIG_DIR, 'charm_context.json')

JENKINS_SECURITY_FILE = os.path.join(JENKINS_CONFIG_DIR,
                                     'security', 'config.xml')
JENKINS_CONFIG_FILE = '/var/lib/jenkins/config.xml'

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
    admin_user, admin_cred = admin_credentials()
    for rid in relation_ids('jenkins-configurator'):
        for unit in related_units(rid):
            jenkins = {
                'jenkins_url': relation_get('jenkins_url', rid=rid, unit=unit),
                'username': admin_user,
                'password': admin_cred,
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


def admin_credentials():
    """fetches admin credentials either from charm config or remote jenkins
    service"""

    admin_user = config('jenkins-admin-user')
    admin_cred = config('jenkins-token')
    if (admin_user and admin_cred) and '' not in [admin_user, admin_cred]:
        log('Configurating Jenkins credentials from charm configuration.')
        return admin_user, admin_cred

    for rid in relation_ids('jenkins-configurator'):
        admin_user = None
        admin_cred = None
        for unit in related_units(rid):
            admin_user = relation_get('admin_username', rid=rid, unit=unit)
            admin_cred = relation_get('admin_password', rid=rid, unit=unit)
            if (admin_user and admin_cred) and \
               '' not in [admin_user, admin_cred]:
                log('Configuring Jenkins credentials from Jenkins relation.')
                return (admin_user, admin_cred)

    return (None, None)


def update_jenkins_config():
    # NOTE (adam_g): This totally overwrites the entire Jenkins configuration
    #                file, just to set security policy?  It would be preferred
    #                if we can find a way to update config instead of
    #                replacing.
    # copy file to jenkins home path
    if not os.path.isdir(JOBS_CONFIG_DIR):
        log('Could not find jobs-config directory at expected location, '
            'skipping jenkins-jobs update (%s)' % JOBS_CONFIG_DIR, ERROR)
        return

    log('Updating jenkins config @ %s' % JENKINS_CONFIG_FILE)
    if not os.path.isfile(JENKINS_SECURITY_FILE):
        log('Could not find jenkins config file @ %s, skipping.' %
            JENKINS_SECURITY_FILE)
        return

    # copy file to jenkins home path
    shutil.copy(JENKINS_SECURITY_FILE, JENKINS_CONFIG_FILE)
    cmd = ['chown', 'jenkins:nogroup', JENKINS_CONFIG_FILE]
    subprocess.check_call(cmd)
    os.chmod(JENKINS_CONFIG_FILE, 0644)

    # NOTE (adam_g): We do not want to restart jenkins unless we absolutely
    #                need to.
    #                TODO: md5 sum the config file before update and only
    #                      restart jenkins if we need to.
    stop_jenkins()
    start_jenkins()


def update_jenkins_jobs():
    if not write_jjb_config():
        log('Could not write jenkins-job-builder config, skipping '
            'jobs update.')
        return
    if not os.path.isdir(JOBS_CONFIG_DIR):
        log('Could not find jobs-config directory at expected location, '
            'skipping jenkins-jobs update (%s)' % JOBS_CONFIG_DIR, ERROR)
        return

    hook = os.path.join(JOBS_CONFIG_DIR, 'update')
    if not os.path.isfile(hook):
        log('Could not find jobs-config update hook at expected location: %s' %
            hook, ERROR)
        return

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
    # Run as the CI_USER so the cache will be primed with the correct
    # permissions (rather than root:root).
    common.run_as_user(cmd=cmd, user=common.CI_USER)


def update_jenkins():
    if not relation_ids('jenkins-configurator'):
        return
    log("*** Updating jenkins.")

    update_jenkins_config()
    update_jenkins_jobs()

    # run repo setup scripts.
    setupd = os.path.join(common.CI_CONFIG_DIR, 'setup.d')
    if os.path.isdir(setupd):
        cmd = ["run-parts", setupd]
        log('Running repo setup.')
        subprocess.check_call(cmd)

    # install any packages that the repo says we need as dependencies.
    pkgs = required_packages()
    if pkgs:
        apt_install(pkgs, fatal=True)


def required_packages():
    control = common.load_control()
    if control and 'required_jenkins_packages' in control:
        return control['required_jenkins_packages']


def required_plugins():
    control = common.load_control()
    if control and 'required_jenkins_plugins' in control:
        return control['required_jenkins_plugins']
