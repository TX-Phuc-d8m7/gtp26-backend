#!/bin/bash
set -e

PROJECT_ID=$(gcloud config get-value project)
REGION="asia-southeast1"
SERVICE="food-ai-backend"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/food-ai/backend:latest"
CLOUD_SQL="${PROJECT_ID}:${REGION}:food-ai-db"

SYNC_TAGS=false
SYNC_FOODS=false
SKIP_BUILD=false

for arg in "$@"; do
  case $arg in
    --sync-tags)  SYNC_TAGS=true ;;
    --sync-foods) SYNC_FOODS=true ;;
    --no-build)   SKIP_BUILD=true ;;
  esac
done

RUN_SEED=false
if [ "$SYNC_TAGS" = "true" ] || [ "$SYNC_FOODS" = "true" ]; then
  RUN_SEED=true
fi

if [ "$SKIP_BUILD" = "false" ]; then
  echo "Building Docker image..."
  gcloud builds submit --tag "$IMAGE" .
fi

echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=3 \
  --add-cloudsql-instances="$CLOUD_SQL" \
  --set-env-vars="DB_HOST=/cloudsql/${CLOUD_SQL},DB_PORT=5432,DB_USERNAME=app_user,DB_NAME=food_ai_db" \
  --set-env-vars="PROJECT_ID=${PROJECT_ID}" \
  --set-env-vars="GCS_BUCKET_NAME=food-ai-media-1d1e4159,GCS_FOOD_IMAGE_PREFIX=foods/" \
  --set-env-vars="GEMINI_TEXT_MODEL=gemini-2.5-flash-lite,PLACES_CACHE_TTL_DAYS=7" \
  --set-env-vars="EMBEDDING_BACKFILL_LIMIT=0" \
  --set-env-vars="RUN_SEED_ON_STARTUP=${RUN_SEED},SYNC_TAGS_ON_STARTUP=${SYNC_TAGS}" \
  --set-env-vars="SYNC_FOODS_ON_STARTUP=${SYNC_FOODS},RUN_EMBEDDING_ON_STARTUP=false" \
  --set-secrets="JWT_SECRET_KEY=JWT_SECRET_KEY:latest,DB_PASSWORD=DB_PASSWORD:latest,SERPAPI_API_KEY=SERPAPI_API_KEY:latest"

if [ "$RUN_SEED" = "true" ]; then
  echo "Waiting 40s for sync to complete..."
  sleep 40
  echo "Resetting sync flags..."
  gcloud run services update "$SERVICE" \
    --region="$REGION" \
    --update-env-vars="RUN_SEED_ON_STARTUP=false,SYNC_TAGS_ON_STARTUP=false,SYNC_FOODS_ON_STARTUP=false"
  echo "Sync flags reset."
fi

echo "Done. Service URL: https://${SERVICE}-${PROJECT_ID#project-}.${REGION}.run.app"
