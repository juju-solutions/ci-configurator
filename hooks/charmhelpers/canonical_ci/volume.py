# Helpers to facilitate initializing and moving application data
# to persistent volumes.  The bulk of it has been lifted directly
# from lp:charms/postgresql, with modification  to volume_apply()
# to remove postgres specific bits.
#
# - Adam Gandelman <adamg@canonical.com>

import subprocess
import sys
import os
import time
import yaml

from charmhelpers.core import hookenv

from charmhelpers.core.hookenv import (
    config, WARNING, INFO, ERROR, CRITICAL,
    log as _log,
)


def log(level, msg):
    msg = '[peristent storage] ' + msg
    _log(level=level, message=msg)


def run(command, exit_on_error=True):
    '''Run a command and return the output.'''
    try:
        log(INFO, command)
        return subprocess.check_output(
            command, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError, e:
        log(ERROR, "status=%d, output=%s" % (e.returncode, e.output))
        if exit_on_error:
            sys.exit(e.returncode)
        else:
            raise


###############################################################################
# Volume managment
###############################################################################
#------------------------------
# Get volume-id from juju config "volume-map" dictionary as
#     volume-map[JUJU_UNIT_NAME]
# @return  volid
#
#------------------------------
def volume_get_volid_from_volume_map():
    volume_map = {}
    try:
        volume_map = yaml.load(config('volume-map').strip())
        if volume_map:
            return volume_map.get(os.environ['JUJU_UNIT_NAME'])
    except yaml.constructor.ConstructorError as e:
        log(WARNING, "invalid YAML in 'volume-map': {}".format(e))
    return None


# Is this volume_id permanent ?
# @returns  True if volid set and not --ephemeral, else:
#           False
def volume_is_permanent(volid):
    if volid and volid != "--ephemeral":
        return True
    return False


# Do we have a valid storage state?
# @returns  volid
#           None    config state is invalid - we should not serve
def volume_get_volume_id():
    ephemeral_storage = config('volume-ephemeral-storage')
    volid = volume_get_volid_from_volume_map()
    juju_unit_name = hookenv.local_unit()
    if ephemeral_storage in [True, 'yes', 'Yes', 'true', 'True']:
        if volid:
            log(ERROR,
                "volume-ephemeral-storage is True, but " +
                "volume-map[{!r}] -> {}".format(juju_unit_name, volid),)
            return None
        else:
            return "--ephemeral"
    else:
        if not volid:
            log(WARNING,
                "volume-ephemeral-storage is False, but "
                "no volid found for volume-map[{!r}]".format(
                    hookenv.local_unit()))
            return None
    return volid


# Initialize and/or mount permanent storage, it straightly calls
# shell helper
def volume_init_and_mount(volid):
    command = ("scripts/volume-common.sh call " +
               "volume_init_and_mount %s" % volid)
    output = run(command)
    if output.find("ERROR") >= 0:
        return False
    return True


def volume_mount_point_from_volid(volid):
    if volid and volume_is_permanent(volid):
        return "/srv/juju/%s" % volid
    return None


def volume_apply(data_directory_path, service, user, group):
    # assumes service stopped.
    volid = volume_get_volume_id()
    if volid:
        if volume_is_permanent(volid):
            if not volume_init_and_mount(volid):
                log(ERROR,
                    "volume_init_and_mount failed, not applying changes")
                return False

        if not os.path.exists(data_directory_path):
            log(CRITICAL,
                "postgresql data dir {} not found, "
                "not applying changes.".format(data_directory_path))
            return False

        mount_point = volume_mount_point_from_volid(volid)
        # new data path consturcted as if mount_point were chroot, eg
        # /srv/juju/vol-000010/var/lib/mysql
        new_data_path = os.path.join(
            mount_point, *data_directory_path.split('/'))

        if not mount_point:
            log(ERROR,
                "invalid mount point from volid = {}, "
                "not applying changes.".format(mount_point))
            return False

        if ((os.path.islink(data_directory_path) and
             os.readlink(data_directory_path) == new_data_path)):
            log(INFO,
                "%s data dir '%s' already points "
                "to %s skipping storage changes." % (
                    service, data_directory_path, new_data_path))
            log(INFO,
                "existing-symlink: to fix/avoid UID changes from "
                "previous units, doing: "
                "chown -R %s:%s %s" % (user, group, new_data_path))
            run("chown -R %s:%s %s" % (user, group, new_data_path))
            return True

        # Create new data directory path under mount point if required
        # and set permissions.
        # Create a directory structure below "new" mount_point, as e.g.:
        #   /srv/juju/vol-000012345/postgresql/9.1/main  , which "mimics":
        #   /var/lib/postgresql/9.1/main
        if not os.path.isdir(new_data_path):
            log(INFO, "Creating new data path under mount: %s" % new_data_path)
            os.makedirs(new_data_path)

        # Ensure directory permissions on every run.
        log(INFO, "Ensuring %s:%s ownership on %s." %
            (user, group, new_data_path))
        run("chown -R %s:%s %s" % (user, group, new_data_path))

#            curr_dir_stat = os.stat(data_directory_path)
#            os.chown(new_data_path, curr_dir_stat.st_uid, curr_dir_stat.st_gi
#            os.chmod(new_data_path, curr_dir_stat.st_mode)

#        for new_dir in [new_pg_dir,
#                        os.path.join(new_pg_dir, config("version")),
#                        new_pg_version_cluster_dir]:
#            if not os.path.isdir(new_dir):
#                log("mkdir %s".format(new_dir))
#                os.mkdir(new_dir)
#                # copy permissions from current data_directory_path
#                os.chown(new_dir, curr_dir_stat.st_uid, curr_dir_stat.st_gid)
#                os.chmod(new_dir, curr_dir_stat.st_mode)

        # Carefully build this symlink, e.g.:
        # /var/lib/postgresql/9.1/main ->
        # /srv/juju/vol-000012345/postgresql/9.1/main
        # but keep previous "main/"  directory, by renaming it to
        # main-$TIMESTAMP

        log(WARNING, "migrating application data {}/ -> {}/".format(
            data_directory_path, new_data_path))

        command = "rsync -a {}/ {}/".format(data_directory_path, new_data_path)
        log(INFO, "run: {}".format(command))
        run(command)

#        if not os.path.exists(os.path.join(
#            new_pg_version_cluster_dir, "PG_VERSION")):
#            log("migrating PG data {}/ -> {}/".format(
#                data_directory_path, new_pg_version_cluster_dir), WARNING)
#            # void copying PID file to perm storage (shouldn't be any...)
#            command = "rsync -a --exclude postmaster.pid {}/ {}/".format(
#                data_directory_path, new_pg_version_cluster_dir)
#            log("run: {}".format(command))
#            run(command)

        try:
            os.rename(data_directory_path, "{}-{}".format(
                data_directory_path, int(time.time())))
            log(INFO, "symlinking {} -> {}".format(
                new_data_path, data_directory_path))
            os.symlink(new_data_path, data_directory_path)
            log(INFO,
                "after-symlink: to fix/avoid UID changes from "
                "previous units, doing: "
                "chown -R %s:%s %s" % (user, group, new_data_path))
            run("chown -R %s:%s %s" % (user, group, new_data_path))
            return True
        except OSError:
            log(ERROR, "failed to symlink {} -> {}".format(
                data_directory_path, new_data_path))
            return False
    else:
        log(ERROR,
            "Invalid volume storage configuration, not applying changes")
    return False
