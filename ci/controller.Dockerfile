ARG JENKINS_IMAGE
FROM ${JENKINS_IMAGE}
COPY ci/plugins.txt /usr/share/jenkins/ref/plugins.txt
COPY ci/plugins.lock.txt /usr/share/jenkins/ref/plugins.lock.txt
COPY ci/plugins.sha256 /usr/share/jenkins/ref/plugins.sha256
RUN jenkins-plugin-cli --latest=false --plugin-file /usr/share/jenkins/ref/plugins.lock.txt \
    && cd /usr/share/jenkins/ref/plugins && sha256sum --check ../plugins.sha256
COPY ci/bootstrap.groovy /usr/share/jenkins/ref/init.groovy.d/release-lab.groovy
