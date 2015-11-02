import os
import pwd
import shutil
import subprocess
import yaml

from charmhelpers.core.host import adduser, add_user_to_group
from charmhelpers.core.hookenv import charm_dir, config, log, ERROR

PACKAGES = [
    'bzr'
]

CI_USER = 'ci'
CI_GROUP = 'ci'

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
    subprocess.check_call(['chown', '-R', CI_USER, CONFIG_DIR])


def update_configs_from_bzr_repo(repo, revision=None):
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
        run_as_user(cmd=cmd, user=CI_USER)
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
        [run_as_user(cmd=c, user=CI_USER, cwd=CI_CONFIG_DIR) for c in cmds]


def update_configs_from_git_repo(repo, revision=None):
    if (os.path.isdir(CI_CONFIG_DIR) and
            not os.path.isdir(os.path.join(CI_CONFIG_DIR, '.git'))):
        log('%s exists but appears not to be a git repo, removing.' %
            CI_CONFIG_DIR)
        shutil.rmtree(CI_CONFIG_DIR)

    if not os.path.exists(CI_CONFIG_DIR):
        log('Cloning {}.'.format(repo))
        cmd = ['git', 'clone', repo, CI_CONFIG_DIR]
        run_as_user(cmd=cmd, user=CI_USER)
    else:
        log('Fetching all remotes in {}'.format(CI_CONFIG_DIR))
        run_as_user(cmd=['git', 'fetch', '--all'], user=CI_USER,
                    cwd=CI_CONFIG_DIR)

    if not revision or revision == 'trunk':
        revision = 'master'
    try:
        git_sha = run_as_user(cmd=['git', 'rev-parse', revision], user=CI_USER,
                              cwd=CI_CONFIG_DIR).strip()
    except subprocess.CalledProcessError:
        git_sha = run_as_user(
            cmd=['git', 'rev-parse', 'origin/{}'.format(revision)],
            user=CI_USER, cwd=CI_CONFIG_DIR).strip()
    log('Resetting {} to {}'.format(CI_CONFIG_DIR, git_sha))
    run_as_user(cmd=['git', 'reset', '--hard', git_sha], user=CI_USER,
                cwd=CI_CONFIG_DIR)


def update_configs_from_repo(repo_rcs, repo, revision=None):
    log('*** Updating %s from remote repo: %s' %
        (CI_CONFIG_DIR, repo))
    subprocess.check_call(['chown', '-R', CI_USER, CONFIG_DIR])

    repo_funcs = {
        'bzr': update_configs_from_bzr_repo,
        'git': update_configs_from_git_repo,
    }
    return repo_funcs[repo_rcs](repo, revision)


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


def ensure_user():
    adduser(CI_USER)
    add_user_to_group(CI_USER, CI_GROUP)
    home = os.path.join('/home', CI_USER)
    if not os.path.isdir(home):
        os.mkdir(home)
    subprocess.check_call(
        ['chown', '-R', '%s:%s' % (CI_USER, CI_GROUP), home])


def install_ssh_keys():
    '''Installs configured ssh keys + known hosts for accessing lp branches'''
    priv_key = config('ssh-privkey')
    pub_key = config('ssh-pubkey')
    if not priv_key or not pub_key:
        log('Missing SSH keys in charm config, will not install.')
        return

    ssh_dir = os.path.join('/home', CI_USER, '.ssh')
    if not os.path.isdir(ssh_dir):
        os.mkdir(ssh_dir)

    _priv_key = os.path.join(ssh_dir, 'id_rsa')
    _pub_key = os.path.join(ssh_dir, 'id_rsa.pub')
    with open(_priv_key, 'wb') as out:
        out.write(priv_key)
    with open(_pub_key, 'wb') as out:
        out.write(pub_key)

    # ssh keys are used to branch from LP. install bazaar.launchpad.net's
    # host keys, as well.
    lp_kh = os.path.join(charm_dir(), 'launchpad_host_keys')
    if lp_kh:
        with open(os.path.join(ssh_dir, 'known_hosts'), 'wb') as out:
            out.write(open(lp_kh).read())

    subprocess.check_call(['chmod', '0600', _priv_key])
    subprocess.check_call(['chown', '-R', CI_USER, ssh_dir])

    log('*** Installed ssh keys for user %s to %s' % (CI_USER, ssh_dir))
