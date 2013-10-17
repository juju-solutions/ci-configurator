import os
import pwd

from subprocess import check_output
from charmhelpers.core.hookenv import log


def public_ssh_key(user='root', ssh_dir=None):
    _ssh_dir = ssh_dir or os.path.join(pwd.getpwnam(user).pw_dir, '.ssh')
    try:
        with open(os.path.join(_ssh_dir, 'id_rsa.pub')) as key:
            return key.read().strip()
    except:
        return None


def initialize_ssh_keys(user='root', ssh_dir=None):
    home_dir = pwd.getpwnam(user).pw_dir
    out_dir = ssh_dir or os.path.join(home_dir, '.ssh')
    if not os.path.isdir(out_dir):
        os.mkdir(out_dir)

    priv_key = os.path.join(out_dir, 'id_rsa')
    if not os.path.isfile(priv_key):
        log('Generating new ssh key for user %s.' % user)
        cmd = ['ssh-keygen', '-q', '-N', '', '-t', 'rsa', '-b', '2048',
               '-f', priv_key]
        check_output(cmd)

    pub_key = '%s.pub' % priv_key
    if not os.path.isfile(pub_key):
        log('Generating missing ssh public key @ %s.' % pub_key)
        cmd = ['ssh-keygen', '-y', '-f', priv_key]
        p = check_output(cmd).strip()
        with open(pub_key, 'wb') as out:
            out.write(p)
    check_output(['chown', '-R', user, out_dir])
