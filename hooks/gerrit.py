import os
import subprocess
import tempfile
import yaml
import pwd

import common

from charmhelpers.core.hookenv import log, relation_ids, relation_get, WARNING, ERROR
from charmhelpers.canonical_ci.gerrit import GerritClient, start_gerrit, stop_gerrit

GERRIT_INIT_SCRIPT = '/etc/init.d/gerrit'
GERRIT_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'gerrit')
THEME_DIR = os.path.join(GERRIT_CONFIG_DIR, 'theme')
HOOKS_DIR = os.path.join(GERRIT_CONFIG_DIR, 'hooks')
PERMISSIONS_DIR = os.path.join(GERRIT_CONFIG_DIR, 'permissions')
PROJECTS_CONFIG_FILE = os.path.join(GERRIT_CONFIG_DIR, 'projects/projects.yml')
GERRIT_USER = "gerrit2"
SSH_PORT = 29418
GIT_PATH = '/srv/git'


def update_theme():
    # TODO (adam_g)
    # These installation destinations needs to come from principle via relation
    theme_dest = '/home/gerrit2/review_site/etc/'
    static_dest = '/home/gerrit2/review_site/static/'

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


def update_hooks():
    # TODO (adam_g)
    # These installation destinations needs to come from principle via relation
    hooks_dest = '/home/gerrit2/review_site/hooks/'

    if not os.path.isdir(HOOKS_DIR):
        log('Gerrit hooks directory not found @ %s, skipping hooks refresh.' %
            HOOKS_DIR, level=WARNING)
        return False

    # TODO:
    # The hooks require some dynamic data (git server, admin_username)
    # etc.  Need to find a way to either pass it in via:
    #  - a common file sourced by hooks that contains stuff as environment
    #    variables
    #       OR
    #  - some basic templating on the script itself.
    log('Installing gerrit hooks in %s to %s.' % (HOOKS_DIR, hooks_dest))
    common.sync_dir(HOOKS_DIR, hooks_dest)
    return True


def update_permissions():
    # TODO (yolanda.robla)
    # These installation destinations needs to come from principle via relation
    git_permissions_dest = '/srv/git/All-Projects.git'

    if not os.path.isdir(PERMISSIONS_DIR):
        log('Gerrit permissions directory not found @ %s, skipping permissions refresh.' %
            PERMISSIONS_DIR, level=WARNING)
        return False

    if not os.path.isdir(git_permissions_dest):
        log('Target permissions directory @ %s, is still not ready, please retry.' %
            git_permissions_dest, level=WARNING)

    # update git repo with permissions
    log('Installing gerrit permissions from %s.' % PERMISSIONS_DIR)
    try:
        tmppath = tempfile.mkdtemp('', 'gerritperms')
        if tmppath:
            os.chdir(tmppath)
            cmd = ("export HOME='/srv/git' && git config --global user.email %s && "
                "git config --global user.name %s && "
                "git init && git remote add repo %s && "
                "git fetch repo refs/meta/config:refs/remotes/origin/meta/config "
                "&& git checkout meta/config" % 
                (relation_get('admin_email'), relation_get('admin_username'), git_permissions_dest)
            )
            subprocess.check_call(cmd, shell=True)

            # copy files to temp dir, then commit and push
            common.sync_dir(PERMISSIONS_DIR+'/All-Projects', tmppath)

            cmd = ("export HOME='/srv/git' && git config --global user.name %s && "
                "git config --global user.email %s && "
                "git commit -a -m 'Initial permissions' && "
                "git push repo meta/config:meta/config" % 
                (relation_get('admin_email'), relation_get('admin_username'))
            )
            subprocess.check_call(cmd, shell=True)
        else:
            log('Error creating permissions temporary directory', level=ERROR)
            return False
    except Exception as e:    
        log('Error creating permissions: %s. Skipping it' % str(e), level=ERROR)

    return True

# globally create all projects, clone and push
def create_projects(admin_username, admin_privkey, base_url, project_list, branch_list):
    branches_path = tempfile.mkdtemp('', 'gerritbranches')
    if branches_path:
        subprocess.check_call(
            ["chown", GERRIT_USER+":"+GERRIT_USER, branches_path])
        os.chmod(branches_path, 0774)
        os.chdir(branches_path)

        # change to gerrit to perform project creation
        pw = pwd.getpwnam(GERRIT_USER)
        pid = os.fork()
        if pid == 0:
            # we are on child, create projects
            try:
                os.setuid(pw[3])
                gerrit_client = GerritClient(host='localhost',
                    user=admin_username, port=SSH_PORT,
                    key_file = admin_privkey)

                for project in project_list:
                    # split project in name and path
                    project_set = project.split('=')
                    if len(project_set)==2:
                        # create project
                        project_name = project_set[0].strip()
                        gerrit_client.create_project(project_name)

                        # clone and push
                        os.chdir(branches_path)
                        path_name = project_name.replace('/', '')
                        cmd = ('git clone ssh://%s@%s/%s %s' % 
                            (admin_username, base_url, project_set[1].strip(),
                             path_name))
                        subprocess.check_call(cmd, shell=True)

                        os.chdir(branches_path+'/'+path_name)
                        cmd = 'git remote add gerrit %s/%s.git' % (GIT_PATH, project_name)
                        subprocess.check_call(cmd, shell=True)

                        # push to each branch
                        for branch in branch_list:
                            branch = branch.strip()
                            try:
                                cmd = ('git checkout %(branch)s && git pull && '
                                    'git push gerrit origin/master:refs/heads/%(branch)s && '
                                    'git push gerrit origin/master:refs/for/%(branch)s' % 
                                    {'branch':branch})
                                subprocess.check_call(cmd, shell=True)
                            except Exception as e:
                                log('Error creating branch: %s' % str(e), ERROR)

                gerrit_client.flush_cache()
            except Exception as e:
                log('Error creating project: %s' % str(e), ERROR)
                os._exit(1)
            finally:
                os._exit(0)
        else:
            os.wait()

# installs initial projects and branches based on config
def update_projects():
    username = relation_get('admin_username')
    privkey_path = relation_get('admin_privkey_path')
    if not username or not privkey_path:
        log('Username or private key path not set, skipping permissions refresh.', level=WARNING)
        return False

    if not os.path.isfile(PROJECTS_CONFIG_FILE):
        log('Gerrit projects directory not found @ %s, skipping permissions refresh.' %
            PROJECTS_CONFIG_FILE, level=WARNING)
        return False

    # parse yaml file to grab config
    config = {}
    with open(PROJECTS_CONFIG_FILE, 'r') as f:
        config = yaml.load(f)
    if not 'base_url' in config or not 'branches' in config or not 'projects' in config:
        log('Gerrit projects config not found', level=WARNING)

    projects_list = config['projects'].split(',')
    branches_list = config['branches'].split(',')
    if len(projects_list)>0:
        create_projects(relation_get('admin_username'),
            relation_get('admin_privkey_path'), config['base_url'], projects_list, branches_list)

def update_gerrit():
    if not relation_ids('gerrit-configurator'):
        return

    log("*** Updating gerrit.")
    if not os.path.isdir(GERRIT_CONFIG_DIR):
        log('Could not find gerrit config directory at expected location, '
            'skipping gerrit update (%s)' % GERRIT_CONFIG_DIR)
        return
    restart_req = False
    restart_req = update_theme()
    restart_req = update_hooks()
    restart_req = update_permissions()
    restart_req = update_projects()

    if restart_req:
        stop_gerrit()
        start_gerrit()
