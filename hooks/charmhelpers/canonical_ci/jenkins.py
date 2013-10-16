import logging
import os
import paramiko
import sys
import subprocess
import json

from charmhelpers.core.hookenv import (
    log as _log,
    ERROR,
)

JENKINS_DAEMON = "/etc/init.d/jenkins"

logging.basicConfig(level=logging.INFO)


def log(msg, level=None):
    # wrap log calls and distribute to correct logger
    # depending if this code is being run by a hook
    # or an external script.
    if os.getenv('JUJU_AGENT_SOCKET'):
        _log(msg, level=level)
    else:
        logging.info(msg)


# start jenkins application
def start_jenkins():
    try:
        subprocess.check_call([JENKINS_DAEMON, "start"])
    except:
        pass


# stop jenkins application
def stop_jenkins():
    try:
        subprocess.check_call([JENKINS_DAEMON, "stop"])
    except:
        pass
