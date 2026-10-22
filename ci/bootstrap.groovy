import jenkins.model.Jenkins
import hudson.model.*
import hudson.security.*
import hudson.slaves.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.Domain
import com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl
import com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey
import org.jenkinsci.plugins.workflow.job.WorkflowJob
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition
import org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition
import org.jenkinsci.plugins.workflow.job.properties.PipelineTriggersJobProperty
import hudson.plugins.git.GitSCM
import hudson.plugins.git.BranchSpec
import hudson.plugins.git.UserRemoteConfig
import hudson.triggers.SCMTrigger

def j = Jenkins.get()
def repoUrl = System.getenv('RELEASE_ENV_REPO_URL') ?: new File('/run/release-secrets/environment-url').text.trim()
jenkins.model.JenkinsLocationConfiguration.get().setUrl('http://127.0.0.1:8082/')
j.setNumExecutors(0)
j.setSlaveAgentPort(-1)
j.getGlobalNodeProperties().replace(new EnvironmentVariablesNodeProperty(
  new EnvironmentVariablesNodeProperty.Entry('RELEASE_ENV_REPO_URL', repoUrl)))
def secrets = new File('/run/release-secrets')
def realm = new HudsonPrivateSecurityRealm(false)
realm.createAccount('release-admin', new File(secrets, 'jenkins-password').text.trim())
j.setSecurityRealm(realm)
def auth = new FullControlOnceLoggedInAuthorizationStrategy()
auth.setAllowAnonymousRead(false)
j.setAuthorizationStrategy(auth)
def store = SystemCredentialsProvider.getInstance().getStore()
if (!SystemCredentialsProvider.getInstance().getCredentials().any { it.id == 'environment-git-ssh' }) {
  store.addCredentials(Domain.global(), new BasicSSHUserPrivateKey(CredentialsScope.GLOBAL,
    'environment-git-ssh', 'release-git',
    new BasicSSHUserPrivateKey.DirectEntryPrivateKeySource(new File(secrets, 'environment-write').text), '', 'Local environment write key'))
}
def node = j.getNode('release-linux')
if (node == null) {
  node = new DumbSlave('release-linux', '/home/jenkins/agent', new JNLPLauncher())
  node.setNumExecutors(1)
  node.setLabelString('trusted-linux-docker')
  node.setMode(Node.Mode.EXCLUSIVE)
  node.setRetentionStrategy(new RetentionStrategy.Always())
  j.addNode(node)
}
// Local acceptance uses a read-only snapshot of this checkout. Production uses SCM.
if (true) {
  def job = j.getItem('release-local') ?: j.createProject(WorkflowJob, 'release-local')
  job.addProperty(new ParametersDefinitionProperty(new ChoiceParameterDefinition('DEMO_MODE', 'healthy\nerror\nlatency\nstartup', 'Candidate mode')))
  job.setDefinition(new CpsFlowDefinition(new File('/opt/release-source/ci/Jenkinsfile.local').text, true))
  job.save()
}
if (true) {
  def job = j.getItem('release-main') ?: j.createProject(WorkflowJob, 'release-main')
  // Repair a partially-created job after an interrupted initial setup as well.
  if (job.getDefinition() == null) { job.setDisabled(true) }
  def scm = new GitSCM(
    [new UserRemoteConfig('https://github.com/muhaddasgujjar/devops-auto-deployment.git', null, null, null)],
    [new BranchSpec('*/main')], null, null, [])
  job.setDefinition(new CpsScmFlowDefinition(scm, 'ci/Jenkinsfile'))
  job.addProperty(new ParametersDefinitionProperty(
    new ChoiceParameterDefinition('DEMO_MODE', 'healthy\nerror\nlatency\nstartup', 'Candidate mode'),
    new StringParameterDefinition('IMAGE_REPOSITORY', 'localhost:5001/release-demo'),
    new StringParameterDefinition('ENV_REPO_URL', repoUrl)))
  job.addProperty(new PipelineTriggersJobProperty([new SCMTrigger('H/2 * * * *')]))
  job.save()
}
j.save()
new File(secrets, 'agent-secret').text = node.toComputer().getJnlpMac()
return null
