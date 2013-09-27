import paramiko
import sys

import gerrit_utils as gerrit

from charmhelpers.core.hookenv import log, ERROR


_connection = None


def get_ssh(host, user, port, key_file):
    global _connection
    if _connection:
        return _connection

    _connection = paramiko.SSHClient()
    _connection.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    _connection.connect(host, username=user, port=port, key_filename=key_file)

    return _connection


class GerritException(Exception):
    def __init__(self, msg):
        log('Failed to execute gerrit command: %s' % msg)
        super(GerritException, self).__init__(msg)


class GerritClient(object):
    def __init__(self, host, user, port, key_file):
        self.ssh = get_ssh(host, user, port, key_file)

    def _run_cmd(self, cmd):
        log('Executing gerrit command: %s' % cmd)
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
        gerrit.stop_gerrit()
        gerrit.start_gerrit()

    def create_project(self, project):
        log('Creating gerrit project %s' % project)
        cmd = ('gerrit create-project %s' % project)
        stdout, stderr = self._run_cmd(cmd)
        if not stdout and not stderr:
            log('Created new project %s.' % project)

    def flush_cache(self):
        cmd = ('gerrit flush-caches')
        stdout, stderr = self._run_cmd(cmd)