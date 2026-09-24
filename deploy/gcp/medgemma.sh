#!/usr/bin/env bash
# Deploy Google's MedGemma from Vertex AI Model Garden and let Bioverse One use it.
#
#   ./deploy/gcp/medgemma.sh            # deploy (15-30 minutes the first time), then run deploy.sh
#   ./deploy/gcp/medgemma.sh --status   # show the endpoint
#   ./deploy/gcp/medgemma.sh --delete   # undeploy and delete the endpoint (stops the GPU bill)
#
#   MEDGEMMA_MODEL=google/medgemma@medgemma-27b-it ./deploy/gcp/medgemma.sh   # larger, multimodal
#
# The endpoint runs on a GPU around the clock and bills for every hour it exists, even with no traffic.
# The default 4B multimodal model fits one NVIDIA L4. The 27B models need much larger GPUs.
# MedGemma is released under the Health AI Developer Foundations terms, which --accept-eula accepts for
# you; read them first. It is a developer model: validate it before any clinical use.
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
G=(--project "${PROJECT_ID}" --region "${MEDGEMMA_REGION}")

endpoint_name() {
  gcloud ai endpoints list "${G[@]}" --filter="displayName=${MEDGEMMA_ENDPOINT_NAME}" \
    --format="value(name)" 2>/dev/null | head -1
}

case "${1:-}" in
  --status)
    ep="$(endpoint_name)"
    [[ -z "${ep}" ]] && { echo "No MedGemma endpoint '${MEDGEMMA_ENDPOINT_NAME}' in ${MEDGEMMA_REGION}."; exit 0; }
    gcloud ai endpoints describe "${ep##*/}" "${G[@]}" \
      --format="table(displayName,deployedModels[].displayName,deployedModels[].dedicatedResources.machineSpec.acceleratorType,dedicatedEndpointDns)"
    exit 0 ;;
  --delete)
    ep="$(endpoint_name)"
    [[ -z "${ep}" ]] && { echo "Nothing to delete."; exit 0; }
    id="${ep##*/}"
    for dm in $(gcloud ai endpoints describe "${id}" "${G[@]}" --format="value(deployedModels[].id)" | tr ';' ' '); do
      gcloud ai endpoints undeploy-model "${id}" "${G[@]}" --deployed-model-id="${dm}" --quiet
    done
    gcloud ai endpoints delete "${id}" "${G[@]}" --quiet
    echo "Deleted. Run ./deploy/gcp/deploy.sh so the app stops calling it."
    exit 0 ;;
esac

say "Vertex AI API"
gcloud services enable aiplatform.googleapis.com --project "${PROJECT_ID}"

say "Runtime account may call the endpoint (Vertex AI User)"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/aiplatform.user" --condition=None >/dev/null
echo "Granted roles/aiplatform.user to ${RUNTIME_SA}"

if [[ -n "$(endpoint_name)" ]]; then
  say "Endpoint '${MEDGEMMA_ENDPOINT_NAME}' already exists"
else
  say "Deploying ${MEDGEMMA_MODEL} (this takes a while)"
  if ! gcloud ai model-garden models deploy --model="${MEDGEMMA_MODEL}" "${G[@]}" \
       --endpoint-display-name="${MEDGEMMA_ENDPOINT_NAME}" --accept-eula; then
    echo >&2
    echo "Deployment failed. Check the model name and your GPU quota:" >&2
    echo "  gcloud ai model-garden models list --model-filter=medgemma --project ${PROJECT_ID}" >&2
    echo "  gcloud ai model-garden models list-deployment-config --model=${MEDGEMMA_MODEL} --project ${PROJECT_ID}" >&2
    echo "Or deploy from the console, naming the endpoint '${MEDGEMMA_ENDPOINT_NAME}':" >&2
    echo "  https://console.cloud.google.com/vertex-ai/publishers/google/model-garden/medgemma?project=${PROJECT_ID}" >&2
    exit 1
  fi
fi

ep="$(endpoint_name)"
[[ -z "${ep}" ]] && { echo "The endpoint is not listed yet. Run ./deploy/gcp/medgemma.sh --status in a few minutes." >&2; exit 1; }
say "Ready: ${ep}"
echo "Now run ./deploy/gcp/deploy.sh. It finds this endpoint and switches the app's AI to MedGemma."
