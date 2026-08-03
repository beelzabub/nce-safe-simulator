#!/bin/sh
# Print the immutable tag of the image currently tagged :latest in ECR.
#
# ecr-push tags every image twice: :latest (convenience pointer) and
# :<VERSION>-<short-sha> (immutable). Deploy targets call this script to pin
# the Helm release to the immutable tag of whatever :latest points at, so the
# release is reproducible and helm rollback returns the previous image
# (issue #290). Reading the tag back from ECR — rather than recomputing it
# from the working tree — keeps deploys correct when HEAD has moved past the
# last push (eks-full-redeploy reuses the current ECR image by design).
set -eu
REPO="${1:?usage: resolve-image-tag.sh <repository> <region>}"
REGION="${2:?usage: resolve-image-tag.sh <repository> <region>}"

TAGS=$(aws ecr describe-images --repository-name "$REPO" --region "$REGION" \
  --image-ids imageTag=latest --query 'imageDetails[0].imageTags' --output text 2>/dev/null) || {
  echo "ERROR: cannot read the :latest image from ECR repository '$REPO'" \
       "— push one first with 'make ecr-push'" >&2
  exit 1
}

for TAG in $TAGS; do
  if [ "$TAG" != "latest" ]; then
    echo "$TAG"
    exit 0
  fi
done

echo "ERROR: the :latest image in '$REPO' carries no immutable tag" \
     "— it predates issue #290; re-push with 'make ecr-push'" >&2
exit 1
