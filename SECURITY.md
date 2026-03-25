# Security

## Release authenticity

DeltaPlan release installs and updates are verified with a signed `manifest.json` plus per-asset SHA-256 checksums.

- public verification key is committed in:
  - `release/release_public_key.pem`
  - `deltaplan_cli/resources/release_public_key.pem`
- signing private key must never be committed
- CI reads the private key from the GitHub Actions secret:
  - `DELTAPLAN_RELEASE_PRIVATE_KEY`

If you rotate the signing key:
1. generate a new keypair
2. update both committed public key files
3. update the GitHub secret with the matching private key
4. publish a new release

## Sensitive data

Do not commit:
- real customer/project workbooks
- `.corpus/`
- `.codex-artifacts/`
- local planning scratch files
- private keys, tokens, passwords, or exported credentials

## Reporting a vulnerability

Please do **not** open a public issue for suspected security problems.

Instead, report privately to the repository owner and include:
- affected version/tag
- impact
- reproduction steps
- logs or screenshots if relevant

The goal is coordinated fix first, public disclosure after patch/release.
