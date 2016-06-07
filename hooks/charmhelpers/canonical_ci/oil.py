# This module holds common features shared by OIL charms.
import os

from charmhelpers.core.hookenv import charm_dir


def render_template(template_name, context, template_dir=None):
    # Import jinja here to avoid import error during install hook.
    import jinja2
    if not template_dir:
        template_dir = os.path.join(charm_dir(), 'templates')

    loader = jinja2.FileSystemLoader(template_dir)
    templates = jinja2.Environment(loader=loader)
    template = templates.get_template(template_name)
    return template.render(context)
