#!/usr/bin/python
import os
import shutil
import subprocess

from charmhelpers.core.hookenv import charm_dir, log

PACKAGES= ['git']
TARBALL = 'jenkins-job-builder.tar.gz'
LOCAL_DEPS = 'jenkins-job-builder_reqs'


def install_from_git(src):
    # assumes internet access.
    log('*** Installing jenkins-job-builder from remote git: %s.' % src)

    outdir = os.path.join('/tmp', 'jenkins-job-builder')
    if os.path.exists(outdir):
        if os.path.isfile(outdir):
            os.unlink(outdir)
        elif os.path.isdir(outdir):
            shutil.rmtree(outdir)

    cmd = ['git', 'clone', src, outdir]
    subprocess.check_call(cmd)
    os.chdir(outdir)
    cmd = ['python', 'setup.py', 'install']
    subprocess.check_call(cmd)
    log('*** Installed jenkins-job-builder from remote git: %s.' % src)


def install_from_file(tarball):
    # does not hit the internet. assumes assets packaged with charm.
    outdir = os.path.join('/tmp', 'jenkins-job-builder')
    if os.path.exists(outdir):
        if os.path.isfile(outdir):
            os.unlink(outdir)
        elif os.path.isdir(outdir):
            shutil.rmtree(outdir)

    os.chdir(os.path.dirname(outdir))
    cmd = ['tar', 'xfz', tarball]
    subprocess.check_call(cmd)

    requires = os.path.join(charm_dir(), 'files', LOCAL_DEPS)
    os.chdir(outdir)
    cmd = ['pip', 'install', '--no-index',
           '--find-links=file://%s' % requires, '-r', 'tools/pip-requires']
