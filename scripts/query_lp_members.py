#! /usr/bin/env python
# Copyright (C) 2011 OpenStack, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# Synchronize Gerrit users from Launchpad.

import os
import json
import sys
import yaml

from launchpadlib.launchpad import Launchpad
from launchpadlib.uris import LPNET_SERVICE_ROOT

from openid.consumer import consumer
from openid.cryptutil import randomString
sys.path.append(os.path.abspath(os.path.dirname(__file__) + '/' + '../hooks'))
import common
from charmhelpers.canonical_ci.gerrit import GerritClient

GERRIT_CACHE_DIR = '/home/gerrit2/.launchpadlib/cache'
GERRIT_CREDENTIALS = '/home/gerrit2/.launchpadlib/creds'
GERRIT_USER_OUTPUT = '/home/gerrit2/.launchpadlib/users'

GERRIT_CONFIG_DIR = os.path.join(common.CI_CONFIG_DIR, 'gerrit')
GROUPS_CONFIG_FILE = os.path.join(GERRIT_CONFIG_DIR, 'permissions/groups.yml')
SSH_PORT = 29418

# check parameters from command line
if len(sys.argv)<3:
    print "ERROR: Please send user and private key in parameters."
    sys.exit(1)
admin_username = sys.argv[1]
admin_privkey = sys.argv[2]

for check_path in (os.path.dirname(GERRIT_CACHE_DIR),
                   os.path.dirname(GERRIT_CREDENTIALS)):
    if not os.path.exists(check_path):
        os.makedirs(check_path)


def get_type(in_type):
    if in_type == "RSA":
        return "ssh-rsa"
    else:
        return "ssh-dsa"


launchpad = Launchpad.login_with('Canonical CI Gerrit User Sync',
                                 LPNET_SERVICE_ROOT,
                                 GERRIT_CACHE_DIR,
                                 credentials_file=GERRIT_CREDENTIALS)

def get_openid(lp_user):
    k = dict(id=randomString(16, '0123456789abcdef'))
    openid_consumer = consumer.Consumer(k, None)
    openid_request = openid_consumer.begin(
        "https://launchpad.net/~%s" % lp_user)
    return openid_request.endpoint.getLocalID()

# create gerrit connection
gerrit_client = GerritClient(
    host='localhost',
    user=admin_username,
    port=SSH_PORT,
    key_file=admin_privkey)

groups_config = {}
with open(GROUPS_CONFIG_FILE, 'r') as f:
    groups_config = yaml.load(f)

need_reboot = False
for group, teams in groups_config.items():
    # create group if not exists
    try:
        print "Creating group %s" % group
        gerrit_client.create_group(group)
        need_reboot = True
    except:
        print "Skipping group creation"

    # grab all the users in that teams
    teams = teams.split(' ')

    final_users = []
    for team_todo in teams:
        team = launchpad.people[team_todo]
        details = team.members_details
        print "Creating users for team %s" % team
        for detail in details:
            user = None
            # detail.self_link ==
            # 'https://api.launchpad.net/1.0/~team/+member/${username}'
            login = detail.self_link.split('/')[-1]

            status = detail.status
            member = launchpad.people[login]

            if (status == "Approved" or status == "Administrator") and \
                (not member.is_team):
                openid = get_openid(login)

                full_name = member.display_name.encode('ascii', 'replace')

                email = None
                try:
                    email = member.preferred_email_address.email
                except ValueError:
                    pass

                ssh_keys = [
                    "%s %s %s" % (get_type(key.keytype), key.keytext, key.comment)
                    for key in member.sshkeys
                ]
                ssh_keys = [k.strip() for k in ssh_keys]

                # add user into gerrit for that group
                if len(ssh_keys)>0:
                    final_user = [login, full_name, ssh_keys[0]]
                    final_users.append(final_user)
                    need_reboot = True
    
    # add all the users
    try:
        gerrit_client.create_users_batch(group, final_users)
    except Exception as e:
        print "ERROR creating users %s" % str(e)
        sys.exit(1)
            
if need_reboot:
    gerrit_client.flush_cache()
