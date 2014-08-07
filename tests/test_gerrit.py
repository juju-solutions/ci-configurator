import os
import mock
import testtools
import gerrit
import tempfile
import shutil


LS_REMOTE_OUTPUT = """
3bd6f626873b11b27624769554ec5fbebe48a056    HEAD
3bd6f626873b11b27624769554ec5fbebe48a056    refs/heads/master
15ac7baff8d1251547a51dd3b1d51c52e0932d0d    refs/meta/config
"""


class GerritTestCase(testtools.TestCase):

    def setUp(self):
        super(GerritTestCase, self).setUp()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        super(GerritTestCase, self).tearDown()
        shutil.rmtree(self.tmpdir)

    @mock.patch('tempfile.mkdtemp')
    @mock.patch('gerrit.unit_get')
    @mock.patch('gerrit.log')
    def test_setup_gitreview(self, mock_log, mock_unit_get, mock_mkdtemp):
        mock_mkdtemp.return_value = self.tmpdir
        mock_unit_get.return_value = '10.0.0.1'
        project = 'openstack/neutron.git'
        cmds = gerrit.setup_gitreview(self.tmpdir, project)

        self.assertEquals([['git', 'add', '.gitreview'],
                           ['git', 'commit', '-a', '-m',
                            'Configured git-review to point to 10.0.0.1']],
                          cmds)
        with open(os.path.join(self.tmpdir, '.gitreview'), 'r') as fd:
            self.assertEqual(['[gerrit]\n', 'host=10.0.0.1\n', 'port=29418\n',
                              'project=%s\n' % (project)], fd.readlines())

    @mock.patch('tempfile.mkdtemp')
    @mock.patch('gerrit.unit_get')
    @mock.patch('gerrit.log')
    def test_setup_gitreview_already_exists(self, mock_log, mock_unit_get,
                                            mock_mkdtemp):
        mock_mkdtemp.return_value = self.tmpdir
        shutil.copy(os.path.join(gerrit.TEMPLATES, '.gitreview'), self.tmpdir)
        mock_unit_get.return_value = '10.0.0.1'
        project = 'openstack/neutron.git'
        cmds = gerrit.setup_gitreview(self.tmpdir, project)

        self.assertEquals([['git', 'commit', '-a', '-m',
                            'Configured git-review to point to 10.0.0.1']],
                          cmds)
        with open(os.path.join(self.tmpdir, '.gitreview'), 'r') as fd:
            self.assertEqual(['[gerrit]\n', 'host=10.0.0.1\n', 'port=29418\n',
                              'project=%s\n' % (project)], fd.readlines())

    @mock.patch('subprocess.check_output')
    @mock.patch('gerrit.log')
    def test_repo_is_initialised(self, mock_log, mock_check_output):
        branches = ['master']
        mock_check_output.return_value = LS_REMOTE_OUTPUT
        result = gerrit.repo_is_initialised('/foo/bar', branches)
        self.assertTrue(result)
