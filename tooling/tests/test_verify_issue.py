import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
from verify_issue import verify

class IssueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        folder = self.root/'specs/007-example';folder.mkdir(parents=True)
        (folder/'spec.md').write_text('---\nid: 007-example\nissue: 7\nowner: ACAurafly\n---\n')
        self.event = self.root/'event.json'
        self.event.write_text(json.dumps({'pull_request':{'body':'Spec: specs/007-example'}}))
    def test_real_issue_is_accepted(self):
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"number":7}')) as request:
            verify(self.event,self.root,'ACAurafly/company-network','test-token')
        self.assertTrue(request.call_args.args[0].full_url.endswith('/issues/7'))
    def test_pr_number_is_not_accepted_as_issue(self):
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"number":7,"pull_request":{}}')):
            with self.assertRaisesRegex(ValueError,'not a pull request'):
                verify(self.event,self.root,'ACAurafly/company-network','test-token')
    def test_invalid_repository_is_rejected_before_network(self):
        with patch('urllib.request.urlopen') as request:
            with self.assertRaisesRegex(ValueError,'repository'):
                verify(self.event,self.root,'../outside','test-token')
        request.assert_not_called()

if __name__ == '__main__': unittest.main()
