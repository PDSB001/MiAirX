# Third-party notices — MiAirX 1.7.0

Original MiAirX code retains the MIT license in `LICENSE`. This build is NOT MIT-only.

## FairPlay Python decryptor

Source: openairplay/airplay2-receiver, commit `6c343d3679ddb561c61566985acaaf587d0a3bd3`, `ap2/fairplay3.py`.

Upstream attribution: systemcrash (2022), original OmgHax author, Foxsen. Upstream declares GPLv2. The source, modification notes and full GPLv2 text are shipped in `src/miairx/protocols/airplay/vendor/` (inside the installed package as `miairx/protocols/airplay/vendor/`). Local edits remove secret-bearing prints and global stdout redirection; crypto arithmetic/tables are unchanged.

Fixed FairPlay reply records come from the same pinned repository's `ap2/playfair.py`. They are third-party protocol blobs, not original MiAirX material; inclusion is not a claim of ownership or a grant of rights over Apple's output.

GPL source ancestry, its relation to GPLv3 C PlayFair distributions, and fixed-blob redistribution rights remain unresolved. The combined distribution must not be described as MIT-only. The complete build is distributed under the Python port's declared GPLv2 terms; original MIT-covered parts retain their notices and separate reuse rights. See `DISTRIBUTION_LICENSE.md`. This release is not a conclusion that the source ancestry or fixed-blob redistribution rights have been cleared.

Regression vectors are attributed in `tests/unit/test_airplay_fairplay.py`; only data needed for interoperability testing is used, not the other receiver's runtime.
