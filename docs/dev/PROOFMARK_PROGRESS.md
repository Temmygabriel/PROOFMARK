# Proofmark — Progress Log

Running log of investigation, testing, fixes, and deployment. Newest first
within each section; keep this updated as work happens.

## Rebrand banner — Proofmark (2026-09-06)

The whole product has been rebranded to **Proofmark** per
`proofmark-rebrand-spec.md` (project root, outside this repo): contract,
frontend, tests, docs, e2e, design system, copy. Entries below that predate the
rename describe the product under its old working name and are kept as history.
The local checkout folder still carries its pre-rename name; the GitHub repo was
renamed to `proofmark` by the user — origin URL is NOT to be touched (GitHub
redirects it; pushes still work). Two locked decisions: (1) the contract rename
→ **new deploy artifact** → redeploy StudioNet + Bradbury to fresh addresses +
re-run the live proof (Phase 6); (2) scope = **everything** (in-repo +
project-root deliverables + SECURITY-CHECK review docs).

Phase state (newest first):
- **Frontend fixes while filming (2026-09-08, commits `59691aa` + next):** the live
  dashboard surfaced two issues worth recording. (a) `register` (and any write) could
  report "Timed out waiting … FINALIZED (current status: 5)" even after success — the
  SDK's default 30s wait (10×3s) runs out while StudioNet lingers at ACCEPTED; verified
  on-chain the reported register tx was FINALIZED + not reverted, then widened the wait
  to ~2 min in `proofmarkClient.write` (a payable retry would double value). (b) the
  identity dropdown `.idmenu` has no height cap and the sticky topbar pins it below the
  viewport, so its last section (Danger zone → Generate new identity) was unreachable on
  short screens; now capped to the viewport with internal `overflow-y: auto`.
  (c) **StudioNet receipts carry no `txExecutionResultName`/`statusName`** — the H-04
  positive check read them as undefined and threw a false "Transaction did not succeed"
  on EVERY successful write (seen live: a `register` for `agent-fa34` that finalized
  MAJORITY_AGREE with 2 agreeing validators = SUCCESS). Replaced the check with
  `classifyReceipt`, the per-validator `consensus_data.validators[]` classifier
  (agree/ERROR rule, idle-ERROR ignored) mirrored from `e2e/run.js`; verified against
  two real finalized register receipts (both classified ok) + synthetic revert and
  undetermined cases. Commits: `59691aa`, `7cfd23b`, this one.
