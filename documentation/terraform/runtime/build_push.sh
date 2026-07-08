#!/usr/bin/env bash
#
# build_push.sh — Build et push d'une image d'agent vers ECR (linux/arm64).
# Invoqué par Terraform (terraform_data.build_push) via local-exec.
#
# Variables d'environnement attendues :
#   AGENT_DIR    Répertoire source de l'agent (Dockerfile, agent.py, docagent/...)
#   ECR_URL      URL complète du repository ECR (sans tag)
#   IMAGE_TAG    Tag de l'image (= nom de l'agent)
#   AWS_REGION   Région AWS
#   AWS_PROFILE  (optionnel) profil AWS CLI
set -euo pipefail

: "${AGENT_DIR:?AGENT_DIR is required}"
: "${ECR_URL:?ECR_URL is required}"
: "${IMAGE_TAG:?IMAGE_TAG is required}"
: "${AWS_REGION:?AWS_REGION is required}"

REGISTRY="${ECR_URL%%/*}"

PROFILE_ARG=()
if [ -n "${AWS_PROFILE:-}" ]; then
  PROFILE_ARG=(--profile "$AWS_PROFILE")
else
  unset AWS_PROFILE
fi

echo "[build_push] Agent      : $IMAGE_TAG"
echo "[build_push] Source dir : $AGENT_DIR"
echo "[build_push] Target     : ${ECR_URL}:${IMAGE_TAG}"

if ! docker info >/dev/null 2>&1; then
  echo "[build_push] ERREUR: démon Docker inaccessible." >&2
  exit 1
fi

echo "[build_push] Authentification ECR ($REGISTRY)..."
aws ecr get-login-password --region "$AWS_REGION" "${PROFILE_ARG[@]}" \
  | docker login --username AWS --password-stdin "$REGISTRY"

if ! docker buildx inspect agentcore-builder >/dev/null 2>&1; then
  docker buildx create --name agentcore-builder --driver docker-container --bootstrap
fi
docker buildx use agentcore-builder

echo "[build_push] Build & push (linux/arm64)..."
docker buildx build \
  --platform linux/arm64 \
  --tag "${ECR_URL}:${IMAGE_TAG}" \
  --push \
  "$AGENT_DIR"

echo "[build_push] OK: ${ECR_URL}:${IMAGE_TAG}"
