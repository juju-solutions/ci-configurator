
import os
import shutil
import subprocess


from charmhelpers.core.hookenv import charm_dir, log

PACKAGES = ['git', 'python-pip']
CONFIG_DIR = '/etc/jenkins_jobs'
JOBS_CONFIG_DIR = os.path.join(CONFIG_DIR, 'jobs-config')

# locaiton of various assets Makefile target creates.
TARBALL = 'jenkins-job-builder.tar.gz'
LOCAL_PIP_DEPS = 'jenkins-job-builder_reqs'
LOCAL_JOBS_CONFIG = 'job-configs'


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

    if (os.path.isdir(os.path.join(JOBS_CONFIG_DIR)) and
       not os.path.isdir(os.path.join(JOBS_CONFIG_DIR, '.bzr'))):
        shutil.rmtree(JOBS_CONFIG_DIR)

    if not os.path.exists(JOBS_CONFIG_DIR):
        cmd = ['bzr', 'branch', repo]
        if revision and revision != 'trunk':
            cmd += ['-r', revision]
        subprocess.check_call(cmd)
        return

    os.chdir(JOBS_CONFIG_DIR)
    if revision == 'trunk':
        log('Ensuring %s is up to date.' % JOBS_CONFIG_DIR)
        cmd = ['bzr', 'pull']
    else:
        log('Ensuring %s is on revision %s.' % (JOBS_CONFIG_DIR, revision))
        cmd = ['bzr', 'update', '-r', revision]
    subprocess.check_call(cmd)


def update_jenkins():
    print 'TODO: update_jenkins().'
