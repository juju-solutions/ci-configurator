import os
import mock
import testtools
import tempfile
import shutil

gerrit = None  # stub to stop flake8 errors

LS_REMOTE_OUTPUT = """
3bd6f626873b11b27624769554ec5fbebe48a056    HEAD
3bd6f626873b11b27624769554ec5fbebe48a056    refs/heads/master
15ac7baff8d1251547a51dd3b1d51c52e0932d0d    refs/meta/config
"""


def common_mocks(f):
    def common_test_mocks_inner(inst, *args, **kwargs):

        @mock.patch('charmhelpers.fetch.apt_install')
        @mock.patch('charmhelpers.core.hookenv.log')
        def common_test_mocks_inner2(*inner_args):
            # Need to import gerrit after we have mocked apt_install
            import gerrit
            global gerrit
            for arg in inner_args:
                inst.__dict__[arg] = arg
            return f(inst, *args, **kwargs)

        return common_test_mocks_inner2()

    return common_test_mocks_inner


class GerritTestCase(testtools.TestCase):

    def setUp(self):
        super(GerritTestCase, self).setUp()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        super(GerritTestCase, self).tearDown()
        shutil.rmtree(self.tmpdir)

    @mock.patch('gerrit.charm_dir')
    @mock.patch('tempfile.mkdtemp')
    @common_mocks
    def test_setup_gitreview(self, mock_mkdtemp, mock_charm_dir):
        mock_charm_dir.return_value = '.'
        mock_mkdtemp.return_value = self.tmpdir
        project = 'openstack/neutron.git'
        host = 'http://foo.bar'
        cmds = gerrit.setup_gitreview(self.tmpdir, project, host)

        self.assertEquals([['git', 'add', '.gitreview'],
                           ['git', 'commit', '-a', '-m',
                            "Configured git-review to point to '%s'" %
                            (host)]],
                          cmds)
        with open(os.path.join(self.tmpdir, '.gitreview'), 'r') as fd:
            self.assertEqual(['[gerrit]\n', 'host=%s\n' % (host),
                              'port=29418\n', 'project=%s\n' % (project)],
                             fd.readlines())

    @mock.patch('gerrit.charm_dir')
    @mock.patch('tempfile.mkdtemp')
    @common_mocks
    def test_setup_gitreview_already_exists(self, mock_mkdtemp,
                                            mock_charm_dir):
        mock_charm_dir.return_value = '.'
        mock_mkdtemp.return_value = self.tmpdir
        shutil.copy(os.path.join(gerrit.TEMPLATES, '.gitreview'), self.tmpdir)
        project = 'openstack/neutron.git'
        host = 'http://foo.bar'
        cmds = gerrit.setup_gitreview(self.tmpdir, project, 'http://foo.bar')

        self.assertEquals([['git', 'commit', '-a', '-m',
                            "Configured git-review to point to '%s'" %
                            (host)]],
                          cmds)
        with open(os.path.join(self.tmpdir, '.gitreview'), 'r') as fd:
            self.assertEqual(['[gerrit]\n', 'host=%s\n' % (host),
                              'port=29418\n', 'project=%s\n' % (project)],
                             fd.readlines())

    @mock.patch('tempfile.mkdtemp')
    @common_mocks
    def test_get_gerrit_hostname_public_url_none(self, mock_mkdtemp):
        try:
            gerrit.get_gerrit_hostname(None)
        except Exception as exc:
            self.assertIsInstance(exc, gerrit.GerritConfigurationException)
        else:
            raise Exception("Did not get expected exception in unit test")

    @mock.patch('tempfile.mkdtemp')
    @common_mocks
    def test_get_gerrit_hostname_public_url(self, mock_mkdtemp):
        mock_mkdtemp.return_value = self.tmpdir
        shutil.copy(os.path.join(gerrit.TEMPLATES, '.gitreview'), self.tmpdir)
        for public_url in ['http://foo.bar', 'ssh://foo.bar/', 'foo.bar']:
            host = gerrit.get_gerrit_hostname(public_url)
            self.assertEqual(host, 'foo.bar')

    @mock.patch('subprocess.check_output')
    @common_mocks
    def test_repo_is_initialised(self, mock_check_output):
        branches = ['master']
        mock_check_output.return_value = LS_REMOTE_OUTPUT
        result = gerrit.repo_is_initialised('/foo/bar', branches)
        self.assertTrue(result)
