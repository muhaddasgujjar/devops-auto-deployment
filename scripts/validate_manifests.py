"""Validate against official, pinned upstream schemas. Needs requirements-validation.txt."""
import json
import tempfile
from pathlib import Path
from urllib.request import urlopen

import jsonschema
import yaml

from scripts.render_release import ROOT, render

CACHE = ROOT / ".tools" / "schemas"


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    import hashlib
    target = CACHE / hashlib.sha256(url.encode()).hexdigest()
    if not target.exists():
        with urlopen(url, timeout=30) as response:
            target.write_bytes(response.read())
    return yaml.safe_load(target.read_text(encoding="utf-8"))


def strict(schema):
    """Reject undeclared CRD fields, matching Kubernetes structural-schema pruning."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            if not schema.get("x-kubernetes-preserve-unknown-fields"):
                schema.setdefault("additionalProperties", False)
        for value in schema.values():
            strict(value)
    elif isinstance(schema, list):
        for value in schema:
            strict(value)
    return schema


def main():
    versions = json.loads((ROOT / "versions.json").read_text())
    docker_from = next(line[5:].strip() for line in (ROOT / "demo/Dockerfile").read_text().splitlines() if line.startswith("FROM "))
    if docker_from != versions["python_image"]:
        raise ValueError("Dockerfile base image does not match versions.json")
    rollouts = versions["argo_rollouts"]
    argo = versions["argo_cd"]
    schemas = {}
    for kind, url in {
        "Rollout": f"https://raw.githubusercontent.com/argoproj/argo-rollouts/{rollouts}/manifests/crds/rollout-crd.yaml",
        "AnalysisTemplate": f"https://raw.githubusercontent.com/argoproj/argo-rollouts/{rollouts}/manifests/crds/analysis-template-crd.yaml",
        "Application": f"https://raw.githubusercontent.com/argoproj/argo-cd/{argo}/manifests/crds/application-crd.yaml",
        "AppProject": f"https://raw.githubusercontent.com/argoproj/argo-cd/{argo}/manifests/crds/appproject-crd.yaml",
    }.items():
        crd = fetch(url)
        version = next(v for v in crd["spec"]["versions"] if v["storage"])
        schema = version["schema"]["openAPIV3Schema"]
        # ObjectMeta is validated by Kubernetes separately and omitted from CRDs.
        schema["properties"]["metadata"] = {"type": "object"}
        schemas[kind] = strict(schema)
    k3d_schema = fetch(f'https://raw.githubusercontent.com/k3d-io/k3d/{versions["k3d"]}/pkg/config/v1alpha5/schema.json')
    k3d_config = yaml.safe_load((ROOT / "platform/k3d.yaml").read_text())
    jsonschema.Draft7Validator(k3d_schema).validate(k3d_config)
    if k3d_config["image"] != versions["k3s_image"]:
        raise ValueError("k3d server image does not match versions.json")
    k8s_version = versions["k3s_image"].split(":")[1].split("-k3s")[0]
    swagger = fetch(f"https://raw.githubusercontent.com/kubernetes/kubernetes/{k8s_version}/api/openapi-spec/swagger.json")
    # OpenAPI v2 encodes Kubernetes IntOrString as a custom string format.
    # General JSON Schema validators need its actual two accepted JSON types.
    swagger["definitions"]["io.k8s.apimachinery.pkg.util.intstr.IntOrString"] = {
        "anyOf": [{"type": "integer"}, {"type": "string"}]
    }
    builtin = {}
    for name, definition in swagger["definitions"].items():
        for gvk in definition.get("x-kubernetes-group-version-kind", []):
            api = f'{gvk["group"]}/{gvk["version"]}' if gvk["group"] else gvk["version"]
            builtin[(api, gvk["kind"])] = name
    checked = 1
    with tempfile.TemporaryDirectory() as directory:
        release = Path(directory) / "release"
        baseline = Path(directory) / "baseline"
        image = "localhost:5001/release-demo@sha256:" + "a" * 64
        render(image, "b" * 40, release)
        render(image, "b" * 40, baseline, baseline=True)
        paths = [*release.glob("*.yaml"), *baseline.glob("*.yaml"),
                 ROOT / "platform/monitoring.yaml", ROOT / "platform/storage.yaml", ROOT / "platform/argocd/application.yaml"]
        for path in paths:
            for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "prometheus":
                    if doc["spec"]["template"]["spec"]["containers"][0]["image"] != versions["prometheus_image"]:
                        raise ValueError("Prometheus image does not match versions.json")
                if doc["kind"] in schemas:
                    validator = jsonschema.Draft4Validator(schemas[doc["kind"]])
                else:
                    name = builtin[(doc["apiVersion"], doc["kind"])]
                    validator = jsonschema.Draft4Validator({"$ref": f"#/definitions/{name}", "definitions": swagger["definitions"]})
                errors = list(validator.iter_errors(doc))
                if errors:
                    raise ValueError(f"{path.name}/{doc['kind']}: {errors[0].message}")
                checked += 1
    print(f"Validated {checked} resource/config documents against pinned upstream schemas.")


if __name__ == "__main__":
    main()
