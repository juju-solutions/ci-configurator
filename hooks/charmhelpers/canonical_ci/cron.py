import os

from charmhelpers.core.hookenv import log, INFO


# generic backup job creation
def schedule_backup(sources, target, schedule, retention_count):
    log("Creating backup cronjob for sources: %s." % sources, INFO)

    # if doesn't exist, create backup directory and scripts directory
    if not os.path.exists(target):
        os.makedirs(target)
        os.chmod(target, 0755)

    script = os.path.join(os.environ['CHARM_DIR'],
                          "scripts/backup_job")
    backup_string = ",".join(sources)

    # create the cronjob file that will call the script
    content = ("%s %s %s %s %s\n" %
               (schedule, script, backup_string, target, retention_count))

    f = os.environ["JUJU_UNIT_NAME"].replace("/", "_")
    cron_path = os.path.join('/etc', 'cron.d', f)
    f = open(cron_path, "w")
    f.write(content)
    f.close()
    os.chmod(cron_path, 0755)
    log("Wrote cronjob to %s." % cron_path, INFO)
