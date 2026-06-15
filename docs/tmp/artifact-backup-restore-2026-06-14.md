# Artifact Backup Restore Notes, 2026-06-14

This note records the remote backup refs created before CLI UX cleanup.

## ActPlane Superproject

Remote:

```text
https://github.com/eunomia-bpf/ActPlane
```

Backup ref:

```text
refs/heads/backup/2026-06-14-master
```

Commit:

```text
cceaee6be878eeff4b42caf9a069d535699ecf69
```

Restore or inspect:

```bash
git fetch origin backup/2026-06-14-master
git show origin/backup/2026-06-14-master --stat
```

## OpenAgentSafety Nested Repository

Local path:

```text
docs/OpenAgentSafety/OpenAgentSafety
```

Remote:

```text
https://github.com/eunomia-bpf/OpenAgentSafety.git
```

Backup ref:

```text
refs/heads/backup/2026-06-14-actplane-submodule
```

Commit:

```text
8cb4131211435a933d44942479e79418972f8f9b
```

Restore into the ActPlane checkout:

```bash
rm -rf docs/OpenAgentSafety/OpenAgentSafety
git clone --branch backup/2026-06-14-actplane-submodule \
  https://github.com/eunomia-bpf/OpenAgentSafety.git \
  docs/OpenAgentSafety/OpenAgentSafety
git -C docs/OpenAgentSafety/OpenAgentSafety rev-parse HEAD
```

Expected restored commit:

```text
8cb4131211435a933d44942479e79418972f8f9b
```

Note: `.gitmodules` in ActPlane contains a `docs/OpenAgentSafety/OpenAgentSafety`
entry, but the current ActPlane HEAD does not track the gitlink for that path.
The restore command above recreates the nested repository checkout directly.