- **Submission wrap-up (2026-09-08)** — three finishing moves after the Phase-7b live
  proof, all on the canonical hardened `0x850F…`:
  (1) **A real payout planted on the canonical board.** The seeded job
  `job-live-1788864539810`'s deadline passed with nothing delivered and the
  deterministic auto-breach claim was filed (`e2e/results/plant-claim.js`, keys
  buyer): claim **upheld**, buyer paid **exactly 1.000000 GEN** from the Unrated
  pool, 2 GEN bond refunded. Board re-read post-settlement: Unrated **9.0600 /
  locked 0.0000** (was 10.0600 / 1.0000), Bronze 5 / Silver 3 / Gold 2. Provenance
  in `e2e/results/plant-payout.log`. This is the "Coverage paid" example the
  submission's Step 2 points a reviewer at.
  (2) **UI Accept-job action** so the full reviewer loop is runnable — the hardened
  contract requires the agent's owner to `accept_job` before a policy is `active`,
  and the UI never surfaced it. The Coverage job-record card now renders an "Accept
  job" button when the current identity owns the agent of a `pending` policy;
  esbuild TSX parse gate clean.
  (3) **Submission + demo docs reconciled to the verified reality** (project root,
  outside this repo): `proofmark-submission-note.md` §05 rewritten as titled,
  reproducible two-window steps (agent window + buyer window — the contract refuses
  self-insurance), canonical → `0x850F…`, board → the post-claim state; demo
  run-sheet/captions gained the accept beat and the settled board; this repo's docs
  (LIVE_EVIDENCE / PROJECT_MEMORY) re-pointed to the settled board. Audit
  follow-ups: M-05 + L-01 resolved (evidence is reproducible via the committed
  LIVE_EVIDENCE tx-hash tables + re-verify; CONTRACT.md and `get_claim_status` share
  the `unresolved/pending/upheld/rejected` vocabulary since H-02); M-07 (ISO parser
  permissiveness) accepted as a disclosed LOW residual — tightening it would change
  `proofmark.py` bytes and break byte-exact provenance to the canonical deploy, so it
  is deliberately unchanged (rationale in the audit doc banner). **Forward-looking
  only, no action at submission:** consensus v0.6 migration — test on studio-dev
  first (https://docs.genlayer.com/developers/consensus-v06-migration); the v0.6 RC
  stack lives on studio-dev (61997) and may reset; stable studionet (61999) must not
  point at the preview RPC. **Vercel env flip to `0x850F…` remains the only manual
  step before filming.**
  (4) **Vercel build fix + logo pack (2026-09-08, commit `b17cc4f`).** Vercel's
  `next build` failed production on a latent type error the local esbuild gate can't
  see (`page.tsx:1322` — a still-`pending` two-phase claim could be pushed onto the
  verdict feed; type narrowed to `upheld | rejected`). Fixed, then **type-checked
  locally with `npx tsc --noEmit`** (clean) before pushing — this is now the gate
  ahead of any Vercel build. Branding: official logo set authored from the in-app
  `ProofmarkLogo` geometry under `branding/` at the project root (local, not in this
  repo): light/dark mark, single-tone badge, app icon, two wordmark lockups (SVG +
  PNG rasterized via `@resvg/resvg-js`). Submission §01 logo blank now points at
  `branding/proofmark-mark-1024.png`.
- **Phase 7b (adversarial contract re-audit + hardening) — DONE + LIVE-PROVEN (2026-09-08):**
  the adversarial audit closed three reviewer-pickable flaws in `proofmark.py` (all
  committed with this entry):
  (1) **evidence custody split** — in `_judge_breach` a 4xx/oversized **deliverable**
  (agent's evidence, live-probed at submit) resolves as a *breach*, while a 4xx/oversized
  **spec** (buyer's evidence, only shape-checked at issue) resolves as *rejected* — a
  buyer who unpins its own spec can no longer manufacture a payout against an agent that
  delivered. (2) **FIX-16** — `accept_job` refuses a policy whose deadline has passed (an
  agent can never be bound to an already-impossible delivery and hit by an instant
  auto-breach). (3) **FIX-18** — new permissionless `expire_pending_policy` voids a
  PENDING policy past `deadline + 7-day claim window` (exposure released, premium
  refunded), so a never-accepted/never-cancelled policy can't lock LP capital forever.
  Plus the GPT-audit **H-02** two-phase claims (FIX-19): payable `file_claim` is
  deterministic (escrows the 2 GEN bond, records `pending`); the nondet judgement runs in
  the separate **non-payable** `judge_claim`, so a failed judgement reverts with no value
  and can never burn the bond (`rescind_pending_claim` recovers it). Frontend **H-04**
  (positive success check) + **M-01** (full pending lifecycle) fixes are in this batch.
  **Gates:** `genvm-lint` clean; **55/55 direct tests green** (`pytest tests/direct/`).
  **Live re-proof on the hardened artifact (2026-09-08, StudioNet):** fresh deploy → e2e
  **37/37 PASS** on `0x1FcE880D9fabDEc1Fa883FA3d2CD0685607379f7` (`studionet.json` + log;
  money rows exact: deposit credits pool 20, upheld auto-breach claim debits 20.12→19.12,
  withdraw drains to 0); fresh deploy → **clean seed-live board** on
  `0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6` (Unrated 10.0600 / locked 1.0000 /
  Bronze 5 / Silver 3 / Gold 2; agent/job ids `agent-live-1788864539810` /
  `job-live-1788864539810`; wallet in `e2e/live-keys.json`). `page.tsx` seed rebaked
  (`SEEDED_CONTRACT` → 0x850F; esbuild TSX parse gate clean); CONTRACT.md /
  DEPLOYMENT.md / LIVE_EVIDENCE.md / intelligent-contracts README re-pointed to the
  hardened canonical. The pre-hardening `0x1c91…` package (37/37 + 10/10 + seeded board)
  is recorded as **superseded** (kept historical). **Manual follow-up:** flip the Vercel
  env `NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS` → `0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6`
  and redeploy so the live demo surface runs the exact hardened source.
- **Phase 7 (evidence + close-out) — DONE (2026-09-07, commits `5282015` + `d790be7` + this one):**
  new `docs/PROOFMARK_LIVE_EVIDENCE.md` with the canonical evidence (StudioNet `0x1c91…` 37/37 +
  10/10 + seeded board, deploy tx, tx-hash tables, residuals incl. the Bradbury pubdata cap and the
  judged-V3 gateway, re-verify command); `PROOFMARK_DEPLOYMENT.md` live-deploy table + env block →
  `0x1c91…` (Bradbury `0x79C1…` caveated as pre-rename Shape A); `intelligent-contracts/README.md`
  canonical table; `E2E_REPORT.md` historical-status banner; `page.tsx` seed baked to the 2026-09-06
  seed (`SEEDED_CONTRACT` 0x1c91, ids `*-live-1788715641710`; esbuild TSX gate clean); `run.js`
  Bradbury default carries the honest-residual note. Project-root deliverables swept: the submission
  note + demo run-sheet/captions reconciled to the verified rebranded UI copy and the canonical
  address; `genlayer-demo-manual.md` + playbook are brand-neutral (kept); `genlayer-project-explorer-submission.md`
  is the **Rigor** worked example — a different product, kept verbatim; `SECURITY-CHECK/e2e-deploy-spec.md`
  kept verbatim (historical Shape B runbook — its "0x79C1 DO NOT USE — unpatched" is technically
  accurate: Bradbury runs unpatched Shape A; the current framing lives in DEPLOYMENT/LIVE_EVIDENCE).
  §12 grep still clean (sole exemption: the two legacy-key literals in `identity.ts`). Auto-memory
  refreshed to the canonical Proofmark state. **All rebrand commits pushed to GitHub 2026-09-07**
  (`origin/main` → `9a02783`; GitHub redirects the old `Temmygabriel/Aegis` URL to `Temmygabriel/PROOFMARK`).
- **Phase 6 (live redeploy + re-proof) — DONE (StudioNet), Bradbury = honest residual:**
  rebranded `proofmark.py` deployed to StudioNet **canonical
  `0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3`** (2026-09-06, deploy tx
  `0x42d1f3c5…a621279`): **e2e 37/37 PASS** (`studionet-proofmark-e2e.log` +
  `studionet.json`), **verify-payments 10/10 PASS** (`studionet-proofmark-verify-
  payments.log`; V3 judged skipped — gateway CIDs unresolved, recorded residual),
  **seeded live board** (`studionet-seed-live.log`; independently re-read
  2026-09-07, state persisted) baked into `page.tsx` (`SEEDED_CONTRACT` 0x1c91,
  seed ids `job/agent-live-1788715641710`; esbuild TSX gate clean). **Bradbury
  fresh deploy BLOCKED:** the 62,351-byte source exceeds Bradbury's per-tx pubdata
  cap (`invalid transaction: BlockPubdataLimitReached`; largest known-good
  ~39,869 B Shape A artifact). One blocked attempt cost ~0.0014 GEN; no further
  attempts per the funds constraint. Canonical Bradbury address remains the
  pre-rename Shape A `0x79C1…` (documented residual, no code/provenance change).
  Fresh evidence in `docs/PROOFMARK_LIVE_EVIDENCE.md`.
- **Phase 5 (content sweep) — DONE:** project-root deliverables brand-swept to
  grep-zero — `proofmark-submission-note.md`, demo run-sheet, demo caption
  cards, `SECURITY-CHECK/*.md`. Product-name prose → Proofmark; file-path refs
  → `proofmark.py` / `proofmarkClient.ts`; technical findings kept verbatim;
  repo URL corrected to `github.com/Temmygabriel/proofmark`; Vercel URL
  placeholders marked for the Phase 7 deploy; the §03 description recount is
  in-file (989 chars, fits). Exempt by design: `proofmark-rebrand-spec.md`
  (the rename authority — its mapping tables must keep the old names) and
  `.claude/settings.local.json` (machine paths + allowlist). Canonical
  addresses/URLs in these docs refresh in the Phase 7 close-out.
- **Phase 4 — DONE:** in-repo docs rebrand. Six docs renamed via `git mv` to
  `PROOFMARK_CONTRACT.md` / `PROOFMARK_DEPLOYMENT.md` / `PROOFMARK_UX_FLOW.md` /
  `PROOFMARK_E2E_REPORT.md` / `PROOFMARK_PROGRESS.md` /
  `PROOFMARK_PROJECT_MEMORY.md`; cross-links + file-path refs swept to
  `proofmark.py` / `test_proofmark.py` / `PROOFMARK_*`; repo-root `README.md`
  rewritten to the Proofmark positioning; the 2026-09-06 `0x5894…` 37/37 run is
  recorded as the pre-rename Shape B validation; live deploy tables stay reserved
  for the Phase 6 hashes. **Gate: §12 grep over repo source (ts/tsx/css/py/json/
  md) returns zero** — the sole exemption is the two mandated legacy-key
  literals in `identity.ts`. This log and PROOFMARK_PROJECT_MEMORY swept to
  grep-zero.
- **Phase 3 — DONE (commit `191e657`):** full frontend rebrand. `layout.tsx` → Geist /
  Geist_Mono (`--font-geist-src`/`--font-geist-mono-src`) + Proofmark metadata.
  `lib/identity.ts` key → `proofmark.identity.pk.v1` + silent migration from the
  two legacy keys (the literal key strings are spec-§1 data — the one exempted
  §12 grep hit); client module renamed to `proofmarkClient.ts` (`git mv`),
  `PROOFMARK_ADDRESS`/`NEXT_PUBLIC_PROOFMARK_*`, `CLAIM_BOND_ATTO` →
  `VERDICT_BOND_ATTO`, `penalty` tier added (1200 bps, muted-red). `globals.css`
  re-themed to spec §2 (graphite `#09090b/#0e0e11/#141417`, proof blue / ok green /
  breach amber / penalty muted-red; copper + shield + navy + ALL-CAPS removed;
  infra grid body; sentence-case mono labels); stamp 84px −5° + `stampLand`,
  `not-delivered` amber / `delivered` green; `proof-pill` "Rail active";
  `shield*` → `gauge*`; chips re-mapped to the derivePolicyState labels.
  `page.tsx`: `ProofmarkLogo` topbar + hero ring, brand/sub, eyebrow "Coverage
  pools", "Capital underwriting active jobs", `{X} GEN backing active jobs`,
  tabs Agents·Coverage·Pools·**Verdicts**, panels "Back a job" / "Job record" /
  "Request verdict" / "Underwrite" / "Add capital" / "Withdraw capital",
  `ConformanceStamp` NOT DELIVERED/DELIVERED + "covered"/"bond returned",
  feed keys `proofmark.activity.v1` + `proofmark:feed`, microcopy sweep
  (insure→back, payout→coverage in the verdict prose). `IdentityBadge` honesty
  notice. package.json/lock → `proofmark-frontend`. `frontend/README.md`
  rewritten to the real product. **Gates: esbuild TSX parse clean on all
  app/components/lib sources (`.esbuild-check/`); §12 grep shows zero brand
  tokens in ts/tsx/css/json except the two mandated legacy-key literals in
  `identity.ts`** (md docs swept in Phase 4).
- **Phase 2 — DONE (commit `82c3f58`):** e2e harness rebranded — `run.js`/`seed-live.js`/
  `verify-payments.js` headers + `CONTRACT_PATH`→`proofmark.py`, mirrors →
  `lib/proofmarkClient.ts` / `test_proofmark.py`, deploy label, `package.json` +
  `package-lock.json` name → `proofmark-e2e` + description. `node --check` clean on
  all 4 scripts; no pre-rebrand brand tokens left in harness sources. (No ABI/method
  name change — `run.js` e2e method calls untouched, spec §11.)
- **Phase 1 — DONE (commit `1133f7b`):** `git mv` the contract source to
  `proofmark.py`, the direct-mode test to `test_proofmark.py`, the smoke test to
  `test_proofmark_smoke.py`; module docstring → Proofmark trust-infrastructure
  positioning (spec §8), contract class `Proofmark`, all 47 deploy-path +
  docstring-header refs
  updated; `intelligent-contracts/README.md` rewritten (deploy table marked
  *pending Phase 6 redeploy*). **Gates: `genvm-lint` clean (Contract: Proofmark,
  17 methods); `pytest tests/direct/` 47/47 PASS.**
- **Phase 0 — DONE (commit `13219c4`):** pre-rebrand Shape B baseline committed
  (security fixes, 46 tests, harness rewrite, StudioNet e2e **37/37** on
  `0x589472da571Db60151100b153D65a7170367E17D` — recorded as the *pre-rename
  validation*).

Next (remaining — all on the user's side or optional): **manual Vercel step** — rename the env vars
to the `NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS` / `NEXT_PUBLIC_PROOFMARK_NETWORK` pair, set the
hardened StudioNet address `0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6`, remove the old-name env
vars, redeploy
(the old Vercel domain is replaced). Then the demo take: dry-run the §05 path live on a fresh profile
on the hardened board (seeded agent/job ids `agent-live-1788864539810` / `job-live-1788864539810`),
film from the run-sheet/captions, fill the remaining `[YOU: …]` blanks in the submission note (logo,
dropdown tags, YouTube link, the planted job id), and submit. Optional: live judged-path (V3) smoke on
StudioNet after the demo take, re-verifying the §05 board numbers if its payout shifts a pool. All
rebrand + hardening commits are pushed to GitHub; after the env flip, confirm the Vercel rebuild
deployed the hardened contract (page foot + board numbers on the new address).

## Status (2026-09-03)

- **Done (Shape A gaming hardening shipped — patch + full redeploy + re-seed):**
  the final proactive review's finding 1 (self-deal auto-breach drain) is
  **patched**, not deferred: `issue_policy` now (a) rejects the agent's own
  owner as buyer, (b) parses deadlines to epoch seconds with a 60 s minimum
  horizon (no ~1-second drain loops), and (c) caps coverage to 10% of the tier
  pool at issue so a policy label is always the most one claim can pay.
  Contract committed (`ba7db2e`), suite **28/28**, `genvm-lint` clean. Both
  contracts **redeployed to fresh canonical addresses** and verified live:
  StudioNet `0x605e5BE4a8013B2B6c70c4BECa3CEbB7BD7918e4` — full e2e **28/28
  PASS** on the new address — and Bradbury `0x79C15889D5070321176994373C440778a9eC47c1`
  (deploy tx `0x14222a…`, read-verified; no full e2e on Bradbury by design).
  Live board **re-seeded** to the §05 numbers on the new StudioNet contract
  (Unrated 10.06 / locked 1.00, Bronze 5, Silver 3, Gold 2; seed ids
  `agent-live-1788435546808` / `job-live-1788435546808`). Frontend seed gate,
  `frontend/.env.example` and `docs/PROOFMARK_DEPLOYMENT.md` re-pointed (`de3d242`,
  parse gate clean). Remaining disclosed residual (two-wallet drip, bronze
  breach-rate gate) and the judged-path QA gap are recorded in the Final
  review section below. **One user action left:** flip the Vercel
  env var to `NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS = 0x605e5B…` and redeploy
  the project
  (no local CLI token).

- **Done (submission + demo docs rewritten to the final UI; working folder
  cleaned):** the submission note was rewritten in the Rigor style
  (`genlayer-project-explorer-submission.md` in the same folder): a simple §05
  reviewer path (Steps 1–7) aligned to the shipped war-room labels (Risk pool
  overview, Recent activity, Get quote / Issue policy, Policy status chips
  Awaiting delivery / Auto-breach available / Paid out), §03 Description
  measured 983 chars, §06 outcome measured 469 chars, and inline symbols
  (arrows/checks/backticks/blockquotes) stripped from the body. The feed no
  longer "starts empty": §05 and the demo plan say the Recent activity panel
  opens with the seeded history and the demo's own writes stack above.
  The demo plan was rebuilt as a plain run-sheet keyed to §05 with a
  copy-paste values block; the demo captions cleaned to plain short
  cards. Superseded/implemented docs (old demo-script, submission-draft,
  ui-redesign, ui-ux-recommendations, wallet-integration) moved to `archive/`
  with a README; top level now holds only the live doc set + the mock + the
  official guides.
- **Done (feed backfill on the seeded live board):** "Recent activity" read
  empty on any fresh browser because the feed only logs *this-browser* writes
  and the seeded chain activity came from `seed-live.js`'s Node wallet. On the
  canonical seeded StudioNet deploy only (`PROOFMARK_ADDRESS` == `0xED90…`),
  `seedFeedOnce()` in `page.tsx` now replays the six REAL seed transactions
  (register `agent-live-1788422271884`, LP 10/5/3/2 GEN into Unrated/Bronze/
  Silver/Gold, 1 GEN cover on `job-live-1788422271884`) into a first-load feed,
  timestamped at the actual seed run (the ids embed `Date.now()`); the browser's
  own confirmed writes then stack above. Any other network/address stays
  local-only. Parse gate clean; pushed for the live build.
- **Done (mock-exact war-room UI, aligning the redesign mockup):**
  implemented on `app/page.tsx` + `app/globals.css`. The marketing
  hero-lead/headline block is gone — the page now opens on the two-panel war
  room (`1fr 340px` grid): **left** = "Risk pool overview" eyebrow + Refresh /
  "Updated …" tools, the conic **capital-utilisation ring** (copper arc =
  live `sum(locked)/sum(balance)`, honest stand-in for the mock's illustrative
  45%) around a small shield, big **TVL** number + "N% · X GEN locked on
  active cover" sub-line, the four tier tension bars, and a dim contract-
  address footline; **right** = "Recent activity" feed (real localStorage
  writes, same empty state). Tabs reordered **Agents · Coverage · Pools ·
  Claims**, **Coverage active on load**. Coverage tab rebuilt to the mock's
  three-part composition: **Quote & issue cover** panel (Agent/Coverage row →
  Job → Spec → Deadline fields; after Get quote a quote-box with a tier
  badge + "Premium due" + one-click **Issue policy →** that re-quotes at pay
  time — a drift just refreshes the box; empty-pool gate jumps to Pools),
  **Policy status** panel (Look up renders a visualized card: status chip,
  2×2 Agent/Pool tier/Coverage/Payout grid reading `get_claim_status` for
  resolved claims, and an honest conformance track — 40 threshold tick + 0–100
  legend, **no fabricated fill** since the contract stores no score), and a
  full-width **verdict strip** that only renders for a real resolved
  inspection. `VerdictStamp` gained an optional detail note. `RATE_BPS_BY_TIER`
  import dropped. esbuild TSX parse gate passes. **Not yet visually confirmed
  on the Vercel build.**
- **Next:** confirm the live build reads like the mock (war-room hero, TVL ring
  + bars + feed, Coverage default, quote-box + policy card, verdict strip) and
  the feed now shows the seeded history on a fresh profile; then the demo-docs
  sync (demo plan, submission note, captions) against the
  final on-screen labels — note the demo plan's "feed starts empty" pre-flight
  line flips to "feed opens with the seeded history, your actions stack above"
  — and the folder cleanup of the similar working docs.
- **Done (war-room redesign):** implemented the then-current UI-redesign note on
  `layout.tsx` (Space Grotesk + Space Mono replace Fraunces/IBM Plex),
  `globals.css` (darker `#07090f` bg + tighter radial glows, new copper
  `#e07820` + cold-green `#38e89a` verdict tokens, 8/6/6 px radii, then the
  new component layer: hero board, tier bars, live-activity feed, quote-box,
  verdict stamp, hero-left shield watermark, net-pill pulse), and
  `page.tsx` (hero is now a hero-lead statement + two-column board —
  **hero-left TierBars** risk display replacing the stat-card + tiles, and a
  **hero-right live feed** fed by the real last-N confirmed writes in
  `localStorage`; `VerdictBox` → `VerdictStamp` ink-stamp; Coverage quote +
  issue collapsed into a `.quote-box`). UX-round logic preserved
  (review/confirm flow, derived policy chips + action tips, Claims role
  grouping). **Not yet visually confirmed on the Vercel build.** Conformance
  score bar **deferred**: the contract exposes no 0–100 score read, so there
  is nothing honest to draw.
- **Done (build fix `105b6f5`):** wrapped the Inspect-a-policy kv + action-tip
  siblings in a fragment — the Vercel JSX compile error from `0804ebb` is
  fixed. Preventive gate added: `esbuild` TSX parse before pushes
  (`.esbuild-check/` gitignored); no local `next build`/`tsc` possible here
  (no node_modules, 8 GB rule).
- **Done:** investigation, toolchain setup, direct-mode test suite (26 tests
  all passing), game-security review — one real exploit found **and fixed**
  (instant auto-breach via past deadline). Contract lints clean.
- **Done (reviewer-proof e2e):** StudioNet **28/28 PASS** on the canonical
  deploy; Bradbury **1 GEN roundtrip 7/7 PASS** (cost-safe). Full report in
  `docs/dev/PROOFMARK_E2E_REPORT.md`; canonical addresses in
  `intelligent-contracts/README.md`.
- **Done (UI/UX review round):** implemented the then-current UI/UX-recommendations
  items that matter — fresh-quote-then-confirm issue flow, empty-pool buyer gate,
  policy review step, derived policy status, consensus elapsed hint, Claims
  role grouping, IdentityBadge type-DELETE confirm, MetaMask mute, tier rates on
  pool tiles, stat-card skeleton + slow-load timeout, refresh timestamp, tab
  relabel, footnote dedupe. (#7 local activity log deferred; #18 zero-display
  convention already consistent.)
- **Done (2026-09-02):** live Vercel env flipped to the canonical StudioNet
  contract (`0xED90a97A77cd959bB278cBDfA0f2981dF5b5B843`) + redeployed — site
  and repo now point at the same tested deployment.
- **Next:** confirm the redesign visually on the live Vercel build; then
  finish the Project Explorer submission upload (primary tag/sub-tags + logo)
  and link the demo video; optionally expose a conformance-score contract
  read if the Inspect score bar is wanted.

## What's been done

### UI/UX review round — 19-item recommendations, implemented (2026-09-02)
- Worked from the UI/UX-recommendations note against the live frontend
  (`app/page.tsx`, `app/globals.css`, `components/IdentityBadge.tsx`,
  and the client module). No on-chain behavior changed — all edits are UX/flow.
- **Critical fixes:** `doIssue()` re-quotes at pay time (a stale tier can never
  fire a wrong-premium revert); empty-pool is pre-checked via `get_pool_info`
  → targeted "Fund the {tier} pool" notice + button that jumps to the Pools
  tab; claims show a ticking "validators are re-fetching…" hint; Pools "Load
  my stake" is disabled until the identity hydrates.
- **High impact:** every policy goes through a **Review & pay** confirm panel
  (Job/Agent/tier·rate/Coverage/Premium/Deadline/Spec + Edit) before any value
  moves; Inspect-a-policy derives a real status from `deliverable_hash +
  deadline` ("Awaiting delivery" / "Auto-breach available" / "Deliverable
  submitted" / "Ready to claim" / paid-out / expired) with an action tip; spec
  input explains the CID requirement; post-register guidance shows what happens
  next; pool tiles show each tier's premium rate; IdentityBadge's "Generate new
  identity" now needs the word DELETE typed inline instead of a one-click
  `window.confirm`.
- **Polish:** stat card uses a shimmer skeleton + 10s "network may be slow"
  fallback; Refresh shows an "Updated hh:mm:ss" stamp; tab relabelled "Pools"
  and wraps on narrow screens; footnote no longer repeats the hero contract
  address; MetaMask (display-only) section visually muted/italic; contract
  error prefixes `[EXPECTED]` etc. are stripped before display.
- **Deferred deliberately:** #7 (client-side "recent activity" log) — extra
  localStorage surface for little reviewer value and real edge-case risk;
  #18 (zero-display) already reads consistently as `0 GEN` / `—`.
- Files: `frontend/app/page.tsx`, `frontend/app/globals.css`,
  `frontend/components/IdentityBadge.tsx`, `frontend/lib/proofmarkClient.ts`.
  **Pending visual confirmation on the Vercel build** (no local `next build`
  on this 8 GB machine).

### Bradbury value roundtrip PASS — cost-safe 1 GEN (2026-09-02)
- After the 20 GEN deposit burn (below), redesigned the Bradbury check to a
  **1 GEN deposit → withdraw roundtrip** (user-approved budget) on a **fresh**
  deploy `0xcBF4…` so reviewer-facing evidence is clean. `e2e/roundtrip.js`
  reuses the main harness so outcome detection matches.
- **Result: 7/7 PASS.** Deposit 1 GEN ok → pool balance 1 / shares 1 / LP
  position 1 → withdraw 1 GEN ok → pool drained to 0 / position 0
  (`e2e/results/bradbury-roundtrip.log`). This proves value moves **in and back
  out** on a *successful* payable pair on Bradbury — the earlier loss was a
  `LEADER_TIMEOUT` no-verdict, not a contract bug.
- **Harness fix for Bradbury receipts:** they carry **no `consensus_data`** —
  the truth is numeric `txExecutionResult`: `1`=FINISHED_WITH_RETURN
  (success), `2`=FINISHED_WITH_ERROR (revert), `0`=NOT_VOTED. A
  `LEADER_TIMEOUT`/`IDLE`/`NOT_VOTED` tx reached no verdict → reported
  `undetermined`, never `ok`. The old run had mislabeled Bradbury reverts as
  "ok (ACCEPTED)". `submitAndWait` now unions StudioNet (agree-vote rule) and
  Bradbury (numeric) detection.

### Full real-network E2E harness (2026-09-02)
- Built `e2e/run.js` on **genlayer-js** (the same lib the frontend uses) because
  the `genlayer` CLI cannot attach `value` to contract writes, so payable calls
  (deposit / issue_policy / file_claim) need an SDK path. Subcommands:
  `keys | deploy | probe | e2e [--network …] [--address …]`. Deterministic 28-step
  scenario mirroring `tests/direct/test_proofmark.py`, with **unique policy keys per
  run** and amounts asserted in GEN.
- **Revert detection fixed (was a false-positive bug):** a reverted StudioNet
  call still finalizes ACCEPTED/FINALIZED with `result_name=MAJORITY_AGREE`. The
  truth is per-validator (`consensus_data.validators[]`): only validators that
  voted `agree` decide the committed outcome — `reverted ⇔ an agreeing
  validator's execution_result == "ERROR"`. Idle validators routinely report
  `execution_result=ERROR` (they timed out / failed to run), so the earlier
  "any ERROR ⇒ revert" rule mislabeled successful `submit_deliverable` as
  reverted. Validated against ground-truth receipts (success submit, dup-register
  revert, fresh register).
- **Numeric reads fixed:** `readContract` returns u256 as number/string, never
  bigint — added `toBig`/`EQ` coercion for all balance/share/position/premium
  asserts.
- **StudioNet result: 28/28 PASS** on a fresh deployment
  (`0xED90…`, deploy → register → deposit math → quote → 2× payable issue →
  deliverable → negative gates → expire → auto-breach claim upheld → payout →
  counters → full LP withdraw → pool drained to 0).
- **Bradbury result (2026-09-02):** deploy succeeded (fresh `0xcE82…`, roles
  funded lp 25 / agent 3 / buyer 15 GEN) but the **full value e2e was aborted**
  — the 20 GEN LP deposit hit `LEADER_TIMEOUT` (every validator `NOT_VOTED`,
  `result_name=IDLE`) and the GEN is **orphaned in the contract ledger (20.06)**
  with pool state 0. Investigation proved a hard GenLayer behavior on BOTH
  networks: **value on a payable call moves at submission and is NOT refunded if
  the execution reverts or never commits** (StudioNet residue 2.06 = a
  past-deadline-issue premium 0.06 + a premature-claim bond 2; the *successful*
  claim's bond WAS returned). No contract path can recover it (no shares, no
  sweep). Bradbury receipts are a different shape (no `consensus_data`): use
  numeric `txExecutionResult` (2 = FINISHED_WITH_ERROR). **Lesson:** never attach
  value to an expected-revert call; cap live value spends (~1 GEN); get user OK
  before spending faucet GEN. Cost-safe Bradbury plan in task #6.

### Wallet integration — honest browser identity (2026-09-02)
- Implemented the wallet-integration note (now in `archive/`; design distilled
  from the Rigor frontend). Replaced the MetaMask "Connect wallet" flow with a browser
  **identity chip** — because GenLayer studionet tx are signed locally by a
  genlayer-js keypair, and MetaMask can't sign them. The UI says so plainly.
- New `frontend/lib/identity.ts` (localStorage identity key;
  generate/import/reset helpers; works around the viem private-key trap by
  persisting our own copy of the key, not `account.privateKey` which is
  `undefined`), `frontend/app/providers.tsx` (identity context, client-only
  hydration), `frontend/components/IdentityBadge.tsx` (chip + dropdown: address
  + copy, honesty notice, show/copy private key, import-from-key with live
  "Recovers: 0x…" preview, MetaMask display-only, generate-new danger).
- `frontend/lib/proofmarkClient.ts`: write client now signs with the Account object
  (`createClient({ chain, account })`, no provider, no `.connect()`); dropped
  `connectWallet`. `writeContract` always passes `value` (0n when nothing
  moves) because genlayer-js 1.2.0 types require it and its local-account path
  signs value-0 fine — the old "never send value:0" rule only applied to the
  MetaMask provider path.
- `frontend/app/page.tsx`: topbar shows `<IdentityBadge />`; write flows take
  the account from context; LP stake lookup passes `acct.address`.
- Pushed as `13ce1bf`; Vercel rebuild pending. **Not yet visually confirmed.**

### Frontend UI redesign — "bold modern" (2026-09-02)
- User rejected the first UI ("total bullshit") and picked a **bold modern**
  direction: dark navy console + copper glow, glassy panels, big numbers,
  tabbed workbench instead of a wall of cards.
- Rewrote `frontend/app/globals.css` (new token set + components) and
  `frontend/app/page.tsx` (hero + live pool tiles + Agents/Pools/Coverage/
  Claims tabs). Contract calls are **unchanged** — same functions, same args —
  so no new on-chain behavior was introduced.
- Feedback is now structured notices (pending spinner / green ok / red error)
  instead of raw `JSON.stringify` dumps; lookups render as key/value rows with
  tier badges and status chips; pool tiles + TVL load live on mount; pool tiles
  refresh after deposits/withdraws; claims auto-show their verdict after filing.
- Wallet connect lives in the topbar and is shared by every tab.

### Investigation
- Read the whole repo: the contract source, frontend (`app/page.tsx`, the
  client module), `README.md`, `docs/PROOFMARK_UX_FLOW.md`.
- Identified duplicate stale files at the `frontend/` root (top-level copies of
  the client module and of `app/page.tsx`) — dead code, to be removed before
  pushing.
- Frontend hardcodes `studionet`; needs to be network-aware for Bradbury.

### Toolchain setup (Windows 8GB machine)
- genlayer CLI 0.37.1 present; current network = testnet-bradbury, account
  "default" unlocked with ~73.9 GEN.
- Patched `gltest/direct/loader.py` Windows temp-file bug so direct tests run
  (see PROOFMARK_PROJECT_MEMORY.md).
- `genvm-lint check` → **lint passed**; validate blocked by SDK 404 (env issue).
- Confirmed pytest 9.1.1 + genlayer-test 0.29.2 work. Smoke test passed.

### Tests
- Wrote `tests/direct/test_proofmark.py` covering registration, LP deposit/withdraw,
  policy issuance, deliverable submission, claims (deterministic + judged), and
  tier promotion / gaming vectors.
- **Result:** 26 passed in ~2.8s (after the deadline-guard fix), including the
  new regression test `test_issue_policy_rejects_past_deadline`. Contract
  passes `genvm-lint lint`.

### Game-security review
- Reviewed every "can this be gamed" angle the contract documents (sybil tiers,
  empty-pool first depositor, locked-exposure withdrawal, mutable-URL evidence,
  exact-premium enforcement, buyer-supplied evidence).
- **Found & fixed one real exploit:** `issue_policy` never checked that the
  deadline was in the future. A buyer could set an already-passed deadline and
  instantly claim the "no deliverable submitted" auto-breach — no chance for
  the agent to deliver, repeatable with fresh job_ids to drain a tier pool or
  burn an honest agent's reputation in one block. Fixed with a
  "deadline must be a future timestamp" guard in `issue_policy`; documented in
  the contract docstring's gaming-audit section.

## Known issues found
- **Fixed:** past-deadline policy issuance (instant auto-breach exploit).
- `genvm-lint validate` still blocked by SDK 404 (environment, not the
  contract) — deployment + tests are the authoritative validation.
- Frontend is network- and address-driven by env vars
  (`NEXT_PUBLIC_PROOFMARK_NETWORK`, `NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS`). Live
  Vercel env points at StudioNet; after the 2026-09-03 Shape A redeploy the
  env must be **flipped to `0x605e5BE4a8013B2B6c70c4BECa3CEbB7BD7918e4`** and
  the project redeployed (no local CLI token — dashboard action).

## Deployments
- **StudioNet (canonical, Shape A):** `0x605e5BE4a8013B2B6c70c4BECa3CEbB7BD7918e4`
  (deployed 2026-09-03, tx `0xf8e416dc…c6373d8fe`; full e2e **28/28 PASS** on
  this address, pool drained to 0 then re-seeded — see Live seeded state).
- **Bradbury (canonical, Shape A):** `0x79C15889D5070321176994373C440778a9eC47c1`
  (deployed 2026-09-03, tx `0x14222a14…3832350a`; read-verified live).
- Superseded (2026-09-02 unpatched generation, do not use): StudioNet
  `0xED90a97A77cd959bB278cBDfA0f2981dF5b5B843` (28/28 e2e on old source);
  Bradbury `0xcBF48A444242919EEA65Ff5bB6BD9d2CB82506e2` (1 GEN roundtrip 7/7).
- Older still (do not use): StudioNet `0x4870…`; Bradbury `0x1ad8…` (first),
  `0xcE82…` (holds an orphaned 20.06 GEN ledger from the LEADER_TIMEOUT burn —
  left as-is, no recovery path exists).

## Live seeded state (2026-09-03, re-seeded on the Shape A deploy)
- **Purpose:** after each e2e drains the pools, `e2e/seed-live.js` re-seeds real
  activity on the canonical StudioNet contract so the live UI displays funded
  pools + a locked-exposure sliver (the §05 board numbers).
- **Re-seeded via `e2e/seed-live.js`** after the 2026-09-03 redeploy: fresh
  agent `agent-live-1788435546808` (wallet key in `e2e/live-keys.json`,
  git-ignored), LP deposited 10/5/3/2 GEN into unrated/bronze/silver/gold, then
  the buyer role issued 1 GEN of cover (`job-live-1788435546808`, active,
  deadline ~1 h out).
- **Live board now reads:** Unrated `10.06 GEN` (locked sliver `1.00 GEN`),
  Bronze `5`, Silver `3`, Gold `2`. Seed tx hashes: register `0x121e62b3…`,
  deposits `0x3d8f686c…` (unrated 10) / `0xbd5ff4f2…` (bronze 5) /
  `0xcc25f7d7…` (silver 3) / `0x82ca7662…` (gold 2), issue `0xd41dab57…`.
- The seeded policy's 1 GEN stays locked until claimed/expired — residue,
  noted; the demo take can run its own register→deposit→issue→claim loop on
  top (Unrated ≥ 10 GEN, so a 1 GEN payout still clears the 10% cap).

## Final proactive review (2026-09-03) + Shape A patch + redeploy

Adversarial re-read of the contract source for every "reviewer could reject this" angle
(sybil, gamed logic, economic drain, honest-claims accuracy), plus a test-suite
reconfirmation. Finding 1 below (self-deal auto-breach drain) was **patched the
same day — Shape A** (see `docs/PROOFMARK_CONTRACT.md` items 7/9/10) — and both contracts
were **redeployed to fresh canonical addresses** (`docs/PROOFMARK_DEPLOYMENT.md`): StudioNet
`0x605e5BE4a8013B2B6c70c4BECa3CEbB7BD7918e4` (e2e **28/28 PASS**) and Bradbury
`0x79C15889D5070321176994373C440778a9eC47c1` (read-verified). The live board was
re-seeded to the §05 numbers. Suite: `python -m pytest tests/direct/test_proofmark.py
-q` → **28 passed**; `genvm-lint` clean.

### Confirmed present (each has a regression test or a code-level trace)
- Past **and** too-soon (< 60 s) deadlines blocked
  (`test_issue_policy_rejects_past_and_too_soon_deadlines`); a 90 s boundary
  still issues.
- Self-buy rejected — the agent's own owner cannot insure its job
  (`test_issue_policy_rejects_self_buy`).
- Coverage capped to the single-claim pool share at issue
  (`test_issue_policy_coverage_capped_to_single_claim_share`); payout still
  capped at 10% of the pool at claim time even when an earlier payout shrank the
  pool (`test_claim_payout_capped_at_10pct_pool`).
- Empty-pool first-depositor closed: `issue_policy` requires pool_value > 0 and
  coverage ≤ 10% of pool; `deposit` hard-aborts on any unattributed balance with
  no shares.
- LPs cannot withdraw under live coverage (locked-exposure gate,
  `test_withdraw_blocks_under_locked_exposure`).
- Evidence is content-addressed only (CIDv0/v1 shape rejects mutable URLs) and
  is agent-submitted only (a buyer can never attach their own deliverable).
- Exact-premium enforcement, exact 2 GEN claim bond (refunded on upheld,
  forfeited to pool on rejected), one wallet binds one agent forever,
  `_normalize_key` blocks case-variant identity squatting.
- Sybil ladder: min distinct buyer addresses + tenure days + min real spend per
  tier. Honest limit (a chain cannot prove one wallet is one person) is stated
  in the contract docstring and the §03 submission text.

### Finding 1 — self-deal auto-breach drain: PATCHED (Shape A, shipped)
Original finding: a buyer plus its own never-delivering agent (two wallets) can
drain a tier pool that holds third-party LP capital — issue cover up to ~10% of
pool (premium 0.06·C at unrated), let the deadline pass, file the deterministic
auto-breach claim, collect ≈ coverage − premium. The **one-wallet** version (buy
on your own agent) is now **impossible** (item 9, self-buy revert), the deadline
can't be a ~1-second loop anymore (item 7, 60 s floor), and per-policy coverage
is capped to what a single claim pays (item 10). Remaining residual, disclosed
in the contract and `docs/PROOFMARK_CONTRACT.md`: a controller using **two separate
wallets** can still run a slow drip (~coverage − premium per round, bounded to
10% of the pool per round). Insurance that pays out more than its premium is the
mechanism's point — an honest claim is economically identical — so no contract
rule can allow the demo and forbid that drain; the real defence is off-chain.
2. **Bronze promotion still has no breach-rate gate (minor, unpatched):**
   silver/gold require breach_rate ≤ 8%/2%, but bronze only needs 3 insured jobs
   + 2 distinct buyers + 3 days of tenure. A chronic breacher can become cheaper
   to insure (600 → 400 bps). No live path can reach bronze today, so it has
   zero review visibility; one gate line for v1.1.

### QA gap — judged consensus claim never proven on a live network
StudioNet e2e and Bradbury exercised only the **deterministic auto-breach**
claim (no deliverable + passed deadline). The **judged** path (agent submits a
deliverable → validators re-fetch both CIDs and score conformance) has only
ever run in direct-mode tests with web+LLM stubbed. The UI's "Submit a
deliverable" panel makes it reachable by a curious reviewer. Mechanism is
standard GenLayer nondet, so risk is low — but if we want it proven on-chain it
must be smoked **after** the demo take, because a judged payout draws from a
pool and would shift the §05 board numbers mid-filming.

## Documentation (created 2026-09-02)
- `docs/PROOFMARK_DEPLOYMENT.md` — per-network addresses, redeploy + verify steps, network quirks.
- `docs/PROOFMARK_CONTRACT.md` — contract overview, public interface, parameters, security hardening.
- `docs/dev/` — internal working notes (PROOFMARK_PROGRESS.md,
  PROOFMARK_PROJECT_MEMORY.md).

## Next steps
0. **Flip the Vercel env** to `NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS =
   0x605e5BE4a8013B2B6c70c4BECa3CEbB7BD7918e4` and redeploy the project (the
   only outstanding action; no local CLI token). Then verify the live site reads
   the new contract (page foot + board numbers Unrated 10.06 / locked 1.00 /
   Bronze 5 / Silver 3 / Gold 2 + seeded feed).
1. Dry-run the rewritten §05 path live against the final UI on a fresh profile
   (pools are seeded; feed opens with the seeded history), then record the demo
   from the demo plan / captions: ~2-min-deadline claim
   leaves the planted example on-chain. Then fill the remaining `[YOU: …]`
   blanks in the submission note (logo, dropdown tags, YouTube link, the
   planted job id for §05 Step 2 — deploy tx hashes are now recorded in
   `docs/PROOFMARK_DEPLOYMENT.md`) and submit.
2. Keep StudioNet as the live frontend target (Bradbury stays documented only).
3. Optional, AFTER the demo take: live-judged-path smoke on StudioNet (register
   a fresh agent, submit a real deliverable CID, file a claim through consensus)
   so the on-chain history also proves the judged path, not just the auto-breach
   path. Re-verify the §05 board numbers afterwards if its payout shifted them.
