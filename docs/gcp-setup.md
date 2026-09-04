# Google Cloud setup

The ReelOps project is provisioned. This records what exists, how to recreate it, and what only a human can do.

## What exists

| Resource | Value |
| --- | --- |
| Project | `reelops-agentic-cinema` (number `494976096442`) |
| Region | `us-central1` |
| Firestore | `(default)`, Native mode, `us-central1` — **location is permanent** |
| Runtime service account | `reelops-agent@reelops-agentic-cinema.iam.gserviceaccount.com` |
| Artifact Registry | `us-central1-docker.pkg.dev/reelops-agentic-cinema/reelops` |
| Secrets | `grafana-service-account-token`, `otel-exporter-otlp-headers` |

Enabled APIs: `aiplatform`, `firestore`, `run`, `cloudbuild`, `artifactregistry`, `secretmanager`, `iam`, `logging`.

Service account roles: `datastore.user`, `secretmanager.secretAccessor`, `aiplatform.user`, `logging.logWriter` — the least privilege the runtime needs. No service account keys exist; Cloud Run assumes the identity directly, which is why there is no key file to leak.

Verified working: `gemini-2.5-flash` through Vertex AI in this project.

## Reproduce from scratch

```sh
PROJECT=reelops-agentic-cinema
REGION=us-central1
BILLING=<your billing account id>

gcloud projects create $PROJECT --name="ReelOps"
gcloud billing projects link $PROJECT --billing-account=$BILLING

gcloud services enable \
  aiplatform.googleapis.com firestore.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com logging.googleapis.com \
  --project=$PROJECT

# Firestore returns "Permission denied on resource or it may not exist" for a
# few minutes after the API is enabled, on a project you own. It is the service
# agent still provisioning, not an IAM problem. Retry.
gcloud firestore databases create --location=$REGION --type=firestore-native --project=$PROJECT

gcloud iam service-accounts create reelops-agent \
  --display-name="ReelOps agent runtime" --project=$PROJECT

SA=reelops-agent@$PROJECT.iam.gserviceaccount.com
for role in roles/datastore.user roles/secretmanager.secretAccessor \
            roles/aiplatform.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:$SA" --role="$role" --condition=None
done

gcloud artifacts repositories create reelops \
  --repository-format=docker --location=$REGION --project=$PROJECT

gcloud secrets create grafana-service-account-token --replication-policy=automatic --project=$PROJECT
gcloud secrets create otel-exporter-otlp-headers   --replication-policy=automatic --project=$PROJECT
```

## Remaining human steps

The secrets exist but hold no versions yet. Add them once `grafana-setup.md` has produced the values:

```sh
printf %s "<grafana service account token>" | \
  gcloud secrets versions add grafana-service-account-token --data-file=- --project=reelops-agentic-cinema

printf %s "<Basic base64 instanceID:token>" | \
  gcloud secrets versions add otel-exporter-otlp-headers --data-file=- --project=reelops-agentic-cinema
```

`printf` rather than `echo` — a trailing newline inside a credential produces authentication failures that look like a bad token.

To make this the default project for your shell, and to point local application credentials at it for quota and billing:

```sh
gcloud config set project reelops-agentic-cinema
gcloud auth application-default set-quota-project reelops-agentic-cinema
```

## Gemini access

ADK reaches Gemini through Vertex AI rather than an AI Studio API key, so the runtime authenticates with the service account and no key material is involved:

```sh
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=reelops-agentic-cinema
GOOGLE_CLOUD_LOCATION=us-central1
```

## Cost

Firestore and Cloud Run have free tiers this project will not exhaust. Vertex AI bills per token, and Artifact Registry bills for image storage — both small at demo scale, and both real. Delete the project when the hackathon ends:

```sh
gcloud projects delete reelops-agentic-cinema
```

Deletion is recoverable for 30 days.
