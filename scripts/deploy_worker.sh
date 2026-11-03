#!/bin/sh
# Deploy entry point for Cloudflare Workers Builds.
#
# Workers Builds runs the deploy command only for the production branch; every
# other branch runs its separate Preview command, which defaults to
# `npx wrangler preview`. A Preview needs its own bindings (a second D1 here),
# so that default fails on this Worker and every branch build shows red while
# `main` stays green. This script is safe in either slot — as the deploy command
# or as the Preview command — because it decides by branch:
#
#   production branch (default: main) -> wrangler deploy
#   any other branch                  -> wrangler versions upload
#
# `versions upload` stores a version and uploads nothing to production, so a
# branch build verifies the bundle without publishing the relay and without
# creating a preview URL pointed at the production D1 database. That is the
# same rule cloudflare/wrangler.build.toml already states with
# `preview_urls = false`; see docs/CLOUDFLARE_DEPLOYMENT.md.
#
# Environment:
#   WORKERS_CI_BRANCH             branch being built (set by Workers Builds)
#   GITHUB_REF_NAME              fallback when running under GitHub Actions
#   WORKERS_CI_PRODUCTION_BRANCH branch allowed to deploy (default: main)
#   WRANGLER                     command to run (default: npx wrangler)
#   WRANGLER_DRY_RUN             "1" appends --dry-run (used by CI and tests)
set -eu

CONFIG="cloudflare/wrangler.build.toml"
PRODUCTION_BRANCH="${WORKERS_CI_PRODUCTION_BRANCH:-main}"
BRANCH="${WORKERS_CI_BRANCH:-${GITHUB_REF_NAME:-}}"
WRANGLER="${WRANGLER:-npx wrangler}"

if [ ! -f "$CONFIG" ]; then
  echo "deploy_worker: $CONFIG is missing — run this from the repository root." >&2
  exit 2
fi

if [ -z "$BRANCH" ]; then
  # Guessing would be worse than stopping: an unknown branch must not be able to
  # deploy to production.
  echo "deploy_worker: no branch in WORKERS_CI_BRANCH or GITHUB_REF_NAME." >&2
  echo "deploy_worker: set WORKERS_CI_BRANCH, or pass the branch explicitly." >&2
  exit 2
fi

DRY_RUN=""
if [ "${WRANGLER_DRY_RUN:-0}" = "1" ]; then
  DRY_RUN="--dry-run"
fi

if [ "$BRANCH" = "$PRODUCTION_BRANCH" ]; then
  echo "deploy_worker: branch '$BRANCH' is the production branch — deploying the relay."
  # Printed so a build log (and CI) can see which command ran, not infer it.
  echo "deploy_worker: command: $WRANGLER deploy --config $CONFIG $DRY_RUN"
  # shellcheck disable=SC2086  # WRANGLER and DRY_RUN are deliberately word-split.
  $WRANGLER deploy --config "$CONFIG" $DRY_RUN
  exit $?
fi

echo "deploy_worker: branch '$BRANCH' is not '$PRODUCTION_BRANCH' — uploading a version only." >&2
echo "deploy_worker: nothing is deployed to production and no preview URL is created." >&2
echo "deploy_worker: command: $WRANGLER versions upload --config $CONFIG $DRY_RUN"
# shellcheck disable=SC2086
$WRANGLER versions upload --config "$CONFIG" $DRY_RUN
exit $?
