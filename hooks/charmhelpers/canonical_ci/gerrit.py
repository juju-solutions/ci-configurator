import logging
import os
import paramiko
import sys
import subprocess

from charmhelpers.core.hookenv import (
    log as _log,
    ERROR,
)

_connection = None
GERRIT_DAEMON = "/etc/init.d/gerrit"

logging.basicConfig(level=logging.INFO)


def log(msg, level=None):
    # wrap log calls and distribute to correct logger
    # depending if this code is being run by a hook
    # or an external script.
    if os.getenv('JUJU_AGENT_SOCKET'):
        _log(msg, level=level)
    else:
        logging.info(msg)


def get_ssh(host, user, port, key_file):
    global _connection
    if _connection:
        return _connection

    _connection = paramiko.SSHClient()
    _connection.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    _connection.connect(host, username=user, port=port, key_filename=key_file)

    return _connection


# start gerrit application
def start_gerrit():
    try:
        subprocess.check_call([GERRIT_DAEMON, "start"])
    except:
        pass


# stop gerrit application
def stop_gerrit():
    try:
        subprocess.check_call([GERRIT_DAEMON, "stop"])
    except:
        pass


class GerritException(Exception):
    def __init__(self, msg):
        log('Failed to execute gerrit command: %s' % msg)
        super(GerritException, self).__init__(msg)


class GerritClient(object):
    def __init__(self, host, user, port, key_file):
        self.ssh = get_ssh(host, user, port, key_file)

    def _run_cmd(self, cmd):
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        return (stdout.read(), stderr.read())

    def create_user(self, user, name, group, ssh_key):
        log('Creating gerrit new user %s in group %s.' % (user, group))
        cmd = ('gerrit create-account %(user)s --full-name "%(name)s" '
               '--group "%(group)s" --ssh-key '
               '"%(ssh_key)s"' % locals())
        stdout, stderr = self._run_cmd(cmd)
        if not stdout and not stderr:
            log('Created new gerrit user %s in group %s.' % (user, group))

        if stderr.startswith('fatal'):
            if 'already exists' in stderr:
                # account can exist, we just need to update it
                log('Gerrit user %s already exists in group %s, updating it.' %
                    (user, group))

                # update name
                cmd = ('gerrit set-account %(user)s --full-name "%s(name)s" ' %
                       locals())
                stdout, stderr = self._run_cmd(cmd)

                # remove old keys and add new
                cmd = ('gerrit set-account %(user)s --delete-ssh-key ALL ' %
                       locals())
                stdout, stderr = self._run_cmd(cmd)
                cmd = ('gerrit set-account %(user)s --add-ssh-key '
                       '"%s(ssh_key)s" ' % locals())
                stdout, stderr = self._run_cmd(cmd)
            else:
                # different error
                log('Error creating account', ERROR)
                sys.exit(1)

        # reboot gerrit to refresh accounts
        stop_gerrit()
        start_gerrit()

    def create_users_batch(self, group, users):
        for user in users:
            # sets container user, name, ssh, openid
            login = user[0]
            name = user[1]
            email = user[2]
            ssh = user[3]
            openid = user[4]

            cmd = (u'gerrit create-account %s --full-name "%s" '
                   u'--group "%s" --email "%s"' % 
                   (login, name, group, email))
            stdout, stderr = self._run_cmd(cmd)

            if stderr.startswith('fatal'):
                if 'already exists' in stderr:
                    # account can exist, we just need to update it
                    cmd = (u'gerrit set-account %s --full-name "%s" '
                           u'--email "%s"' % (login, name, email))
                    stdout, stderr = self._run_cmd(cmd)
                else:
                    # different error
                    sys.exit(1)

            # remove old keys and add new
            cmd = ('gerrit set-account %s --delete-ssh-key ALL' %
                   login)
            stdout, stderr = self._run_cmd(cmd)
            for ssh_key in ssh:
                cmd = ('gerrit set-account %s --add-ssh-key %s' %
                       (login, ssh))
                stdout, stderr = self._run_cmd(cmd)

            # retrieve user id
            account_id = None  
            cmd = ('gerrit gsql --format json -c "SELECT account_id '
                'FROM account_external_ids WHERE external_id=\'username:%s\'"'
                % (login))
            stdout, stderr = self._run_cmd(cmd)
            if not stderr:
                # load and decode json, extract account id
                lines = stdout.splitlines()
                if len(lines)>0:
                    res = json.loads(lines[0])
                    try:
                        account_id = res['columns']['account_id']
                    except:
                        pass
            if account_id:
                # replace external id
                cmd = ('gerrit gsql -c "DELETE FROM account_external_ids '
                       'WHERE account_id=%s AND external_id LIKE \'http%%\'"'
                       % account_id)
                stdout, stderr = self._run_cmd(cmd)

                # replace launchpad for ubuntu account
                openid = openid.replace('login.launchpad.net', 'login.ubuntu.com')
                cmd = ('gerrit gsql -c "INSERT INTO account_external_ids '
                       '(account_id, email_address, external_id) VALUES '
                       '(%s, \'%s\', \'%s\')"' % (account_id, email, openid))
                stdout, stderr = self._run_cmd(cmd)

        sys.exit(0)

    def create_project(self, project):
        log('Creating gerrit project %s' % project)
        cmd = ('gerrit create-project %s' % project)
        stdout, stderr = self._run_cmd(cmd)
        if not stdout and not stderr:
            log('Created new project %s.' % project)
            return True
        else:
            log('Error creating project %s, skipping project creation' %
                project)
            return False

    def create_group(self, group):
        log('Creating gerrit group %s' % group)
        cmd = ('gerrit create-group %s' % group)
        stdout, stderr = self._run_cmd(cmd)
        if not stdout and not stderr:
            log('Created new group %s.' % group)

    def flush_cache(self):
        cmd = ('gerrit flush-caches')
        stdout, stderr = self._run_cmd(cmd)
