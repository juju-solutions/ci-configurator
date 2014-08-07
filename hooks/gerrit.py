from base64 import b64decode
import common
import os
import re
import subprocess
import sys
import shutil
import tempfile
import yaml

from charmhelpers.core.hookenv import (
    config,
    log,
    relation_ids,
    relation_get,
    related_units,
    unit_get,
    WARNING,
    INFO,
    ERROR
)
from charmhelpers.canonical_ci.gerrit import (
    GerritClient,
    start_gerrit,
    stop_gerrit
)
from charmhelpers.canonical_ci import cron
from jinja2 import Template

GERRIT_INIT_SCRIPT = '/etc/init.d/gerrit'
GERRIT_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'gerrit')
THEME_DIR = os.path.join(GERRIT_CONFIG_DIR, 'theme')
HOOKS_DIR = os.path.join(GERRIT_CONFIG_DIR, 'hooks')
PERMISSIONS_DIR = os.path.join(GERRIT_CONFIG_DIR, 'permissions')
PROJECTS_CONFIG_FILE = os.path.join(GERRIT_CONFIG_DIR, 'projects/projects.yml')
GROUPS_CONFIG_FILE = os.path.join(GERRIT_CONFIG_DIR, 'permissions/groups.yml')
GIT_PATH = os.path.join('/srv', 'git')
SSH_PORT = 29418
GERRIT_USER = 'gerrit2'
GERRIT_USER_HOME = os.path.join('/home', GERRIT_USER)
WAR_PATH = os.path.join(GERRIT_USER_HOME, 'gerrit-wars', 'gerrit.war')
SITE_PATH = os.path.join(GERRIT_USER_HOME, 'review_site')
LOGS_PATH = os.path.join(SITE_PATH, 'logs')
LAUNCHPAD_DIR = os.path.join(GERRIT_USER_HOME, '.launchpadlib')
TEMPLATES = 'templates'


def update_theme(theme_dest, static_dest):
    if not os.path.isdir(THEME_DIR):
        log('Gerrit theme directory not found @ %s, skipping theme refresh.' %
            THEME_DIR, level=WARNING)
        return False

    theme_orig = os.path.join(THEME_DIR, 'files')
    static_orig = os.path.join(THEME_DIR, 'static')

    if False in [os.path.isdir(theme_orig), os.path.isdir(static_orig)]:
        log('Theme directory @ %s missing required subdirs: files, static. '
            'Skipping theme refresh.' % THEME_DIR, level=WARNING)
        return False

    log('Installing theme from %s to %s.' % (theme_orig, theme_dest))
    common.sync_dir(theme_orig, theme_dest)
    log('Installing static files from %s to %s.' % (theme_orig, theme_dest))
    common.sync_dir(static_orig, static_dest)

    return True


def update_hooks(hooks_dest, settings):
    if not os.path.isdir(HOOKS_DIR):
        log('Gerrit hooks directory not found @ %s, skipping hooks refresh.' %
            HOOKS_DIR, level=WARNING)
        return False

    log('Installing gerrit hooks in %s to %s.' % (HOOKS_DIR, hooks_dest))
    common.sync_dir(HOOKS_DIR, hooks_dest)

    #  hook allow tags like {{var}}, so replace all entries in file
    for filename in os.listdir(hooks_dest):
        current_path = os.path.join(hooks_dest, filename)
        if os.path.isfile(current_path):
            with open(current_path, 'r') as f:
                contents = f.read()
            for key, value in settings.items():
                pattern = '{{%s}}' % (key)
                contents = contents.replace(pattern, value)
            with open(current_path, 'w') as f:
                f.write(contents)

    return True


