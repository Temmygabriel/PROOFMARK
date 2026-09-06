# intelligent-contracts / `proofmark.py`

**`proofmark.py` is the one and only contract source.** GenLayer intelligent-contract
code is **network-agnostic** — the same file is deployed to each network; there is
no separate "StudioNet contract" vs "Bradbury contract" to maintain. Keeping one
source (instead of two byte-identical copies) is what prevents the two from ever
drifting apart.

## Canonical live deployments

| Network | Address | Verified |
|---|---|---|
| **StudioNet** (61999) | *(pending Phase 6 redeploy — see below)* | — |
| **Testnet Bradbury** (4221) | *(pending Phase 6 redeploy — see below)* | — |

> **Rebrand note (2026-09-06):** the contract was renamed `aegis.py` →
> `proofmark.py` and `class Aegis` → `class Proofmark` as part of the Proofmark
> rebrand. That is a **new deploy artifact**, so both networks get fresh addresses
> and the live proof is re-run on the new contract. The prior Shape B deploy
> (`0x589472da571Db60151100b153D65a7170367E17D`, StudioNet e2e **37/37** PASS on
> 2026-09-06) stands as the **historical pre-rename validation**.

Full evidence, prior deployments, and re-deploy steps live in
[`docs/PROOFMARK_DEPLOYMENT.md`](../docs/PROOFMARK_DEPLOYMENT.md) and
[`docs/dev/PROOFMARK_E2E_REPORT.md`](../docs/dev/PROOFMARK_E2E_REPORT.md).

## If you deploy a new version

1. Edit `proofmark.py`.
2. Re-run the direct test suite: `pytest tests/direct/test_proofmark.py` and
   `genvm-lint check intelligent-contracts/proofmark.py`.
3. Deploy + value-test on StudioNet, then on Bradbury (see
   `e2e/run.js` / `e2e/verify-payments.js`).
4. Record the new addresses in `docs/PROOFMARK_DEPLOYMENT.md` and point the frontend
   `.env` at them.
