# Windows v26 repository snapshot

The repository root contains the complete verified Windows-native release.
On Windows, clone/extract to an ASCII path and run `run_cases.cmd`. The embedded
runtime is included; no compiler, Ubuntu, WSL or extra Python is needed to run.
See `README.md`, `REQUIREMENTS_WINDOWS.md`, and `source/BUILD_WINDOWS.md`.

`docs/technical-report.pdf` and `.docx` are the updated anonymous technical report.
The original release files, including `validation-current-9i4sbu6t/`, remain
byte-identical. No original manifest, report, proof or status was rewritten.

## Integrity scope

`payload-index.json` retains the exact original **2727-file release scope**
(including the index itself). Git metadata and repository/report additions are
outside that frozen release. `repository-release.json` separately declares the
additional files and hashes. Check the combined repository with:

```powershell
.\runtime\python.exe -I -S .\verify_repository_payload.py
```

On Linux, `python3 -E -B verify_repository_payload.py` performs the same read-only
byte checks; it does not run the Windows program. `.git` and new local run outputs
are reported separately. A successful check does not rerun performance or EQY.

The standalone RAR packager requires a clean release-only directory, so do not
apply its exact whole-directory test directly to a Git checkout with extra files.
To export the frozen submission, copy precisely the original index entries plus
`payload-index.json` into a new directory. The original independent measurement
auditor remains applicable: Git/docs additions do not change its controlled
tool, resource, deployment-record or recorded-run checks.

`.gitattributes` disables newline conversion, ident expansion and external filters
for all files, preserving validated hashes on both Windows and Linux. Do not use
Git LFS filters or replace the bundled binaries. Raw historical PENDING markers
remain intact; `release-status.json` contains the completed aggregate verdict.

## Recoverable history

The previous main commit is `b9c27136acf656a8a2640a1fa00466706b234a79`.
It is preserved as `backup/main-before-windows-v26-20261103`. Publish this snapshot
as a new child commit replacing the current tree and retaining all history;
verify the resulting commit contents before updating main.