def update_permissions(admin_username, admin_email, admin_privkey):
    if not os.path.isdir(PERMISSIONS_DIR):
        log('Gerrit permissions directory not found @ %s, skipping '
            'permissions refresh.' % PERMISSIONS_DIR, level=WARNING)
        return False

    # create launchpad directory and setup permissions
    if not os.path.isdir(LAUNCHPAD_DIR):
        os.mkdir(LAUNCHPAD_DIR)
        cmd = ['chown', "%s:%s" % (GERRIT_USER, GERRIT_USER), LAUNCHPAD_DIR]
        subprocess.check_call(cmd)
        os.chmod(LAUNCHPAD_DIR, 0774)

    # check if we have creds, push to dir
    if config('lp-credentials-file'):
        creds = b64decode(config('lp-credentials-file'))
        with open(os.path.join(LAUNCHPAD_DIR, 'creds'), 'w') as f:
            f.write(creds)

    # if we have teams and schedule, update cronjob
    if config('lp-schedule'):
        command = ('%s %s %s > %s 2>&1' %
                  (os.path.join(os.environ['CHARM_DIR'], 'scripts',
                   'query_lp_members.py'), admin_username, admin_privkey,
                   LOGS_PATH+'/launchpad_sync.log'))
        cron.schedule_generic_job(
            config('lp-schedule'), 'root', 'launchpad_sync', command)

    # parse groups file and create groups
    gerrit_client = GerritClient(
        host='localhost',
        user=admin_username, port=SSH_PORT,
        key_file=admin_privkey)

    groups_config = {}
    with open(GROUPS_CONFIG_FILE, 'r') as f:
        groups_config = yaml.load(f)
    for group, teams in groups_config.items():
        # create group
        gerrit_client.create_group(group)

    # update git repo with permissions
    log('Installing gerrit permissions from %s.' % PERMISSIONS_DIR)
    try:
        tmppath = tempfile.mkdtemp('', 'gerritperms')
        if tmppath:
            subprocess.check_call(
                ["chown", "%s:%s" % (GERRIT_USER, GERRIT_USER), tmppath])
            os.chmod(tmppath, 0774)

            cmds = [
                ['git', 'init'],
                ['git', 'remote', 'add', 'repo',
                 'ssh://%s@localhost:%s/All-Projects.git' %
                 (admin_username, SSH_PORT)],
                ['git', 'fetch', 'repo',
                 'refs/meta/config:refs/remotes/origin/meta/config'],
                ['git', 'checkout', 'meta/config']
            ]

            for cmd in cmds:
                common.run_as_user(
                    user=GERRIT_USER, cmd=cmd, cwd=tmppath)

            common.sync_dir(os.path.join(PERMISSIONS_DIR, 'All-Projects'),
                            tmppath)
            os.chdir(tmppath)

            # generate groups file
            query = 'SELECT name, group_uuid FROM account_groups'
            cmd = ['java', '-jar', WAR_PATH,
                   'gsql', '-d', SITE_PATH, '-c', query]
            result = subprocess.check_output(cmd)

            if result:
                # parse file and generate groups
                output = result.splitlines()
                with open('groups', 'w') as f:
                    for item in output[2:]:
                        # split between name and id
                        data = item.split('|')
                        if len(data) == 2:
                            f.write(
                                '%s\t%s\n' % (data[1].strip(), data[0].strip())
                            )

                cmds = [
                    ['git', 'config', '--global', 'user.name', admin_username],
                    ['git', 'config', '--global', 'user.email', admin_email],
                    ['git', 'commit', '-a', '-m', '"Initial permissions"'],
                    ['git', 'push', 'repo', 'meta/config:meta/config']
                ]
                for cmd in cmds:
                    common.run_as_user(
                        user=GERRIT_USER, cmd=cmd, cwd=tmppath)
            else:
                log('Error querying for groups', level=ERROR)
                return False
        else:
            log('Error creating permissions temporary directory', level=ERROR)
            return False
    except Exception as e:
        log('Error creating permissions: %s. '
            'Skipping it' % str(e), level=ERROR)

    return True


def setup_gitreview(path, repo):
    """
    Configure .gitreview so that when user clones repo the default git-review
    target is their CIaaS not upstream openstack.

    :param repo: <project>/<os-project>

    Returns list of commands to executed in the git repo to apply these
    changes.
    """
    cmds = []
    git_review_cfg = '.gitreview'
    target = os.path.join(path, git_review_cfg)

    log("Configuring %s" % (target))

    if not os.path.exists(target):
        log("%s not found in %s repo" % (target, repo), level=INFO)
        cmds.append(['git', 'add', git_review_cfg])

    host = unit_get('private-address')

    with open(os.path.join(TEMPLATES, git_review_cfg), 'r') as fd:
        t = Template(fd.read())
        rendered = t.render(repo=repo, host=host, port=SSH_PORT)

    with open(target, 'w') as fd:
        fd.write(rendered)

    cmds.append(['git', 'commit', '-a', '-m',
                 "Configured git-review to point to %s" % (host)])

    return cmds

import sys

def repo_is_initialised(url, branches):
    cmd = ['git', 'ls-remote', url]
    # Get list of branches extant in teh repo
    stdout = subprocess.check_output(cmd)
    key = r"^[\S]+.+?%s"
    keys = [re.compile(key % b) for b in branches]

    # These two branches are added by Gerrit so should always exist
    keys.append(re.compile(key % "HEAD"))
    keys.append(re.compile(key % "config"))

    found = 0
    for line in stdout.split('\n'):
        for i, key in enumerate(keys):
            result = key.match(line)
            if result:
                found += 1
                keys.pop(i)
                break

    if found == len(branches) + 2:
        return True

    return False

