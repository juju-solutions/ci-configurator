import os
import pwd
import shutil
import subprocess
import yaml

from charmhelpers.core.hookenv import log, ERROR

LOCAL_CONFIG_REPO = 'ci-config-repo'
CONFIG_DIR = '/etc/ci-configurator'
# /etc/ci-configurator/ci-config/ is where the repository
# ends up.  This is either a bzr repo of the remote source
# or a copy of the repo shipped with charm, depending on config.
CI_CONFIG_DIR = os.path.join(CONFIG_DIR, 'ci-config')
CI_CONTROL_FILE = os.path.join(CI_CONFIG_DIR, 'control.yml')


def update_configs_from_charm(bundled_configs):
    log('*** Updating %s from local configs dir: %s' %
        (CI_CONFIG_DIR, bundled_configs))
    if os.path.exists(CI_CONFIG_DIR):
        shutil.rmtree(CI_CONFIG_DIR)
    shutil.copytree(bundled_configs, CI_CONFIG_DIR)


def update_configs_from_repo(repo, revision=None):
    log('*** Updating %s from remote repo: %s' %
        (CI_CONFIG_DIR, repo))

    if (os.path.isdir(CI_CONFIG_DIR) and
       not os.path.isdir(os.path.join(CI_CONFIG_DIR, '.bzr'))):
        log('%s exists but appears not to be a bzr repo, removing.' %
            CI_CONFIG_DIR)
        shutil.rmtree(CI_CONFIG_DIR)

    if not os.path.exists(CI_CONFIG_DIR):
        log('Branching new checkout of %s.' % repo)
        cmd = ['bzr', 'branch', repo, CI_CONFIG_DIR]
        if revision and revision != 'trunk':
            cmd += ['-r', revision]
        subprocess.check_call(cmd)
        return

    cmds = []
    cmds.append(['bzr', 'revert'])
    if revision == 'trunk':
        log('Ensuring %s is up to date with trunk.' % CI_CONFIG_DIR)
        cmds.append(['bzr', 'revert'])
        cmds.append(['bzr', 'pull'])
    elif revision:
        log('Ensuring %s is on revision %s.' % (CI_CONFIG_DIR, revision))
        cmds.append(['bzr', 'update', '-r', revision])

    if cmds:
        os.chdir(CI_CONFIG_DIR)
        log('Running bzr: %s' % cmds)
        [subprocess.check_call(c) for c in cmds]


def load_control():
    if not os.path.exists(CI_CONTROL_FILE):
        log('No control.yml found in repo at @ %s.' % CI_CONTROL_FILE)
        return None

    with open(CI_CONTROL_FILE) as control:
        return yaml.load(control)


def sync_dir(src, dst):
    """Copies all files and directories to a destination directory.  If
    copy destination already exists, it will be removed and re-copied.
    """
    for path in os.listdir(src):
        _path = os.path.join(src, path)
        if os.path.isdir(_path):
            dest_dir = os.path.join(dst, path)
            if os.path.isdir(dest_dir):
                shutil.rmtree(dest_dir)
            shutil.copytree(_path, dest_dir)
        else:
            shutil.copy(_path, dst)


def _run_as_user(user):
    try:
        user = pwd.getpwnam(user)
    except KeyError:
        log('Invalid user: %s' % user, ERROR)
        raise Exception('Invalid user: %s' % user)
    uid, gid = user.pw_uid, user.pw_gid
    os.environ['HOME'] = user.pw_dir

    def _inner():
        os.setgid(gid)
        os.setuid(uid)
    return _inner


def run_as_user(user, cmd, cwd='/'):
    return subprocess.check_output(cmd, preexec_fn=_run_as_user(user), cwd=cwd)
