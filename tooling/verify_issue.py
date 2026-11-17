"""Check that the selected PR specification links an actual Issue in this repository."""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from sdd import metadata, selected_spec

def verify(event_path, root, repository, token, api_url='https://api.github.com'):
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    body = event['pull_request'].get('body') or ''
    matches = re.findall(r'^Spec:\s*(specs/[a-z0-9][a-z0-9-]*)\s*$',body,re.M)
    if len(matches) != 1: raise ValueError('PR requires exactly one Spec: reference')
    directory = selected_spec(root,matches[0])
    issue = metadata((directory/'spec.md').read_text(encoding="utf-8")).get('issue')
    if type(issue) is not int or issue < 1: raise ValueError('A positive Issue number is required')
    if not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*/[A-Za-z0-9][A-Za-z0-9_.-]*',repository): raise ValueError('Invalid repository')
    request = urllib.request.Request(f'{api_url.rstrip("/")}/repos/{repository}/issues/{issue}',headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json','User-Agent':'Company-Network-SDD'})
    with urllib.request.urlopen(request,timeout=30) as response: data = json.load(response)
    if data.get('number') != issue or 'pull_request' in data:
        raise ValueError('Specification must link an Issue, not a pull request')
    print(f'Issue verified: {repository}#{issue}')

if __name__ == '__main__':
    try:
        verify(sys.argv[1],Path(__file__).resolve().parents[1],os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_TOKEN'],os.environ.get('GITHUB_API_URL','https://api.github.com'))
    except (ValueError,KeyError,OSError,urllib.error.URLError) as exc:
        print(f'Issue verification failed: {exc}',file=sys.stderr);raise SystemExit(1)
