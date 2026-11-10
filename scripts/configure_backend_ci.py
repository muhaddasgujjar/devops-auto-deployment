"""Configure only the reviewed backend-gate job; leave the proven demo job unchanged."""
import argparse
import base64
import json
import re
import subprocess
from urllib.parse import urlencode

from scripts.gitops_trial import Jenkins
from scripts.render_release import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sha', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}', args.source_sha):
        parser.error('Use a full reviewed commit')
    pipeline = subprocess.check_output(['git', '-C', str(ROOT), 'show', args.source_sha + ':ci/Jenkinsfile.backend'], text=True)
    encoded = base64.b64encode(pipeline.replace('__SOURCE_SHA__', args.source_sha).encode()).decode()
    script = '''
import jenkins.model.Jenkins
import hudson.model.*
import org.jenkinsci.plugins.workflow.job.WorkflowJob
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition
def j = Jenkins.get()
def job = j.getItem('backend-gate') ?: j.createProject(WorkflowJob, 'backend-gate')
if (job.isBuilding()) { throw new IllegalStateException('Backend job is running') }
job.addProperty(new ParametersDefinitionProperty(new BooleanParameterDefinition('FAIL_TEST_GATE',false,'Intentional local gate failure')))
job.setDefinition(new CpsFlowDefinition(new String('__PIPELINE__'.decodeBase64(),'UTF-8'),true))
job.setDisabled(false)
job.save()
println('Configured backend-gate')
'''.replace('__PIPELINE__', encoded)
    client = Jenkins()
    client.wait_ready()
    crumb = client.json('crumbIssuer/api/json')
    content, _ = client.request('scriptText', urlencode({'script': script}).encode(),
        {crumb['crumbRequestField']: crumb['crumb'], 'Content-Type': 'application/x-www-form-urlencoded'})
    if content.decode().strip() != 'Configured backend-gate':
        raise RuntimeError('Backend job configuration failed')
    print(json.dumps({'job': 'backend-gate', 'source_commit': args.source_sha}))


if __name__ == '__main__':
    main()
