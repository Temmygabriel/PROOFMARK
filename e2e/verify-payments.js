// e2e/verify-payments.js
// Proves GEN actually moves on GenLayer's emit_transfer(on="finalized").
// Closes the "contract says paid but the GEN never moved" failure mode (Mode B)
// that a state-only e2e cannot catch: it snapshots WALLET balances before and
// after each transfer and requires the recipient's balance to rise.
//
// Usage:
//   node e2e/verify-payments.js --network studionet [--address <hex>]
//   node e2e/verify-payments.js --network bradbury  [--address <hex>]
//   REAL_SPEC_URL=... REAL_SPEC_SHA256=... REAL_DELIV_URL=... REAL_DELIV_SHA256=... \
//     node e2e/verify-payments.js --network studionet
//
// Three transfers verified:
//   1. LP deposit  -> withdraw : GEN leaves the LP wallet, enters the pool,
//                                and returns to the LP wallet.
//   2. Auto-breach claim       : the AGENT'S FORFEITED BOND pays COVERAGE to the
//                                buyer and the 2 GEN claim bond is refunded. The
//                                tier pool balance does NOT move (FIX-22) -- the
//                                pre-fix version drained LP capital instead.
//   3. Judged claim            : TWO-PHASE (FIX-19). file_claim escrows a
//                                PENDING claim; the permissionless judge_claim
//                                then re-fetches BOTH real commit-pinned GitHub
//                                files and runs the conformance LLM through
//                                validator consensus. A rejected verdict
//                                forfeits the claim bond to the pool; an upheld
//                                one pays the buyer out of the agent's bond.
//                                Requires a real spec+deliverable url/sha256
//                                pair (see REAL_* env vars below).
//
// Balance-enforcement note: StudioNet is gasless and does NOT enforce balances,
// so wallet-level deltas there are informational only (logged, not failed) --
// the authoritative checks on both networks are the pool-ledger conservation
// reads from the contract. The definitive wallet-credit proof (Mode B closed)
// is a Bradbury run, where balances are enforced; Bradbury is out of scope for
// this deployment pass (deploy-only), so run this there when a value run is made.

import { createAccount, createClient, generatePrivateKey } from "genlayer-js";
import { loadOrGenKeys, accountsFromKeys, makeNetwork } from "./run.js";

const GEN = 10n ** 18n;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
async function getBalance(client, address) {
  // StudioNet RPC is flaky (HTML-page responses, resets) -- retry before
  // giving up so a transient blip never blanks a money-outcome check.
  for (let i = 0; i < 6; i++) {
    try {
      const bal = await client.getBalance({ address });
      return typeof bal === "bigint" ? bal : BigInt(bal);
    } catch (e) {
      const msg = String(e?.message || e);
      if (!/fetch failed|ECONNRESET|socket|not valid JSON|Unexpected token|<!DOCTYPE/i.test(msg)) {
        throw e;
      }
      if (i === 5) {
        console.error(`  getBalance failed for ${address} after 6 attempts:`, msg);
        return null;
      }
      await new Promise((r) => setTimeout(r, 900 * (i + 1)));
    }
  }
  return null;
}

function fmtGen(atto) {
  if (atto === null || atto === undefined) return "UNKNOWN";
  const b = typeof atto === "bigint" ? atto : BigInt(atto);
  const whole = b / GEN;
  const frac = (b % GEN).toString().padStart(18, "0").slice(0, 6);
  return `${whole}.${frac} GEN`;
}

