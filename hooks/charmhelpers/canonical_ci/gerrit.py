import logging
import os
import paramiko
import sys
import subprocess
import json

from charmhelpers.core.hookenv import (
    log as _log,
    INFO,
    WARNING,
    ERROR
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
        _, stdout, stderr = self.ssh.exec_command(cmd)
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
            if 'already exists' not in stderr:
                # different error
                log('Error creating account', ERROR)
                sys.exit(1)
            else:
                # retrieve user id and update keys
                account_id = None
                sql = ("SELECT account_id FROM account_external_ids WHERE "
                       "external_id='username:%s'" % (user))
                cmd = ('gerrit gsql --format json -c "%s"' % (sql))
                stdout, stderr = self._run_cmd(cmd)
                if not stderr:
                    # load and decode json, extract account id
                    lines = stdout.splitlines()
                    if len(lines) > 0:
                        res = json.loads(lines[0])
                        try:
                            account_id = res['columns']['account_id']
                        except:
                            pass

                # if found, update ssh keys
                if account_id:
                    sql = ("DELETE FROM account_ssh_keys WHERE account_id=%s"
                           % account_id)
                    cmd = ('gerrit gsql -c "%s"' % (sql))
                    stdout, stderr = self._run_cmd(cmd)

                    # insert new key
                    sql = ("INSERT INTO account_ssh_keys (ssh_public_key, "
                           "valid, account_id, seq) VALUES ('%s', 'Y', "
                           "'%s', 0)" % (ssh_key, account_id))
                    cmd = ('gerrit gsql -c "%s"' % (sql))
                    stdout, stderr = self._run_cmd(cmd)

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
                if 'already exists' not in stderr:
                    sys.exit(1)

            # retrieve user id
            account_id = None
            sql = ("SELECT account_id FROM account_external_ids WHERE "
                   "external_id='username:%s'" % (login))
            cmd = ('gerrit gsql --format json -c "%s"' % (sql))
            stdout, stderr = self._run_cmd(cmd)
            if not stderr:
                # load and decode json, extract account id
                lines = stdout.splitlines()
                if len(lines) > 0:
                    res = json.loads(lines[0])
                    try:
                        account_id = res['columns']['account_id']
                    except:
                        pass

            # if found, update ssh keys and openid
            if account_id:
                # remove old keys and add new
                if len(ssh) > 0:
                    sql = ("DELETE FROM account_ssh_keys WHERE account_id=%s "
                           "AND ssh_public_key NOT IN (%s)" %
                           (account_id,
                            (', '.join("'%s'" % item for item in ssh))))
                    cmd = ('gerrit gsql -c "%s"' % (sql))
                else:
                    cmd = ('gerrit gsql -c "DELETE FROM account_ssh_keys '
                           'WHERE account_id=%s' % account_id)

                stdout, stderr = self._run_cmd(cmd)

                num_key = 0
                for ssh_key in ssh:
                    # insert new keys
                    sql = ("INSERT INTO account_ssh_keys (ssh_public_key, "
                           "valid, account_id, seq) SELECT %(ssh_key)s, "
                           "%(valid)s, %(account_id)s, %(num_key)s WHERE NOT "
                           "EXISTS (SELECT account_id FROM account_ssh_keys "
                           "WHERE account_id=%(account_id)s AND "
                           "ssh_public_key=%(ssh_key)s)" %
                           {'ssh_key': "'%s'" % ssh_key,
                            'valid': "'Y'",
                            'account_id': "'%s'" % account_id,
                            'num_key': num_key})
                    cmd = ('gerrit gsql -c "%s"' % (sql))
                    num_key += 1
                    stdout, stderr = self._run_cmd(cmd)

                # replace external id
                if openid:
                    openid = openid.replace('login.launchpad.net',
                                            'login.ubuntu.com')
                    sql = ("DELETE FROM account_external_ids WHERE "
                           "account_id=%s AND external_id NOT IN (%s) AND "
                           "external_id LIKE 'http%%'" %
                           (account_id, "'%s'" % openid))
                    cmd = ('gerrit gsql -c "%s"' % (sql))
                    stdout, stderr = self._run_cmd(cmd)

                    # replace launchpad for ubuntu account
                    sql = ("INSERT INTO account_external_ids "
                           "(account_id, email_address, external_id) SELECT "
                           "%(account_id)s, %(email_address)s, "
                           "%(external_id)s WHERE NOT EXISTS (SELECT "
                           "account_id FROM account_external_ids WHERE "
                           "account_id=%(account_id)s AND "
                           "external_id=%(external_id)s)" %
                           {'account_id': "'%s'" % account_id,
                            'email_address': "'%s'" % str(email),
                            'external_id': "'%s'" % openid})
                    cmd = ('gerrit gsql -c "%s"' % (sql))
                    stdout, stderr = self._run_cmd(cmd)

    def create_project(self, project):
        """Create project in gerrit.

        This will create create an empty git repository at gerrit.basePath and
        will also update the gerrit db with an entry for this repo.

        If the command fails because the repository already exists, we allow
        the operation to succeed but we log a WARNING.

        Returns True if the operation succeeded, otherwise False.
        """
        log('Creating gerrit project %s' % project)

        cmd = ('gerrit create-project %s' % project)
        stdout, stderr = self._run_cmd(cmd)
        if stderr:
            stderr = stderr.strip()
            if stderr != 'fatal: project "%s" exists' % (project):
                msg = ("Failed to create project '%s' (stderr='%s')." %
                       (project, stderr))
                log(msg, level=ERROR)
                return False
            else:
                msg = ("Project '%s' already exists." % project)
                log(msg, level=WARNING)
                return True

        log("Successfully created new project '%s'." % project, level=INFO)
        return True

    def create_group(self, group):
        """Create group in gerrit.

        If the command fails because the group already exists, we allow the
        operation to succeed but we log a WARNING.

        Returns True if the operation succeeded, otherwise False.
        """

        log('Creating gerrit group %s' % group)
        cmd = ('gerrit create-group %s' % group)
        stdout, stderr = self._run_cmd(cmd)
        if stderr:
            stderr = stderr.strip()
            if stderr != 'fatal: Name Already Used':
                msg = ("Failed to create group '%s' (stderr='%s')." %
                       (group, stderr))
                log(msg, level=ERROR)
                return
            else:
                msg = ("Group '%s' already exists." % group)
                log(msg, level=WARNING)
                return

        log("Successfully created new group '%s'." % group, level=INFO)

    def flush_cache(self):
        cmd = ('gerrit flush-caches')
        self._run_cmd(cmd)
