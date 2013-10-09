import os
import subprocess
import tempfile
import yaml
import sys

import common

from charmhelpers.core.hookenv import (
    log, relation_ids, relation_get, related_units, WARNING, ERROR, INFO)
from charmhelpers.canonical_ci.gerrit import (
    GerritClient, start_gerrit, stop_gerrit)

GERRIT_INIT_SCRIPT = '/etc/init.d/gerrit'
GERRIT_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'gerrit')
THEME_DIR = os.path.join(GERRIT_CONFIG_DIR, 'theme')
HOOKS_DIR = os.path.join(GERRIT_CONFIG_DIR, 'hooks')
PERMISSIONS_DIR = os.path.join(GERRIT_CONFIG_DIR, 'permissions')
PROJECTS_CONFIG_FILE = os.path.join(GERRIT_CONFIG_DIR, 'projects/projects.yml')
GROUPS_CONFIG_FILE = os.path.join(GERRIT_CONFIG_DIR, 'permissions/groups.yml')
GERRIT_USER = "gerrit2"
SSH_PORT = 29418
GIT_PATH = '/srv/git'
WAR_PATH = '/home/gerrit2/gerrit-wars/gerrit.war'
SITE_PATH = '/home/gerrit2/review_site'


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
                pattern = '{{'+key+'}}'
                contents = contents.replace(pattern, value)
            with open(current_path, 'w') as f:
                f.write(contents)

    return True


def update_permissions(admin_username, admin_email, admin_privkey):
    if not os.path.isdir(PERMISSIONS_DIR):
        log('Gerrit permissions directory not found @ %s, skipping '
            'permissions refresh.' % PERMISSIONS_DIR, level=WARNING)
        return False

    # parse groups file and create groups
    gerrit_client = GerritClient(
        host='localhost',
        user=admin_username, port=SSH_PORT,
        key_file=admin_privkey)

    config = {}
    with open(GROUPS_CONFIG_FILE, 'r') as f:
        config = yaml.load(f)
    for group, teams in config.items():
        # create group
        gerrit_client.create_group(group)

    # update git repo with permissions
    log('Installing gerrit permissions from %s.' % PERMISSIONS_DIR)
    try:
        tmppath = tempfile.mkdtemp('', 'gerritperms')
        if tmppath:
            subprocess.check_call(
                ["chown", GERRIT_USER+":"+GERRIT_USER, tmppath])
            os.chmod(tmppath, 0774)

            cmds = [
                ['git', 'init'],
                ['git', 'remote', 'add', 'repo', 'ssh://%s@localhost:%s/All-Projects.git' % (admin_username, SSH_PORT)],
                ['git', 'fetch', 'repo', 'refs/meta/config:refs/remotes/origin/meta/config'],
                ['git', 'checkout', 'meta/config']
            ]
            for cmd in cmds:
                common.run_as_user(user=GERRIT_USER, cmd=cmd,
                    cwd=tmppath)

            common.sync_dir(PERMISSIONS_DIR+'/All-Projects', tmppath)
            os.chdir(tmppath)
            # generate groups file
            query = 'SELECT name, group_uuid FROM account_groups'
            cmd = ['java', '-jar', WAR_PATH, 'gsql', '-d', SITE_PATH, '-c', query]
            result = subprocess.check_output(cmd)
            if result:
                # parse file and generate groups
                output = result.splitlines()
                with open('groups','w') as f:
                    for item in output[2:]:
                        # split between name and id
                        data = item.split('|')
                        if len(data)==2:
                            f.write('%s\t%s\n' % (data[1].strip(), data[0].strip()))

                cmds = [
                    ['git', 'config', '--global', 'user.name', admin_username],
                    ['git', 'config', '--global', 'user.email', admin_email],
                    ['git', 'commit', '-a', '-m', '"Initial permissions"'],
                    ['git', 'push', 'repo', 'meta/config:meta/config']
                ]
                for cmd in cmds:
                    common.run_as_user(user=GERRIT_USER, cmd=cmd,
                        cwd=tmppath)
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


# globally create all projects, clone and push
def create_projects(admin_username, admin_privkey, base_url,
                    projects, branches):
    tmpdir = tempfile.mkdtemp()
    subprocess.check_call(
        ["chown", GERRIT_USER+":"+GERRIT_USER, tmpdir])
    os.chmod(tmpdir, 0774)

    gerrit_client = GerritClient(
        host='localhost',
        user=admin_username, port=SSH_PORT,
        key_file=admin_privkey)

    try:
        for project in projects:
            name, repo = project.itervalues()
            gerrit_client.create_project(name)

            # successfully created project, push from git
            path_name = os.path.join(tmpdir, name.replace('/', ''))
            # clone and push
            repo_url = 'ssh://%s@%s/%s' % (admin_username, base_url, repo)
            cmd = ['git', 'clone', repo_url, path_name]
            common.run_as_user(user=GERRIT_USER, cmd=cmd, cwd=tmpdir)
            cmds = [
                ['git', 'remote', 'add', 'gerrit', '%s/%s.git' % (GIT_PATH, repo)],
                ['git', 'fetch', '--all']
            ]
            for cmd in cmds:
                common.run_as_user(user=GERRIT_USER, cmd=cmd,
                    cwd=path_name)

            # push to each branch if needed
            for branch in branches:
                branch = branch.strip()
                try:
                    cmd = ['git', 'show-branch', 'gerrit/'+branch]
                    common.run_as_user(user=GERRIT_USER, cmd=cmd, cwd=path_name)
                except Exception:
                    # branch does not exist, create it
                    ref = 'HEAD:refs/heads/%s' % branch
                    cmds = [
                        ['git', 'checkout', branch],
                        ['git', 'pull'],
                        ['git', 'push', '--force', 'gerrit', ref]
                        ]
                    for cmd in cmds:
                        common.run_as_user(user=GERRIT_USER, cmd=cmd,
                            cwd=path_name)
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
    config = {}
    with open(PROJECTS_CONFIG_FILE, 'r') as f:
        config = yaml.load(f)
    if ('base_url' not in config or 'branches' not in config or
       'projects' not in config):
        log('Gerrit projects config not found', level=WARNING)

    projects = config['projects']
    branches = config['branches']
    if projects:
        create_projects(admin_username, privkey_path, config['base_url'],
                        projects, branches)


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