function argvFlag(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const results = [];
function check(name, passed, detail) {
  results.push({ name, passed: !!passed });
  const mark = passed ? "PASS" : "FAIL";
  console.log(`[${mark}] ${name}`);
  if (detail) console.log(`      ${detail}`);
}

/** Enforce a check only where balances are mirrored; elsewhere log + soft-pass. */
function walletCheck(name, hard, detail, netName) {
  if (netName === "bradbury") {
    check(name, hard, detail);
  } else {
    results.push({ name, passed: true, informational: true });
    console.log(`[INFO] ${name} (StudioNet: wallet balances informational)`);
    if (detail) console.log(`      ${detail}`);
  }
}

// ---------------------------------------------------------------------------
// Verification
// ---------------------------------------------------------------------------
async function runVerification(netName, contractAddress) {
  const m = makeNetwork(netName);
  const addr = contractAddress || m.address;
  const readClient = createClient({ chain: m.net.chain }); // wallet getBalance reads
  const keys = loadOrGenKeys(false);
  const accs = accountsFromKeys(keys);

  const LP = accs.lp.address;
  const BUYER = accs.buyer.address;

  console.log(`\n${"=".repeat(64)}`);
  console.log(`Payment Verification — ${netName.toUpperCase()}`);
  console.log(`Contract: ${addr}`);
  console.log(`LP:       ${LP}`);
  console.log(`Buyer:    ${BUYER}`);
  console.log(`${"=".repeat(64)}\n`);

  // -------------------------------------------------------------------------
  // VERIFICATION 1: LP deposit -> withdraw roundtrip
  // -------------------------------------------------------------------------
  console.log("--- Verification 1: LP deposit -> withdraw ---");
  const DEPOSIT = 5n * GEN;

  const lp_before = await getBalance(readClient, LP);
  const pool_before = await m.read("get_pool_info", ["unrated"]);
  console.log(`  LP wallet before:    ${fmtGen(lp_before)}`);
  console.log(`  Pool balance before: ${fmtGen(pool_before?.balance_atto)}`);

  const dep = await m.submitAndWait(accs.lp.account, "deposit", ["unrated"], DEPOSIT);
  check("LP deposit tx finalized as success", dep.ok, `hash: ${dep.hash} status: ${dep.execName}`);

  const lp_after_deposit = await getBalance(readClient, LP);
  const pool_after_deposit = await m.read("get_pool_info", ["unrated"]);
  const lp_delta_deposit =
    lp_before !== null && lp_after_deposit !== null ? lp_before - lp_after_deposit : null;

  walletCheck(
    "LP wallet debited by deposit amount",
    lp_delta_deposit !== null && lp_delta_deposit >= DEPOSIT,
    `before: ${fmtGen(lp_before)} after: ${fmtGen(lp_after_deposit)} delta: ${fmtGen(lp_delta_deposit)}`,
    netName
  );
  check(
    "Pool balance credited by deposit amount",
    BigInt(pool_after_deposit?.balance_atto ?? 0) >= BigInt(pool_before?.balance_atto ?? 0) + DEPOSIT,
    `pool before: ${fmtGen(pool_before?.balance_atto)} pool after: ${fmtGen(pool_after_deposit?.balance_atto)}`
  );

  // The board is shared and may carry a live policy, so the LP cannot always
  // exit the whole position: withdraw() refuses any payout that would leave the
  // tier holding less than its locked exposure -- that capital is backing active
  // coverage, and the refusal is a feature, not a fault. Withdraw HALF the
  // position instead: a genuine round-trip that stays valid on an active board.
  const posBefore = await m.read("get_lp_position", ["unrated", LP]);
  const poolBefore = await m.read("get_pool_info", ["unrated"]);
  const ownedShares = BigInt(String(posBefore));
  const totalShares = BigInt(String(poolBefore?.total_shares ?? 0));
  const poolValue = BigInt(String(poolBefore?.balance_atto ?? 0));
  const locked = BigInt(String(poolBefore?.locked_exposure_atto ?? 0));
  const request = ownedShares / 2n;
  const expectedPayout = totalShares > 0n ? (request * poolValue) / totalShares : 0n;
  console.log(
    `  LP position: ${ownedShares} of ${totalShares} shares; withdrawing ${request} ` +
      `-> expected payout ${fmtGen(expectedPayout)} (tier keeps ` +
      `${fmtGen(poolValue - expectedPayout)}, locked ${fmtGen(locked)})`
  );
  check(
    "Withdrawal leaves the tier's locked exposure fully backed",
    request > 0n && poolValue - expectedPayout >= locked,
    `remaining ${fmtGen(poolValue - expectedPayout)} vs locked ${fmtGen(locked)}`
  );

  const lp_before_withdraw = await getBalance(readClient, LP);
  const wd = await m.submitAndWait(accs.lp.account, "withdraw", ["unrated", request], 0n);
  check("LP withdraw tx finalized as success", wd.ok, `hash: ${wd.hash} status: ${wd.execName}`);

  await sleep(3000); // let the finalized transfer credit
  const lp_after_withdraw = await getBalance(readClient, LP);
  const pool_after_withdraw = await m.read("get_pool_info", ["unrated"]);
  const posAfter = await m.read("get_lp_position", ["unrated", LP]);
  const lp_delta_withdraw =
    lp_before_withdraw !== null && lp_after_withdraw !== null
      ? lp_after_withdraw - lp_before_withdraw
      : null;
  const pool_withdrew = poolValue - BigInt(String(pool_after_withdraw?.balance_atto ?? 0));
  const sharesBurned = ownedShares - BigInt(String(posAfter));

  walletCheck(
    "LP wallet ACTUALLY credited after withdraw",
    lp_delta_withdraw !== null && lp_delta_withdraw > 0n,
    `before: ${fmtGen(lp_before_withdraw)} after: ${fmtGen(lp_after_withdraw)} delta: ${fmtGen(lp_delta_withdraw)}`,
    netName
  );
  check(
    "Pool released EXACTLY the proportional payout for the shares burned",
    pool_withdrew === expectedPayout,
    `released: ${fmtGen(pool_withdrew)} expected: ${fmtGen(expectedPayout)}`
  );
  check(
    "LP share position debited by exactly the shares withdrawn",
    sharesBurned === request,
    `burned: ${sharesBurned} expected: ${request}`
  );
  if (netName === "bradbury") {
    check(
      "[BRADBURY] Pool debit ~= wallet credit (conservation)",
      lp_delta_withdraw !== null && Math.abs(Number(lp_delta_withdraw - pool_withdrew)) < Number(pool_withdrew) / 100,
      `LP received: ${fmtGen(lp_delta_withdraw)} pool released: ${fmtGen(pool_withdrew)}`
    );
  }

  // -------------------------------------------------------------------------
  // VERIFICATION 2: auto-breach claim -> buyer wallet + pool payout
  // -------------------------------------------------------------------------
  console.log("\n--- Verification 2: auto-breach claim payout -> buyer wallet ---");
  const DEPOSIT2 = 12n * GEN; // 1 GEN coverage needs >= ~10 GEN pool (10% cap), margin for premium
  const COVERAGE = 1n * GEN;
  const PREMIUM = (COVERAGE * 600n) / 10000n; // unrated 600 bps
  const BOND = 2n * GEN;

  // Fresh agent wallet every run (run.js e2e binds accs.agent to an id forever).
  const agentPk = generatePrivateKey();
  const agentAcc = createAccount(agentPk);
  const agentWallet = { address: agentAcc.address, account: agentAcc };
  const suffix = `${netName}-${Date.now()}`;
  const agentId = `verify-agent-${suffix}`;
  const jobId = `verify-job-${suffix}`;

  await m.submitAndWait(accs.lp.account, "deposit", ["unrated"], DEPOSIT2);
  await m.submitAndWait(agentWallet.account, "register", [agentId], 0n);

  const deadline = new Date(Date.now() + 65_000).toISOString().replace(/\.\d{3}Z$/, "Z");
  // FIX-22: evidence is a commit-pinned GitHub raw URL + the sha256 of the exact
  // bytes. The auto-breach path never fetches the spec, so only the URL SHAPE is
  // checked on-chain here; the judged path below uses a real resolvable pair.
  const specUrl = `https://raw.githubusercontent.com/proofmark-e2e/evidence/${"a".repeat(40)}/spec.txt`;
  const specSha = "0".repeat(64);
  await m.submitAndWait(
    accs.buyer.account,
    "issue_policy",
    [jobId, agentId, COVERAGE, specUrl, specSha, deadline],
    PREMIUM
  );
  // Shape B consent + the FIX-22 agent bond: the agent must post the coverage.
  await m.submitAndWait(agentWallet.account, "accept_job", [jobId], COVERAGE);
  console.log(`  issued ${jobId} on agent ${agentId}, accepted with a ${fmtGen(COVERAGE)} bond; waiting 70s for the 65s deadline to pass...`);
  await sleep(70_000);

  const buyer_before_claim = await getBalance(readClient, BUYER);
  const pool_before_claim = await m.read("get_pool_info", ["unrated"]);
  const escrow_before_claim = await m.read("get_accounting", ["unrated"]);
  console.log(`  Buyer wallet before claim:   ${fmtGen(buyer_before_claim)}`);
  console.log(`  Pool balance before claim:   ${fmtGen(pool_before_claim?.balance_atto)}`);
  console.log(`  Agent bond escrow:           ${fmtGen(escrow_before_claim?.agent_bond_escrow_atto)}`);
  console.log(`  Expected payout:             ${fmtGen(COVERAGE)}   expected bond refund: ${fmtGen(BOND)}`);

  const claim = await m.submitAndWait(accs.buyer.account, "file_claim", [jobId], BOND);
  check("Claim tx finalized as success", claim.ok, `hash: ${claim.hash} status: ${claim.execName}`);

  const claimStatus = await m.read("get_claim_status", [jobId]);
  check("Contract state shows claim upheld", claimStatus === "upheld", `get_claim_status: ${claimStatus}`);

  await sleep(5_000); // let emit_transfer(on="finalized") credit
  const buyer_after_claim = await getBalance(readClient, BUYER);
  const pool_after_claim = await m.read("get_pool_info", ["unrated"]);
  const escrow_after_claim = await m.read("get_accounting", ["unrated"]);
  const buyer_net_delta =
    buyer_before_claim !== null && buyer_after_claim !== null ? buyer_after_claim - buyer_before_claim : null;
  const pool_delta_claim = BigInt(pool_before_claim?.balance_atto ?? 0) - BigInt(pool_after_claim?.balance_atto ?? 0);

  console.log(`  Buyer wallet after claim:    ${fmtGen(buyer_after_claim)}   (delta ${fmtGen(buyer_net_delta)})`);
  // Buyer pays the 2 GEN bond at submit, then receives refund + 1 GEN payout:
  // net wallet delta on an enforced chain = +1 GEN (payout) when the before
  // snapshot predates the bond debit; positive in all orderings.
  walletCheck(
    "Buyer wallet ACTUALLY increased after upheld claim",
    buyer_net_delta !== null && buyer_net_delta > 0n,
    `delta: ${fmtGen(buyer_net_delta)} (expected positive: payout + bond refund - bond paid)`,
    netName
  );
  // FIX-22: the payout is drawn from the agent's forfeited bond, so the tier
  // pool is MADE WHOLE -- its balance does not move at all. Before the bond this
  // was the drain: the pool paid the coverage and LP capital shrank.
  check(
    "Pool balance UNCHANGED by the payout (agent bond funded it, FIX-22)",
    pool_delta_claim === 0n,
    `pool before: ${fmtGen(pool_before_claim?.balance_atto)} after: ${fmtGen(pool_after_claim?.balance_atto)} delta: ${fmtGen(pool_delta_claim)}`
  );
  // The board is shared, so escrow may still carry another run's bond: assert
  // THIS policy's bond left escrow rather than that escrow is globally zero.
  const escrowBeforeClaim = BigInt(String(escrow_before_claim?.agent_bond_escrow_atto ?? -1));
  const escrowAfterClaim = BigInt(String(escrow_after_claim?.agent_bond_escrow_atto ?? -1));
  check(
    "This policy's agent bond left escrow (forfeited to the pool, then paid out)",
    escrowBeforeClaim >= 0n && escrowBeforeClaim - escrowAfterClaim === COVERAGE,
    `escrow before: ${fmtGen(escrow_before_claim?.agent_bond_escrow_atto)} after: ` +
      `${fmtGen(escrow_after_claim?.agent_bond_escrow_atto)} (delta ${escrowBeforeClaim - escrowAfterClaim}, ` +
      `expected -${COVERAGE})`
  );
  if (netName === "bradbury") {
    check(
      "[BRADBURY] Pool debit == 0 and the bond covered the payout",
      pool_delta_claim === 0n,
      `expected: 0 actual: ${fmtGen(pool_delta_claim)} (coverage ${fmtGen(COVERAGE)} came from the bond)`
    );
  }

  // -------------------------------------------------------------------------
  // VERIFICATION 3 (optional): judged claim
  // Requires a real commit-pinned GitHub evidence pair for BOTH the spec and the
  // deliverable (url + sha256 of the exact bytes). Outcome is whatever the
  // validator LLM majority decides -- both upheld and rejected prove the judged
  // path executes; the bond-forfeiture asserts only hold on a "rejected" verdict.
  // -------------------------------------------------------------------------
  console.log("\n--- Verification 3: judged claim (bond path) ---");
  const realSpecUrl = process.env.REAL_SPEC_URL;
  const realSpecSha = process.env.REAL_SPEC_SHA256;
  const realDelivUrl = process.env.REAL_DELIV_URL;
  const realDelivSha = process.env.REAL_DELIV_SHA256;
  if (!realSpecUrl || !realSpecSha || !realDelivUrl || !realDelivSha) {
    console.log(
      "  [SKIP] REAL_SPEC_URL/REAL_SPEC_SHA256/REAL_DELIV_URL/REAL_DELIV_SHA256 not set " +
        "-- set all four to run the judged path."
    );
  } else {
    const suffix3 = `${netName}-${Date.now()}`;
    const agentId3 = `verify-agent3-${suffix3}`;
    const jobId3 = `verify-job3-${suffix3}`;
    const freshPk3 = generatePrivateKey();
    const freshAcc3 = createAccount(freshPk3);
    const wallet3 = { address: freshAcc3.address, account: freshAcc3 };
    await m.submitAndWait(wallet3.account, "register", [agentId3], 0n);

    // Short deadline (90s): deliverable is submitted immediately, then we wait
    // past the deadline and file a *judged* claim (deliverable present).
    const deadline3 = new Date(Date.now() + 90_000).toISOString().replace(/\.\d{3}Z$/, "Z");
    await m.submitAndWait(accs.buyer.account, "issue_policy", [jobId3, agentId3, COVERAGE, realSpecUrl, realSpecSha, deadline3], PREMIUM);
    await m.submitAndWait(wallet3.account, "accept_job", [jobId3], COVERAGE);
    await m.submitAndWait(wallet3.account, "submit_deliverable", [jobId3, realDelivUrl, realDelivSha], 0n); // live probe: must resolve AND hash-match
    console.log(`  submitted real deliverable ${realDelivUrl} on ${jobId3}; waiting ~100s for deadline...`);
    await sleep(100_000);

    const pool_before_judged = await m.read("get_pool_info", ["unrated"]);
    const escrow_before_judged = await m.read("get_accounting", ["unrated"]);
    const buyer_before_judged = await getBalance(readClient, BUYER);

    // Phase 1 of the two-phase claim (FIX-19 / H-02): file_claim is
    // DETERMINISTIC -- it escrows the bond and records a PENDING claim. It must
    // NOT produce a verdict by itself, so the judgement below is a genuinely
    // separate, retryable step.
    const filed = await m.submitAndWait(accs.buyer.account, "file_claim", [jobId3], BOND);
    check("Claim filed and escrowed (tx finalized)", filed.ok, `hash: ${filed.hash} status: ${filed.execName}`);
    const pendingStatus = await m.read("get_claim_status", [jobId3]);
    check(
      "Two-phase claim: file_claim left a PENDING claim, no verdict yet",
      pendingStatus === "pending",
      `get_claim_status immediately after file_claim: ${pendingStatus}`
    );

    // Phase 2: the judgement. judge_claim is PERMISSIONLESS and NON-payable --
    // called here by the LP account on purpose, to prove any third party can
    // settle a pending claim and that a failed judgement risks no value. It
    // re-fetches BOTH real GitHub files, re-hashes them against the digests
    // committed on-chain at issue/submit time, and runs the conformance prompt
    // through validator consensus. A [TRANSIENT] evidence-host outage reverts
    // with nothing attached, so retrying is always safe.
    let judgedStatus = "pending";
    for (let attempt = 1; attempt <= 3; attempt++) {
      const judged = await m.submitAndWait(accs.lp.account, "judge_claim", [jobId3], 0n);
      console.log(
        `  judge_claim attempt ${attempt}: ${judged.ok ? "ok" : "reverted"} ` +
          `(${judged.execName}) hash: ${judged.hash}`
      );
      for (let i = 0; i < 60; i++) {
        judgedStatus = await m.read("get_claim_status", [jobId3]);
        if (judgedStatus === "upheld" || judgedStatus === "rejected") break;
        await sleep(5_000);
      }
      if (judgedStatus === "upheld" || judgedStatus === "rejected") break;
    }
    check(
      "Judged consensus reached a REAL verdict (upheld or rejected)",
      judgedStatus === "upheld" || judgedStatus === "rejected",
      `get_claim_status: ${judgedStatus}`
    );
    console.log(`  JUDGED_CLAIM_RESULT=${judgedStatus}`);

    if (judgedStatus === "rejected") {
      await sleep(5_000);
      const pool_after_judged = await m.read("get_pool_info", ["unrated"]);
      const escrow_after_judged = await m.read("get_accounting", ["unrated"]);
      const buyer_after_judged = await getBalance(readClient, BUYER);
      const pool_delta_judged =
        BigInt(pool_after_judged?.balance_atto ?? 0) - BigInt(pool_before_judged?.balance_atto ?? 0);
      check(
        "Rejected verdict: pool received EXACTLY the forfeited claim bond",
        pool_delta_judged === BOND,
        `pool before: ${fmtGen(pool_before_judged?.balance_atto)} after: ${fmtGen(pool_after_judged?.balance_atto)} ` +
          `delta: ${fmtGen(pool_delta_judged)} expected: ${fmtGen(BOND)}`
      );
      check(
        "Rejected verdict: agent's bond returned (a failed claim is not a breach)",
        BigInt(escrow_before_judged?.agent_bond_escrow_atto ?? -1) -
          BigInt(escrow_after_judged?.agent_bond_escrow_atto ?? -1) === COVERAGE,
        `escrow before: ${fmtGen(escrow_before_judged?.agent_bond_escrow_atto)} ` +
          `after: ${fmtGen(escrow_after_judged?.agent_bond_escrow_atto)} (expected -${fmtGen(COVERAGE)})`
      );
      walletCheck(
        "Buyer wallet decreased (bond NOT refunded on rejected claim)",
        buyer_before_judged !== null &&
          buyer_after_judged !== null &&
          buyer_after_judged < buyer_before_judged,
        `before: ${fmtGen(buyer_before_judged)} after: ${fmtGen(buyer_after_judged)}`,
        netName
      );
    } else if (judgedStatus === "upheld") {
      await sleep(5_000);
      const pool_after_judged = await m.read("get_pool_info", ["unrated"]);
      check(
        "Upheld verdict: pool UNCHANGED (the forfeited agent bond funded the payout, FIX-22)",
        BigInt(pool_after_judged?.balance_atto ?? 0) === BigInt(pool_before_judged?.balance_atto ?? 0),
        `pool before: ${fmtGen(pool_before_judged?.balance_atto)} after: ${fmtGen(pool_after_judged?.balance_atto)}`
      );
    }
  }

  // -------------------------------------------------------------------------
  // Summary
  // -------------------------------------------------------------------------
  const failed = results.filter((r) => !r.passed);
  console.log(`\n${"=".repeat(64)}`);
  console.log(`Payment Verification — ${netName.toUpperCase()} COMPLETE`);
  console.log(`${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) {
    console.log("\nFAILED:");
    failed.forEach((f) => console.log(`  ${f.name}`));
    console.log(
      "\n  A hard pool-ledger check failed -- the contract's accounting and the chain disagree.\n" +
        "  Do not submit until this passes. (Wallet-credit checks are the Bradbury Mode-B gate.)"
    );
  } else {
    const infoCount = results.filter((r) => r.informational).length;
    console.log("\nAll enforced checks passed.");
    if (infoCount) console.log(`(${infoCount} wallet-credit check(s) informational on StudioNet -- see header note.)`);
  }
  console.log("=".repeat(64));
  return failed.length === 0;
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------
const network = argvFlag("--network") || "studionet";
const address = argvFlag("--address") || undefined;

runVerification(network, address)
  .then((ok) => process.exit(ok ? 0 : 1))
  .catch((e) => {
    console.error("FATAL:", e?.message || e);
    process.exit(1);
  });
