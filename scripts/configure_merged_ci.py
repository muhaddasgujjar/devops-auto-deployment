"""Configure one reviewed acceptance job; disable legacy polling before agent start."""
import argparse
import base64
import json
import re
from urllib.parse import urlencode

from scripts.gitops_trial import Jenkins
from scripts.render_release import ROOT


def configuration(source_sha):
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Use a full trusted source commit")
    pipeline = (ROOT / "ci/Jenkinsfile.acceptance").read_text().replace("__SOURCE_SHA__", source_sha)
    encoded = base64.b64encode(pipeline.encode()).decode()
    return '''
import jenkins.model.Jenkins
import hudson.model.*
import org.jenkinsci.plugins.workflow.job.WorkflowJob
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition
import org.jenkinsci.plugins.workflow.job.properties.PipelineTriggersJobProperty
def j = Jenkins.get()
['release-main','release-local'].each { name ->
  def old = j.getItem(name)
  if (old != null) {
    old.setDisabled(true)
    old.removeProperty(PipelineTriggersJobProperty)
    old.save()
  }
}
j.queue.items.findAll { it.task.name in ['release-main','release-local'] }.each { j.queue.cancel(it) }
def job = j.getItem('release-merged') ?: j.createProject(WorkflowJob, 'release-merged')
if (job.isBuilding()) { throw new IllegalStateException('Acceptance job is running; refusing reconfiguration') }
job.addProperty(new ParametersDefinitionProperty(
  new ChoiceParameterDefinition('DEMO_MODE','healthy\\nerror\\nlatency\\nstartup','Candidate mode'),
  new BooleanParameterDefinition('FAIL_TEST_GATE',false,'Intentional negative unittest gate')))
job.setDefinition(new CpsFlowDefinition(new String(''' + "'" + encoded + "'" + '''.decodeBase64(),'UTF-8'),true))
job.setDisabled(false)
job.save()
println('Configured release-merged; legacy jobs disabled')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    script = configuration(args.source_sha)
    client = Jenkins()
    crumb = client.json("crumbIssuer/api/json")
    content, _ = client.request("scriptText", urlencode({"script": script}).encode(),
                               {crumb["crumbRequestField"]: crumb["crumb"],
                                "Content-Type": "application/x-www-form-urlencoded"})
    if content.decode().strip() != 'Configured release-merged; legacy jobs disabled':
        raise RuntimeError("Jenkins configuration failed; inspect authenticated script diagnostics locally")
    print(json.dumps({"job": "release-merged", "source_commit": args.source_sha,
                      "legacy_polling_disabled": True}))


if __name__ == "__main__":
    main()
