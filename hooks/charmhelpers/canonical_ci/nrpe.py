from charmhelpers.core.hookenv import log


HTTP_CHECK = """
command[%(name)s]=/usr/lib/nagios/plugins/check_http
--hostname=%(hostname)s --port=%(port)s
""".strip().replace('\n', ' ')


TCP_CHECK = """
command[%(name)s]=/usr/lib/nagios/plugins/check_tcp
--hostname=%(hostname)s --port=%(port)s
""".strip().replace('\n', ' ')


NRPE_SERVICE_ENTRY = """
define service {
    use active-service
    host_name %(nagios_hostname)s
    service_description %(nagios_hostname)s %(check_name)s
    check_command check_nrpe!%(check_name)s
    servicegroups %(nagios_servicegroup)s
}

"""


NRPE_CHECKS = {
    'http': HTTP_CHECK,
    'tcp': TCP_CHECK,
}


CONF_HEADER = "#" * 80 + "\n# This file is Juju managed\n" + "#" * 80 + '\n'


def nrpe_service_config(check_name, nagios_hostname, nagios_servicegroup):
    """
    Generates a single snippet of nagios config for a monitored service.
    Does not verify whether the check to use is actually configured.
    """
    return NRPE_SERVICE_ENTRY % locals()


def nrpe_check(check_type, name, hostname, port, **kwargs):
    """
    Generates a single NRPE check command for a given type.

    name, hostname and port are currently required for all.

    Any kwargs will be expanded to additional --k=v arguments,
    or --k argument if value is True.
    """
    try:
        cmd = NRPE_CHECKS[check_type]
    except KeyError:
        e = 'Unsupported NRPE check type: %s.' % check_type
        log(e)
        raise Exception(e)
    cmd = cmd % locals()
    for k, v in kwargs.iteritems():
        if v is True:
            cmd += ' --%s' % k
        else:
            cmd += ' --%s=%s' % (k, v)
    return cmd
