# FairPlay third-party source

- Source: https://github.com/openairplay/airplay2-receiver
- Pinned commit: `6c343d3679ddb561c61566985acaaf587d0a3bd3`
- Upstream Git blob for `ap2/fairplay3.py`: `f084f8a238a379ba8d88f7d184f3460cc48bbc0c`.
- `fairplay3.py`: upstream `ap2/fairplay3.py`, attributed by upstream to systemcrash (2022), OmgHax's original author and Foxsen.
- Upstream file explicitly declares `GPLv2`; bundled `LICENSE.txt` supplies the GPL version 2 text (copied from Linux's `LICENSES/preferred/GPL-2.0`, license-text section only).
- Local modifications (2026-10-02): replaced executable debug `print` statements with `pass`, removed process-global `sys.stdout` redirection, added provenance comments. Cryptographic arithmetic and tables are unchanged.
- `replies.py`: only the four fixed 142-byte reply records from upstream `ap2/playfair.py`. These are protocol response blobs also found in UxPlay; MiAirX does not claim authorship or independent rights over the blobs.
- Test vectors are attributed separately in `tests/unit/test_airplay_fairplay.py`.

This directory is NOT covered by MiAirX's MIT license. The Python port declares GPLv2, whereas contemporary C PlayFair distributions contain GPLv3 terms. Source ancestry and response-blob rights remain unconfirmed. MiAirX 1.7.0 retains the declared GPLv2 terms and publishes this caveat; publication does not settle licensing compatibility or grant independent rights over third-party blobs. See the root `DISTRIBUTION_LICENSE.md` and `THIRD_PARTY_NOTICES.md`.
