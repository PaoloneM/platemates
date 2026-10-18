#!/usr/bin/env bash
# Deploys PlateMates to the public server with Ansible (deploy/), run in the
# authkeys/docker-ansible container: nothing to install on the Mac but Docker.
#
#   scripts/deploy.sh                                   # whole server, latest images of main
#   scripts/deploy.sh --tags app                        # the app only
#   scripts/deploy.sh -e platemates_version=sha-abc1234 # a given build
#   scripts/deploy.sh --check --diff                    # what would change
#   scripts/deploy.sh --tags app -e platemates_restart=grafana  # also restart a service that
#                                                       # reads mounted configuration
#   scripts/deploy.sh vault edit                        # change the encrypted personal values
#
# The image's entrypoint passes arguments on unquoted: an extra variable with spaces in it goes
# in a file under deploy/ instead, `-e @file.yml`.
#
# SSH keys come from the Mac's ssh-agent (unlocked by the keychain); the vault password from
# ~/.config/platemates/ansible-vault-password, outside the repository.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="authkeys/docker-ansible:1.2.0"
VAULT_PASSWORD="${PLATEMATES_VAULT_PASSWORD_FILE:-$HOME/.config/platemates/ansible-vault-password}"
# Docker Desktop's bridge to the Mac's ssh-agent, owned by root's group in the container.
AGENT_SOCK=/run/host-services/ssh-auth.sock

if [[ ! -f "$VAULT_PASSWORD" ]]; then
  echo "Missing vault password: $VAULT_PASSWORD" >&2
  exit 1
fi

run() {
  local tty=()
  [[ -t 0 ]] && tty=(-t)
  docker run --rm -i ${tty[@]+"${tty[@]}"} \
    --group-add 0 \
    -v "$AGENT_SOCK:$AGENT_SOCK" -e SSH_AUTH_SOCK="$AGENT_SOCK" \
    -v "$ROOT/deploy:/ansible" \
    -v "$VAULT_PASSWORD:/vault-password:ro" \
    "$@"
}

if [[ "${1:-}" == "vault" ]]; then
  shift
  run -e EDITOR="${EDITOR:-vi}" --entrypoint ansible-vault "$IMAGE" "$@" group_vars/platemates/vault.yml
else
  # The image's entrypoint installs deploy/requirements.yml, then runs ansible-playbook.
  run "$IMAGE" site.yml "$@"
fi
