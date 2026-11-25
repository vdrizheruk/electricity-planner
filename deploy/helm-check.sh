#!/usr/bin/env bash
# Lint the chart and render it for the supported setups; validate the manifests with kubeconform
# when it is installed. Usage: deploy/helm-check.sh   (needs helm 3.x)
set -euo pipefail
cd "$(dirname "$0")/.."
chart=charts/electricity-planner
kube=${KUBE_VERSION:-1.30.0}
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT

render() { # name, helm args...
  local name=$1; shift
  helm lint "$chart" "$@" >/dev/null
  helm template planner "$chart" --kube-version "$kube" --namespace planner "$@" >"$out/$name.yaml"
  echo "rendered: $name"
}

render external-db   --set database.url=postgres://u:p@db:5432/planner
render builtin-db    --set postgresql.enabled=true --set ingress.enabled=true \
                     --set 'ingress.hosts={planner.example.com}' \
                     --set 'ingress.tls[0].secretName=tls' --set 'ingress.tls[0].hosts={planner.example.com}'
render existing-secret --set secret.existingSecret=planner-secrets --set backend.autoscaling.enabled=true \
                     --set backend.podDisruptionBudget.enabled=true --set frontend.podDisruptionBudget.enabled=true \
                     --set migrations.enabled=false
render gke           -f "$chart/values-gke.yaml"

if command -v kubeconform >/dev/null; then
  kubeconform -strict -summary -kubernetes-version "$kube" "$out"/*.yaml
else
  echo "kubeconform not installed: manifests are not schema-validated" >&2
fi

# The migration Job must exist exactly once and run before the rollout on upgrades.
grep -q 'helm.sh/hook: .*pre-upgrade' "$out/external-db.yaml"
grep -q 'RUN_MIGRATIONS' "$out/external-db.yaml"
echo "helm chart OK"
