`ddc_web.wasm`: browser build of the design editor's generator (crate `ddc-web`, Apache-2.0), editor commit 2e2931493 (branch link/w1).
Rebuild in the editor checkout: `cargo build --release -p ddc-web --target wasm32-unknown-unknown`, copy `<target>/wasm32-unknown-unknown/release/ddc_web.wasm` here and put its sha256 in `ddcWeb.test.ts` (`VENDORED_SHA256`).
sha256 17275958771191c4f3bfa88b9c52c086d5375cb6b94062db75c68374a1b1ccbb
