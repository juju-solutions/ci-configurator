import os
import mock
import json
import sys
import testtools
import gerrit
import tempfile
import shutil
import charmhelpers


class GerritTestCase(testtools.TestCase):

    def setUp(self):
        super(GerritTestCase, self).setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.pwd = os.getcwd()

    def tearDown(self):
        super(GerritTestCase, self).tearDown()
        shutil.rmtree(self.tmpdir)
        os.chdir(self.pwd)
        
    @mock.patch('gerrit.unit_get')
    @mock.patch('gerrit.log')
    def test_setup_gitreview(self, mock_log, mock_unit_get):
        tpath = os.path.join(self.pwd, gerrit.TEMPLATES)
        os.chdir(self.tmpdir)
        os.mkdir(gerrit.TEMPLATES)
        shutil.copy(os.path.join(tpath, '.gitreview'), gerrit.TEMPLATES)
        mock_unit_get.return_value = '10.0.0.1'
        
        cmds = gerrit.setup_gitreview('openstack/neutron')
        
        self.assertEquals([['git', 'add', '.gitreview'],
                           ['git', 'commit', '-a', '-m',
                            'Configured git-review to point to 10.0.0.1']],
                          cmds)
        with open('.gitreview', 'r') as fd:
            self.assertEqual(['[gerrit]\n', 'host=10.0.0.1\n', 'port=29418\n',
                              'project=openstack/neutron'], fd.readlines())

    @mock.patch('gerrit.unit_get')
    @mock.patch('gerrit.log')
    def test_setup_gitreview_already_exists(self, mock_log, mock_unit_get):
        tpath = os.path.join(self.pwd, gerrit.TEMPLATES)
        os.chdir(self.tmpdir)
        os.mkdir(gerrit.TEMPLATES)
        shutil.copy(os.path.join(tpath, '.gitreview'), gerrit.TEMPLATES)
        shutil.copy(os.path.join(tpath, '.gitreview'), self.tmpdir)
        mock_unit_get.return_value = '10.0.0.1'
        
        cmds = gerrit.setup_gitreview('openstack/neutron')
        
        self.assertEquals([['git', 'commit', '-a', '-m',
                            'Configured git-review to point to 10.0.0.1']],
                          cmds)
        with open('.gitreview', 'r') as fd:
            self.assertEqual(['[gerrit]\n', 'host=10.0.0.1\n', 'port=29418\n',
                              'project=openstack/neutron'], fd.readlines())

