#!/bin/bash
# Push the rebuilt plan branches onto the stacked PRs' branches, all or none
# (--atomic), each with a lease on the remote commit last fetched: a branch
# someone else moved since is refused instead of overwritten.
set -euo pipefail
W=${CAD_VIEWER_WT:-$(git rev-parse --show-toplevel)}  # a clone with the plan/NN-* branches
cd "$W"
git fetch -q origin
PAIRS="07-item7:07-half-window 08-item8b:08-measure-record 09-item10:09-toolbar 10-section:10-section-mm
11-motion:11-view-motion 12-idle:12-idle-render 13-labels:13-label-spread 14-title:14-tab-title
15-angle:15-angle 16-release:16-release-0.5.0"
args=()
for pair in $PAIRS; do
  l=plan/${pair%%:*}; r=stack/${pair##*:}
  old=$(git rev-parse "origin/$r")
  # each branch must sit on the one below it (the chain the PRs' bases expect)
  args+=("--force-with-lease=refs/heads/$r:$old" "$l:refs/heads/$r")
done
prev=plan/06-pr35
for pair in $PAIRS; do
  l=plan/${pair%%:*}
  git merge-base --is-ancestor "$prev" "$l" || { echo "$l does not sit on $prev" >&2; exit 1; }
  prev=$l
done
[ "$(git rev-parse origin/stack/base)" = "$(git rev-parse plan/06-pr35)" ] || { echo "stack/base moved" >&2; exit 1; }
git push --atomic origin "${args[@]}"
git fetch -q origin
for pair in $PAIRS; do
  l=plan/${pair%%:*}; r=stack/${pair##*:}
  [ "$(git rev-parse "$l")" = "$(git rev-parse "origin/$r")" ] && echo "ok $r $(git rev-parse --short "$l")" || { echo "MISMATCH $r" >&2; exit 1; }
done
