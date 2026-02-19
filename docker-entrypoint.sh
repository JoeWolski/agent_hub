#!/usr/bin/env bash
set -euo pipefail

LOCAL_USER="${LOCAL_USER:-codex}"
LOCAL_GROUP="${LOCAL_GROUP:-$LOCAL_USER}"
LOCAL_UID="${LOCAL_UID:-1000}"
LOCAL_GID="${LOCAL_GID:-1000}"
LOCAL_SUPP_GIDS="${LOCAL_SUPP_GIDS:-}"
LOCAL_SUPP_GROUPS="${LOCAL_SUPP_GROUPS:-}"
LOCAL_HOME="${LOCAL_HOME:-/home/$LOCAL_USER}"
LOCAL_UMASK="${LOCAL_UMASK:-0022}"

if [[ "$LOCAL_UMASK" =~ ^[0-7]{3,4}$ ]]; then
  umask "$LOCAL_UMASK"
fi

if [[ "$#" -eq 0 ]]; then
  set -- codex
fi

if [[ "$(id -u)" -ne 0 ]]; then
  exec "$@"
fi

if ! getent group "$LOCAL_GID" >/dev/null 2>&1; then
  if getent group "$LOCAL_GROUP" >/dev/null 2>&1; then
    groupmod --gid "$LOCAL_GID" "$LOCAL_GROUP"
  else
    groupadd --gid "$LOCAL_GID" "$LOCAL_GROUP"
  fi
fi

if ! id -u "$LOCAL_USER" >/dev/null 2>&1; then
  if [[ -d "$LOCAL_HOME" ]]; then
    useradd \
      --uid "$LOCAL_UID" \
      --gid "$LOCAL_GID" \
      --home-dir "$LOCAL_HOME" \
      --no-create-home \
      --shell /bin/bash \
      "$LOCAL_USER"
  else
    useradd \
      --uid "$LOCAL_UID" \
      --gid "$LOCAL_GID" \
      --home-dir "$LOCAL_HOME" \
      --create-home \
      --shell /bin/bash \
      "$LOCAL_USER"
  fi
fi

if [[ "$(id -u "$LOCAL_USER")" != "$LOCAL_UID" ]]; then
  usermod --uid "$LOCAL_UID" "$LOCAL_USER"
fi

if [[ "$(id -g "$LOCAL_USER")" != "$LOCAL_GID" ]]; then
  usermod --gid "$LOCAL_GID" "$LOCAL_USER"
fi

if [[ -n "$LOCAL_SUPP_GIDS" ]]; then
  IFS=',' read -r -a supp_gid_list <<< "$LOCAL_SUPP_GIDS"
  IFS=',' read -r -a supp_group_list <<< "$LOCAL_SUPP_GROUPS"
  supplemental=()
  for idx in "${!supp_gid_list[@]}"; do
    gid="${supp_gid_list[$idx]}"
    if [[ -z "$gid" || "$gid" == "$LOCAL_GID" ]]; then
      continue
    fi

    group_name="$(getent group "$gid" | cut -d: -f1 || true)"
    if [[ -z "$group_name" ]]; then
      candidate=""
      if [[ "$idx" -lt "${#supp_group_list[@]}" ]]; then
        candidate="${supp_group_list[$idx]}"
      fi
      if [[ -z "$candidate" || "$candidate" == "$LOCAL_GROUP" ]]; then
        candidate="hostgrp_$gid"
      fi
      if getent group "$candidate" >/dev/null 2>&1; then
        candidate="${candidate}_$gid"
      fi
      groupadd --gid "$gid" "$candidate"
      group_name="$candidate"
    fi
    supplemental+=("$group_name")
  done

  if [[ "${#supplemental[@]}" -gt 0 ]]; then
    # usermod requires a comma-separated list of unique group names.
    groups_csv="$(
      printf '%s\n' "${supplemental[@]}" \
        | awk '!seen[$0]++' \
        | paste -sd, -
    )"
    if [[ -n "$groups_csv" ]]; then
      usermod --append --groups "$groups_csv" "$LOCAL_USER"
    fi
  fi
fi

if command -v sudo >/dev/null 2>&1; then
  if ! getent group sudo >/dev/null 2>&1; then
    groupadd --system sudo
  fi
  usermod --append --groups sudo "$LOCAL_USER"

  sudoers_file="/etc/sudoers.d/90-${LOCAL_USER}"
  printf '%s ALL=(ALL:ALL) NOPASSWD:ALL\n' "$LOCAL_USER" > "$sudoers_file"
  chmod 0440 "$sudoers_file"
fi

mkdir -p "$LOCAL_HOME"
chown "$LOCAL_UID:$LOCAL_GID" "$LOCAL_HOME"

export HOME="$LOCAL_HOME"
exec gosu "$LOCAL_USER" "$@"
