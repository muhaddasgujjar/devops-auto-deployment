ARG JENKINS_IMAGE
FROM ${JENKINS_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /home/jenkins/agent && chown jenkins:jenkins /home/jenkins/agent
COPY tools/docker /usr/local/bin/docker
COPY tools/docker-buildx /usr/local/lib/docker/cli-plugins/docker-buildx
COPY tools/trivy /usr/local/bin/trivy
RUN chmod 755 /usr/local/bin/docker /usr/local/bin/trivy /usr/local/lib/docker/cli-plugins/docker-buildx
USER jenkins
WORKDIR /home/jenkins/agent