def create_projects(admin_username, admin_privkey, base_url, projects,
                    branches):
    """Globally create all projects and repositories, clone and push"""
    tmpdir = tempfile.mkdtemp()
    cmd = ["chown", "%s:%s" % (GERRIT_USER, GERRIT_USER), tmpdir]
    subprocess.check_call(cmd)
    os.chmod(tmpdir, 0774)

    gerrit_client = GerritClient(host='localhost', user=admin_username,
                                 port=SSH_PORT, key_file=admin_privkey)

    try:
        for project in projects:
            name, repo = project.itervalues()

            # TODO: currently if False is returned this can indicate either
            # error or already exists. Needs fixing in charm-helpers and
            # syncing in.
            if not gerrit_client.create_project(name):
                pass

            git_srv_path = os.path.join(GIT_PATH, name)
            project_name = repo.partition('/')[2]
            repo_path = os.path.join(tmpdir, name.replace('/', ''))
            repo_url = 'https://%s/%s' % (base_url, repo)
            gerrit_remote_url = "%s/%s.git" % (GIT_PATH, repo)

            # Only continue if the repo has NOT been successfully initialised.
            if self.repo_is_initialised(gerrit_remote_url, branches):
                log("Repository '%s' already initialised - skipping" %
                    (git_srv_path), level=INFO)
                continue

            log("Cloning git repository '%s'" % (repo_url))
            cmd = ['git', 'clone', repo_url, repo_path]
            common.run_as_user(user=GERRIT_USER, cmd=cmd, cwd=tmpdir)

            # Setup the .gitreview file to point to this repo by default (as
            # opposed to upstream openstack).
            cmds = setup_gitreview(repo_path, name)

            cmds.append(['git', 'remote', 'add', 'gerrit', gerrit_remote_url])
            # TODO: think this might be redundant now
            cmds.append(['git', 'fetch', '--all'])

            for cmd in cmds:
                common.run_as_user(user=GERRIT_USER, cmd=cmd, cwd=repo_path)

            # Push to each branch if needed
            for branch in branches:
                branch = branch.strip()
                try:
                    cmd = ['git', 'show-branch', 'gerrit/%s' % (branch)]
                    common.run_as_user(user=GERRIT_USER, cmd=cmd,
                                       cwd=repo_path)
                except Exception:
                    # branch does not exist, create it
                    ref = 'HEAD:refs/heads/%s' % branch
                    cmds = [['git', 'checkout', branch],
                            ['git', 'pull'],
                            ['git', 'push', '--force', 'gerrit', ref]]
                    for cmd in cmds:
                        common.run_as_user(user=GERRIT_USER, cmd=cmd,
                                           cwd=repo_path)

            gerrit_client.flush_cache()

    except Exception as e:
        log('Error creating project branch: %s' % str(e), ERROR)
        sys.exit(1)


# installs initial projects and branches based on config
def update_projects(admin_username, privkey_path):
    if not os.path.isfile(PROJECTS_CONFIG_FILE):
        log('Gerrit projects directory not found @ %s, '
            'skipping permissions refresh.' %
            PROJECTS_CONFIG_FILE, level=WARNING)
        return False

    # parse yaml file to grab config
    with open(PROJECTS_CONFIG_FILE, 'r') as f:
        config = yaml.load(f)

    for opt in ['base_url', 'branches', 'projects']:
        if opt not in config:
            log('Gerrit projects config not found', level=WARNING)
            break

    if 'projects' in config:
        create_projects(admin_username, privkey_path, config['base_url'],
                        config['projects'], config['branches'])


def update_gerrit():
    if not relation_ids('gerrit-configurator'):
        log('*** No relation to gerrit, skipping update.')
        return

    rel_settings = {}

    for rid in relation_ids('gerrit-configurator'):
        for unit in related_units(rid):
            rel_settings = {
                'admin_username': relation_get('admin_username',
                                               rid=rid, unit=unit),
                'admin_email': relation_get('admin_email',
                                            rid=rid, unit=unit),
                'privkey_path': relation_get('admin_privkey_path',
                                             rid=rid, unit=unit),
                'review_site_root': relation_get('review_site_dir',
                                                 rid=rid, unit=unit)
            }

    if not rel_settings:
        log('Found no relation data set by gerrit, skipping update.')
        return

    if (None in rel_settings.itervalues() or
       '' in rel_settings.itervalues()):
        log('Username or private key path not set, skipping permissions '
            'refresh.', level=WARNING)
        return False

    log("*** Updating gerrit.")
    if not os.path.isdir(GERRIT_CONFIG_DIR):
        log('Could not find gerrit config directory at expected location, '
            'skipping gerrit update (%s)' % GERRIT_CONFIG_DIR)
        return

    # installation location of hooks and theme, based on review_site path
    # exported from principle
    hooks_dir = os.path.join(rel_settings['review_site_root'], 'hooks')
    theme_dir = os.path.join(rel_settings['review_site_root'], 'etc')
    static_dir = os.path.join(rel_settings['review_site_root'], 'static')

    restart_req = False
    restart_req = update_projects(rel_settings['admin_username'],
                                  rel_settings['privkey_path'])
    restart_req = update_permissions(rel_settings['admin_username'],
                                     rel_settings['admin_email'],
                                     rel_settings['privkey_path'])
    restart_req = update_hooks(hooks_dir, rel_settings)
    restart_req = update_theme(theme_dir, static_dir)

    if restart_req:
        stop_gerrit()
        start_gerrit()
