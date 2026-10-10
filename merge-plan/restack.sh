#!/bin/bash
# usage: restack.sh <branch> <old-base>
#
# Put <branch> (its commits after <old-base>) on origin/master, check it
# (tsc, backend pytest) and push it with --force-with-lease. The known
# conflicts are resolved by git rerere (recorded when the plan was built);
# a conflict it cannot resolve stops the script, for a hand resolution.
#
# For an open PR still based on master: <old-base> = the master it was based
# on (git merge-base origin/<branch> origin/master before fetching), or simply
# origin/master^ style refs; for a stacked PR: the previous PR's branch tip
# before that PR was squash-merged.
set -euo pipefail
BR=$1
OLD=$2
# the worktree to restack in (any clone of the repo); PYTEST: backend's pytest (a venv's)
W=${CAD_VIEWER_WT:-$(git rev-parse --show-toplevel)}
PYTEST=${PYTEST:-.venv/bin/pytest}
cd "$W"
git fetch -q origin
if git rev-parse -q --verify "refs/heads/$BR" >/dev/null; then
  git checkout -q "$BR"
else
  git checkout -q -b "$BR" "origin/$BR"
fi
if ! git rebase --onto origin/master "$OLD" "$BR"; then
  # rerere may have resolved and staged every conflict: go on while nothing is left unmerged
  while [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; do
    if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
      echo "unresolved conflicts: $(git diff --name-only --diff-filter=U)" >&2
      exit 1
    fi
    GIT_EDITOR=true git rebase --continue || true
  done
fi
# node from nvm when there is one
[ -d "$HOME/.nvm/versions/node" ] && export PATH=$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node" | tail -1)/bin:$PATH
(cd frontend && npx tsc --noEmit -p .)
(cd backend && "$PYTEST" -q -p no:cacheprovider)
git push --force-with-lease origin "$BR"
git log --oneline -3
