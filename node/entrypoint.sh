#!/bin/sh
# Clone on first start, then run the witness loop.
set -eu
: "${OM_WITNESS_REMOTE:?set OM_WITNESS_REMOTE, e.g. https://github.com/openmasonry/openmasonry.git}"
REPO="${OM_WITNESS_REPO:-/data/openmasonry}"
if [ -n "${GH_TOKEN:-}" ]; then
  gh auth setup-git >/dev/null 2>&1 || true
fi
if [ ! -d "$REPO/.git" ]; then
  git clone --quiet "$OM_WITNESS_REMOTE" "$REPO"
fi
git -C "$REPO" config user.name "witness-${OM_WITNESS_NAME}"
git -C "$REPO" config user.email "witness-${OM_WITNESS_NAME}@users.noreply.github.com"
exec python /home/tyler/witness.py
