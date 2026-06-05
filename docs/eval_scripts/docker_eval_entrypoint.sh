#!/bin/sh
set -u

HOST_ROOT=${HOST_ROOT:-/host-root}
MERGED_ROOT=${MERGED_ROOT:-/workspace/host-root}
MERGED_WORKSPACE=${MERGED_WORKSPACE:-/home/yunwei37/workspace/ActPlane}
EXPORT_DIR=${EXPORT_DIR:-/out}
OVERLAY_STORE=${OVERLAY_STORE:-/mnt/actplane-overlay-store}
HOST_HOME=${HOST_HOME:-${HOME:-/root}}
HOST_PYTHONPATH=${HOST_PYTHONPATH:-${PYTHONPATH:-}}

UPPER="$OVERLAY_STORE/root/upper"
WORK="$OVERLAY_STORE/root/work"
STORE_MOUNTED=0
OVERLAY_MOUNTED=0
TRACEFS_MOUNTED=0
VIRTUAL_MOUNTS=""
START_TS=$(date +%s)
EXPORTED_TMP="$EXPORT_DIR/.docker-eval-exported-files.tmp"

json_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

workspace_rel() {
    case "$MERGED_WORKSPACE" in
        /*) printf '%s' "${MERGED_WORKSPACE#/}" ;;
        *) printf '%s' "$MERGED_WORKSPACE" ;;
    esac
}

export_overlay_results() {
    rm -f "$EXPORTED_TMP"
    workspace_upper="$UPPER/$(workspace_rel)"
    corpus_root="$workspace_upper/docs/corpus-test"
    [ -d "$corpus_root" ] || return 0

    find "$corpus_root" -path '*/results/*' -type f | sort | while IFS= read -r src; do
        rel=${src#"$workspace_upper"/}
        dst="$EXPORT_DIR/$rel"
        mkdir -p "${dst%/*}"
        cp -p "$src" "$dst"
        printf '%s\n' "$rel" >> "$EXPORTED_TMP"
    done
}

write_manifest() {
    rc=$1
    shift
    now=$(date +%s)
    elapsed=$((now - START_TS))
    manifest="$EXPORT_DIR/docker_eval_manifest.json"
    {
        printf '{\n'
        printf '  "host_root": "%s",\n' "$(json_escape "$HOST_ROOT")"
        printf '  "merged_root": "%s",\n' "$(json_escape "$MERGED_ROOT")"
        printf '  "merged_workspace": "%s",\n' "$(json_escape "$MERGED_WORKSPACE")"
        printf '  "overlay_upper": "%s",\n' "$(json_escape "$UPPER")"
        printf '  "elapsed_s": %s,\n' "$elapsed"
        printf '  "command": "%s",\n' "$(json_escape "$*")"
        printf '  "returncode": %s,\n' "$rc"
        printf '  "exported_files": ['
        first=1
        if [ -f "$EXPORTED_TMP" ]; then
            while IFS= read -r rel; do
                if [ "$first" -eq 0 ]; then
                    printf ','
                fi
                printf '\n    "%s"' "$(json_escape "$rel")"
                first=0
            done < "$EXPORTED_TMP"
        fi
        if [ "$first" -eq 0 ]; then
            printf '\n  '
        fi
        printf ']\n'
        printf '}\n'
    } > "$manifest"
    rm -f "$EXPORTED_TMP"
}

cleanup_mounts() {
    for mountpoint in $VIRTUAL_MOUNTS; do
        umount -l "$mountpoint" >/dev/null 2>&1 || true
    done
    if [ "$OVERLAY_MOUNTED" -eq 1 ]; then
        umount -l "$MERGED_ROOT" >/dev/null 2>&1 || true
    fi
    if [ "$TRACEFS_MOUNTED" -eq 1 ]; then
        umount -l /sys/kernel/tracing >/dev/null 2>&1 || true
    fi
    if [ "$STORE_MOUNTED" -eq 1 ]; then
        umount -l "$OVERLAY_STORE" >/dev/null 2>&1 || true
    fi
}

finalize() {
    status=$?
    trap - EXIT INT TERM
    mkdir -p "$EXPORT_DIR"
    export_overlay_results || true
    write_manifest "$status" "$@" || true
    if [ "${HOST_UID:-}" ] && [ "${HOST_GID:-}" ]; then
        chown -R "$HOST_UID:$HOST_GID" "$EXPORT_DIR" >/dev/null 2>&1 || true
    fi
    cleanup_mounts
    exit "$status"
}

trap 'finalize "$@"' EXIT INT TERM

if [ ! -d "$HOST_ROOT" ]; then
    echo "missing HOST_ROOT lowerdir: $HOST_ROOT" >&2
    exit 2
fi
if [ "$#" -eq 0 ]; then
    echo "usage: actplane-docker-eval <command> [args...]" >&2
    exit 2
fi

mkdir -p "$EXPORT_DIR" "$OVERLAY_STORE" "$MERGED_ROOT"
if mount -t tmpfs tmpfs "$OVERLAY_STORE"; then
    STORE_MOUNTED=1
else
    echo "warning: could not mount tmpfs overlay store; using existing filesystem" >&2
fi
mkdir -p "$UPPER" "$WORK"

if [ ! -e /sys/kernel/tracing/events ]; then
    mkdir -p /sys/kernel/tracing
    if mount -t tracefs tracefs /sys/kernel/tracing; then
        TRACEFS_MOUNTED=1
    fi
fi

if ! mount -t overlay overlay -o "lowerdir=$HOST_ROOT,upperdir=$UPPER,workdir=$WORK" "$MERGED_ROOT"; then
    echo "failed to mount full-host overlayfs; run docker with --privileged" >&2
    exit 1
fi
OVERLAY_MOUNTED=1

for name in proc sys dev; do
    src="/$name"
    dst="$MERGED_ROOT/$name"
    if [ -e "$src" ]; then
        mkdir -p "$dst"
        if ! mount --rbind "$src" "$dst"; then
            echo "failed to bind $src into chroot" >&2
            exit 1
        fi
        VIRTUAL_MOUNTS="$dst $VIRTUAL_MOUNTS"
    fi
done
if [ -e "$HOST_ROOT/run" ]; then
    mkdir -p "$MERGED_ROOT/run"
    if ! mount --rbind "$HOST_ROOT/run" "$MERGED_ROOT/run"; then
        echo "failed to bind host /run into chroot" >&2
        exit 1
    fi
    VIRTUAL_MOUNTS="$MERGED_ROOT/run $VIRTUAL_MOUNTS"
fi

chroot "$MERGED_ROOT" /usr/bin/env \
    "HOME=$HOST_HOME" \
    "PATH=$PATH" \
    "PYTHONPATH=$HOST_PYTHONPATH" \
    "MERGED_WORKSPACE=$MERGED_WORKSPACE" \
    /bin/sh -lc 'cd "$MERGED_WORKSPACE" && exec "$@"' actplane-eval "$@"
