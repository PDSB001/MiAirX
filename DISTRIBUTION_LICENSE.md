# Complete-build distribution terms

The complete MiAirX distribution includes a FairPlay decryptor whose pinned upstream Python source declares GPL version 2. The combined build is offered under those GPLv2 terms, with complete corresponding MiAirX source, build scripts, upstream attribution, modification notes and the GPLv2 text included. The license text is at `src/miairx/protocols/airplay/vendor/LICENSE.txt` (installed as `miairx/protocols/airplay/vendor/LICENSE.txt`).

The original MIT license and copyright notices remain in `LICENSE`. Original MIT-covered parts may still be reused separately under MIT; this is not an MIT-only license claim for the combined package or container. Separately licensed dependencies retain their own terms.

## Unresolved provenance caveat

The Python port declares GPLv2; related C PlayFair distributions contain GPLv3 terms. The exact source ancestry and redistribution rights of fixed FairPlay response blobs have not been confirmed. This release preserves the declared upstream terms and notices; publication does NOT certify licensing compatibility, resolve these issues, or grant rights that MiAirX does not possess.

See `THIRD_PARTY_NOTICES.md` and the vendor `PROVENANCE.md` for the pinned source and local changes. Anyone redistributing the combined build should review these unresolved issues and the applicable source-distribution obligations.
