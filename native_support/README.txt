Windows EQY command dependencies

This directory contains GNU make, Bash and the small command/DLL closure used by
the make-based strategies in the official Windows OSS CAD Suite EQY package.
It does not contain Yosys, EQY, SBY, ABC or an OSS CAD Suite installation.

The proof adapter constructs PATH from the configured OSS CAD Suite, this
directory and Windows System32. It does not use an external MSYS2 installation,
Windows user-site Python packages or WSL for the Windows-native proof backend.

provenance.json records every executable/DLL SHA-256, the original installed
package version, its corresponding source-package URL and packaging recipe.
All 15 exact source archives were found in the official MSYS2 source index on
2026-11-04; source-urls-check.json records that check. Source archives include
the upstream source and MSYS2 build recipe/patches. They are not embedded here.
Keep these source URLs and license notices with any redistributed package.

licenses/ contains the installed per-package metadata and license notices,
common GPL-2.0/GPL-3.0/LGPL-2.1/LGPL-3.0 texts, PCRE's license extracted from its
exact MSYS2 source archive, the Cygwin/MSYS runtime notice and GCC runtime notice.

Source archive index: https://repo.msys2.org/msys/sources/
Build recipes: https://github.com/msys2/MSYS2-packages

The tools retain their original licenses; this notice does not change them.
