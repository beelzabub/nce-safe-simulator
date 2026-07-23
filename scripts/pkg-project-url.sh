#!/bin/sh
# Print the GitLab API project URL derived from this clone's `origin` remote,
# e.g.  https://gitlab.com/api/v4/projects/group%2Fsubgroup%2Fproject
#
# Docker builds pass it as the PKG_PROJECT build-arg so every registry fetch
# (the Quarto .deb, issue #262; the apt-debs system packages, issue #269) pulls
# from the package registry of WHATEVER GitLab instance this clone came from —
# no hardcoded host anywhere, so a repo lifted into another network (enclave)
# automatically resolves to its own instance.
# Works from any cwd inside the repo; handles https:// and git@host: remotes.
set -e
remote=$(git remote get-url origin)
case "$remote" in
  *://*)
    scheme=${remote%%://*}
    rest=${remote#*://}
    host=${rest%%/*}
    path=${rest#*/}
    ;;
  *@*:*)
    scheme=https
    hostpart=${remote#*@}
    host=${hostpart%%:*}
    path=${hostpart#*:}
    ;;
  *)
    echo "pkg-project-url.sh: unrecognized origin remote form: $remote" >&2
    exit 1
    ;;
esac
path=${path%.git}
printf '%s://%s/api/v4/projects/%s\n' "$scheme" "$host" "$(printf '%s' "$path" | sed 's#/#%2F#g')"
