#!/usr/bin/env bash
# Cloud Run 배포. .env 의 DB 설정을 읽어 환경변수로 넣고, 비밀번호만 Secret Manager 에 둔다.
#
#   ./deploy.sh                      # 배포
#   MIN_INSTANCES=1 ./deploy.sh      # 개봉일 전후: 콜드 스타트 방지
#
set -euo pipefail
cd "$(dirname "$0")"

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-asia-northeast3}"          # 서울. Supabase(ap-northeast-2)와 가깝다
SERVICE="${SERVICE:-pumpkin-api}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
SECRET="pumpkin-db-password"

set -a; . ./.env; set +a
: "${DB_HOST:?}" "${DB_USER:?}" "${DB_PASSWORD:?}"

echo "▶ project=$PROJECT region=$REGION service=$SERVICE min=$MIN_INSTANCES"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com --project "$PROJECT" -q

# 비밀번호는 Secret Manager 에. 이미 있으면 새 버전을 추가한다.
if gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
  printf '%s' "$DB_PASSWORD" | gcloud secrets versions add "$SECRET" --data-file=- --project "$PROJECT" -q
else
  printf '%s' "$DB_PASSWORD" | gcloud secrets create "$SECRET" --data-file=- --replication-policy=automatic --project "$PROJECT" -q
fi

# Cloud Run 기본 서비스 계정이 시크릿을 읽을 수 있게
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding "$SECRET" --project "$PROJECT" -q \
  --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" >/dev/null

# --source 배포는 같은 계정으로 Cloud Build 를 돌린다. 새 프로젝트는 이 권한이 없어서 실패한다.
gcloud projects add-iam-policy-binding "$PROJECT" -q \
  --member="serviceAccount:$SA" --role="roles/cloudbuild.builds.builder" >/dev/null

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated \
  --cpu 1 --memory 512Mi --concurrency 80 \
  --min-instances "$MIN_INSTANCES" --max-instances 10 \
  --set-env-vars "DB_HOST=$DB_HOST,DB_PORT=${DB_PORT:-6543},DB_USER=$DB_USER,DB_NAME=${DB_NAME:-postgres},DB_SSL=${DB_SSL:-true},DB_SCHEMA=${DB_SCHEMA:-pumpkin},COOKIE_SECURE=true,OPEN_AT=${OPEN_AT:-}" \
  --set-secrets "DB_PASSWORD=${SECRET}:latest" \
  -q

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')
echo "✔ $URL"
echo "  Cloudflare Workers 의 API_ORIGIN 에 위 주소를 넣어."
curl -fsS "$URL/api/health" && echo
