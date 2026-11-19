# Upstream workspace license notices

Retrieved 2026-10-30 from the official upstream workspace LICENSE files:

- faer and faer-traits: https://raw.githubusercontent.com/sarah-quinones/faer-rs/main/LICENSE
- nano-gemm and nano-gemm-* crates: https://raw.githubusercontent.com/sarah-ek/nano-gemm/main/LICENSE
- equator/equator-macro: https://raw.githubusercontent.com/sarah-ek/equator/main/LICENSE
- pulp-wasm-simd-flag: https://raw.githubusercontent.com/sarah-quinones/pulp/main/LICENSE

These supplement notices missing from individual published crate archives.
Keep all crate-specific LICENSE, COPYING and NOTICE files as well. In particular,
faer's third-party COPYING files are distributed with the extension. Cargo.toml
files identify package versions, license declarations and source repositories.
Vendored source is shipped in the sdist; wheel notices live in
klimapy/_third_party/rust. This inventory includes optional vendored packages and
is not a claim that every vendored package is linked into every platform build.

Added for the 2026-10-30 geometry migration:
- geo: https://github.com/georust/geo (LICENSE-MIT, LICENSE-APACHE)
- rstar: https://github.com/georust/rstar (LICENSE-MIT, LICENSE-APACHE)
- i_key_sort: https://github.com/iShape-Rust/iKeySort (LICENSE)
- i_overlay: https://github.com/iShape-Rust/iOverlay (LICENSE-MIT, LICENSE-APACHE)
