ARG JENKINS_IMAGE
FROM ${JENKINS_IMAGE}
COPY ci/plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
COPY ci/bootstrap.groovy /usr/share/jenkins/ref/init.groovy.d/release-lab.groovy
