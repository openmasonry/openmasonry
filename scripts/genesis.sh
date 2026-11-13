#!/usr/bin/env sh
# The Founding Ceremony, step 1: draft the genesis (validated by the protocol; nothing is signed).
#
# Read docs/operations/LAUNCH.md first: without --custodian the ledger is founded with no Custodian,
# and no correction exists on it until a founder claims the office. Nothing in entry 0 can be
# corrected afterwards.
#
#   scripts/genesis.sh --name NAME --login LOGIN --github-id N --key KEY \
#       --custodian NAME:KEY.pub:REVOKE.pub[:MEMBER_LOGIN] [--custodian-threshold N] \
#       [--cofounder LOGIN:KEY.pub[:ID] --cofounder-proof LOGIN:FILE ...] \
#       [--witness NAME:KEY.pub --witness-proof NAME:FILE ...]
#
#   (for the canonical ceremony: --login openmasonry --github-id 355316448 --key "$OM_KEY", from the shell the
#    pre-flight of docs/operations/LAUNCH.md prepared; --login and --key default to $OM_LOGIN and $OM_KEY)
#
#   (a cofounder makes their proof with `bin/om proof founder LOGIN --github-id N --key PATH --out FILE`,
#    a witness operator with `bin/om proof witness NAME --key PATH --out FILE`; both private keys of
#    each custodian must be readable when the draft is approved)
#
# Step 2, approve it in the system dialog (signs entry 0 and opens the pull request):
#
#   bin/om approve <digest printed by step 1>
#
# The script refuses to run without --custodian, and anywhere but a clean checkout that is exactly
# origin/main. To rehearse in a throwaway copy of the repository, with throwaway keys, set
# OM_REHEARSAL=1 (skips the checkout check) and approve with `bin/om approve --no-submit <digest>`.
cd "$(dirname "$0")/.." || exit 1

custodian=no
for arg in "$@"; do
  case "$arg" in
    --custodian|--custodian=*) custodian=yes ;;
  esac
done
if [ "$custodian" != yes ]; then
  echo "refused: no --custodian. A genesis without one founds a ledger on which no correction exists." >&2
  echo "Read docs/operations/LAUNCH.md (The Founding Ceremony). To found without a Custodian on purpose," >&2
  echo "run bin/om genesis yourself." >&2
  exit 2
fi

if [ "${OM_REHEARSAL:-}" != 1 ]; then
  git fetch --quiet origin main || { echo "refused: cannot fetch origin main" >&2; exit 2; }
  if [ -n "$(git status --porcelain)" ]; then
    echo "refused: the checkout has changes or untracked files; draft the genesis on a clean checkout of main" >&2
    exit 2
  fi
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    echo "refused: HEAD is not origin/main; check out exactly main (git checkout main && git pull --ff-only)" >&2
    exit 2
  fi
fi

exec bin/om genesis "$@"
