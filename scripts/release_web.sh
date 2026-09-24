#!/bin/bash
# Build the web page and publish it as a GitHub release (run on the dev machine).
#   bash scripts/release_web.sh
# deploy.sh on the server downloads the newest web-* release whose commit is part
# of the deployed code — see docs/design/web-service.md → "Web release & deploy".
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

for cmd in git gh npm tar sha256sum; do
    command -v "$cmd" &>/dev/null || { echo "Missing: $cmd"; exit 1; }
done

# Every release must match a real, pushed commit
if [ -n "$(git status --porcelain)" ]; then
    echo "Working tree not clean — commit or stash first."
    exit 1
fi
git fetch --quiet origin
SHA="$(git rev-parse HEAD)"
SHORT="$(git rev-parse --short HEAD)"
if ! git merge-base --is-ancestor "$SHA" origin/main; then
    echo "HEAD $SHORT is not on origin/main — push it first."
    exit 1
fi

TAG="web-$(date +%Y%m%d)-$SHORT"
if gh release view "$TAG" &>/dev/null; then
    echo "Release $TAG already exists."
    exit 1
fi

echo "Building web page at $SHORT …"
(cd web && npm ci --no-audit --no-fund && npm run build)

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
ARCHIVE="web-$SHORT.tar.gz"
tar -czf "$OUT/$ARCHIVE" -C web/www .
(cd "$OUT" && sha256sum "$ARCHIVE" > "$ARCHIVE.sha256")

gh release create "$TAG" "$OUT/$ARCHIVE" "$OUT/$ARCHIVE.sha256" \
    --target "$SHA" \
    --title "Web page $SHORT" \
    --notes "Web page build of commit $SHA. Installed automatically by scripts/deploy.sh."

echo "Published $TAG. Deploy on the server: git pull && sudo ./scripts/deploy.sh"
