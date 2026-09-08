"use client";

import { createClient } from "genlayer-js";
import { studionet, testnetBradbury } from "genlayer-js/chains";
import { TransactionStatus } from "genlayer-js/types";
import type { GenAccount } from "./identity";

// ---------------------------------------------------------------------------
// Network selection
// ---------------------------------------------------------------------------
// Point the frontend at whichever network your contract is deployed on via
// NEXT_PUBLIC_PROOFMARK_NETWORK. Accepts the CLI-style dashed name or the
// genlayer-js Network string; anything else falls back to studionet.
const NETWORK_RAW = (process.env.NEXT_PUBLIC_PROOFMARK_NETWORK ?? "studionet").trim();
export const NETWORK_NAME: "studionet" | "testnetBradbury" =
  NETWORK_RAW === "testnet-bradbury" || NETWORK_RAW === "testnetBradbury"
    ? "testnetBradbury"
    : "studionet";
const CHAIN = NETWORK_NAME === "testnetBradbury" ? testnetBradbury : studionet;

// Contract address comes from Vercel env at build/runtime -- see .env.example.
// This is the one thing you change per deployment; nothing else in this file
// should need to change to point at a different Proofmark deployment.
export const PROOFMARK_ADDRESS = process.env
  .NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS as `0x${string}` | undefined;

// Fixed contract constants (mirrors proofmark.py -- keep these two in sync if the
// contract's constants ever change).
export const VERDICT_BOND_ATTO = 2n * 10n ** 18n;
export const VALID_TIERS = [
  "unrated",
  "bronze",
  "silver",
  "gold",
  "penalty",
] as const;
export type Tier = (typeof VALID_TIERS)[number];

/** Premium rate in basis points per tier (mirrors RATE_BPS_BY_TIER in proofmark.py).
 * 1 bps = 0.01% of coverage. Keep in sync if the contract's constants change. */
export const RATE_BPS_BY_TIER: Record<Tier, number> = {
  unrated: 600,
  bronze: 400,
  silver: 250,
  gold: 150,
  penalty: 1200,
};

/** Read-only client -- talks directly to the network's RPC, no wallet needed. */
export function getReadClient() {
  return createClient({ chain: CHAIN });
}

// Write client. The "account" here is a genlayer-js / viem *Account object*
// created in the browser from our own private key (see lib/identity.ts), NOT a
// MetaMask address -- GenLayer studionet transactions are signed locally and
// MetaMask cannot sign them. With the account passed into createClient there is
// no provider and no .connect() call: viem signs with the account's key and
// sends straight to the RPC.
export function getWriteClient(account: GenAccount) {
  return createClient({ chain: CHAIN, account });
}

function requireAddress(): `0x${string}` {
  if (!PROOFMARK_ADDRESS) {
    throw new Error(
      "NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS is not set. Add it as an environment " +
        "variable (see .env.example) and redeploy."
    );
  }
  return PROOFMARK_ADDRESS;
}

async function read<T = any>(functionName: string, args: any[] = []): Promise<T> {
  const client = getReadClient();
  return client.readContract({
    address: requireAddress(),
    functionName,
    args,
  }) as Promise<T>;
}

/**
 * Decides whether a finalized write actually executed successfully.
 *
 * On StudioNet a reverted call STILL finalizes FINALIZED/MAJORITY_AGREE, and the
 * receipt exposes no `txExecutionResultName`/`statusName` (reading them yields
 * undefined -- a false "Transaction did not succeed" on EVERY successful write).
 * The truth is per-validator (validated against ground-truth receipts):
 * `consensus_data.validators[]`, each with execution_result + vote; only
 * validators that voted **agree** decide the committed outcome -- reverted <=>
 * an agreeing validator's execution_result is "ERROR". Idle validators routinely
 * report execution_result "ERROR" ("validator execution cancelled after quorum")
 * and must be ignored; scanning any-ERROR mislabels successful submits as
 * reverted. Bradbury carries no consensus_data: numeric txExecutionResult tells
 * all (1=FINISHED_WITH_RETURN success, 2=FINISHED_WITH_ERROR revert, 0=NOT_VOTED).
 * Mirrors the validated classifier in e2e/run.js.
 */
function classifyReceipt(receipt: any): {
  ok: boolean;
  reverted: boolean;
  undetermined: boolean;
  label: string;
} {
  let cd = receipt?.consensus_data;
  if (typeof cd === "string") {
    try { cd = JSON.parse(cd); } catch { cd = null; }
  }
  const raw = Array.isArray(cd?.validators)
    ? cd.validators
    : Array.isArray(cd?.leader_receipt)
      ? cd.leader_receipt
      : [];
  const seen = raw.map((e: any) => ({
    result: e?.execution_result ?? e?.genvm_result?.execution_result ?? null,
    vote: e?.vote ?? null,
    mode: e?.mode ?? null,
  }));
  const agreeing = seen.filter((e: any) => e?.vote === "agree");
  const execNum = receipt?.txExecutionResult;
  const execNm = String(receipt?.txExecutionResultName ?? "");
  const stName = String(receipt?.statusName ?? receipt?.status_name ?? "");
  const rName = String(receipt?.resultName ?? receipt?.result_name ?? "");
  const leaderErr = seen.some((e: any) => e?.mode === "leader" && e?.result === "ERROR");

  if (agreeing.length > 0) {
    const reverted = agreeing.some((e: any) => e?.result === "ERROR");
    return {
      ok: !reverted,
      reverted,
      undetermined: false,
      label: `AGREE[${agreeing.map((e: any) => e?.result).join(",")}]`,
    };
  }
  if (execNum === 2 || /FINISHED_WITH_ERROR/.test(execNm) || leaderErr) {
    return { ok: false, reverted: true, undetermined: false, label: "FINISHED_WITH_ERROR" };
  }
  if (execNum === 1 && /AGREE/.test(rName)) {
    return { ok: true, reverted: false, undetermined: false, label: rName };
  }
  if (/LEADER_TIMEOUT|TIMEOUT/.test(stName) || /IDLE|NOT_VOTED/.test(rName) || execNum === 0) {
    return { ok: false, reverted: false, undetermined: true, label: `UNDETERMINED(${stName}/${rName})` };
  }
  return { ok: !leaderErr, reverted: leaderErr, undetermined: false, label: stName || rName };
}

async function write(
  account: GenAccount,
  functionName: string,
  args: any[],
  value: bigint = 0n
): Promise<{ hash: `0x${string}`; result: any }> {
  const client = getWriteClient(account);
  const hash = await client.writeContract({
    address: requireAddress(),
    functionName,
    args,
    // genlayer-js requires `value` in writeContract's args type. Its own
    // implementation defaults it to 0n and signs value-0 transactions fine on
    // the local-account path (viem account, no MetaMask), so always pass it.
    value,
  });

  // StudioNet finalizes slowly and intermittently: the SDK's default 30s wait
  // (10 x 3s) can run out while a tx sits at ACCEPTED, making a *successful*
  // write look like a failure -- and tempting a retry that would double a
  // payable value (deposit/issue/file_claim). Wait up to ~2 min for FINALIZED
  // before reporting a failure (observed: register reached FINALIZED ~30-60s in).
  const receipt = await client.waitForTransactionReceipt({
    hash,
    status: TransactionStatus.FINALIZED,
    interval: 3000,
    retries: 40,
  });

  // Positive success check (H-04): FINALIZED/ACCEPTED is a *lifecycle* state,
  // not proof of execution success -- a reverted call still finalizes, and on
  // StudioNet the receipt carries no txExecutionResultName at all. classifyReceipt
  // decides from the agreeing validators' execution_result (see above). Success is
  // only claimed when positively proven; an UNDETERMINED / validator-or-leader
  // timeout outcome is surfaced as "no result to assume", never as "done".
  const verdict = classifyReceipt(receipt);
  if (verdict.undetermined) {
    throw new Error(
      `Consensus did not complete (${verdict.label}); no contract result should be assumed for ${hash}.`
    );
  }
  if (verdict.reverted) {
    throw new Error(
      `Transaction did not succeed (${verdict.label}). Check the receipt for ${hash}.`
    );
  }

  return { hash, result: receipt };
}

// ---------------------------------------------------------------------------
// Agent identity & reputation
// ---------------------------------------------------------------------------

export function register(account: GenAccount, agentId: string) {
  return write(account, "register", [agentId]);
}

export function getProfile(agentId: string) {
  return read<{
    owner: string;
    tier: Tier;
    jobs_insured: number | bigint;
    distinct_buyers: number | bigint;
    claims_filed_against: number | bigint;
    claims_upheld_against: number | bigint;
    registered_at: string;
  }>("get_profile", [agentId]);
}

export function agentIdForAddress(address: string) {
  return read<string>("agent_id_for_address", [address]);
}

// ---------------------------------------------------------------------------
// Policies
// ---------------------------------------------------------------------------

export function quotePremium(agentId: string, coverageAtto: bigint) {
  return read<{ tier: Tier; rate_bps: number; premium_atto: number | bigint }>(
    "quote_premium",
    [agentId, coverageAtto]
  );
}

export function issuePolicy(
  account: GenAccount,
  jobId: string,
  agentId: string,
  coverageAtto: bigint,
  specHash: string,
  deadlineIso: string,
  premiumAtto: bigint
) {
  return write(
    account,
    "issue_policy",
    [jobId, agentId, coverageAtto, specHash, deadlineIso],
    premiumAtto
  );
}

export function submitDeliverable(
  account: GenAccount,
  jobId: string,
  deliverableHash: string
) {
  return write(account, "submit_deliverable", [jobId, deliverableHash]);
}

export function expirePolicy(account: GenAccount, jobId: string) {
  return write(account, "expire_policy", [jobId]);
}

/** Agent accepts a pending policy, activating it (and starting the clock). */
export function acceptJob(account: GenAccount, jobId: string) {
  return write(account, "accept_job", [jobId]);
}

/** Agent rejects a pending policy; the buyer's premium is refunded. */
export function rejectJob(account: GenAccount, jobId: string) {
  return write(account, "reject_job", [jobId]);
}

/** Buyer cancels a pending policy before the agent accepts it. */
export function cancelPendingPolicy(account: GenAccount, jobId: string) {
  return write(account, "cancel_pending_policy", [jobId]);
}

export function getPolicy(jobId: string) {
  return read<{
    job_id: string;
    display_job_id: string;
    buyer: string;
    agent_id: string;
    coverage_atto: number | bigint;
    spec_hash: string;
    deliverable_hash: string;
    deadline_iso: string;
    pool_tier: Tier;
    // M-01: the contract also has "pending" (a policy issued but not yet
    // accepted by the agent) -- the frontend type must not drop states the
    // contract can actually return.
    status: "pending" | "active" | "claimed" | "expired";
    agent_accepted: boolean;
  }>("get_policy", [jobId]);
}

// ---------------------------------------------------------------------------
// LP pools
// ---------------------------------------------------------------------------

export function deposit(account: GenAccount, tier: Tier, amountAtto: bigint) {
  return write(account, "deposit", [tier], amountAtto);
}

export function withdraw(account: GenAccount, tier: Tier, shares: bigint) {
  return write(account, "withdraw", [tier, shares]);
}

export function getPoolInfo(tier: Tier) {
  return read<{
    tier: Tier;
    balance_atto: number | bigint;
    total_shares: number | bigint;
    locked_exposure_atto: number | bigint;
  }>("get_pool_info", [tier]);
}

export function getLpPosition(tier: Tier, address: string) {
  return read<number | bigint>("get_lp_position", [tier, address]);
}

// ---------------------------------------------------------------------------
// Claims -- the one call that triggers GenLayer consensus
// ---------------------------------------------------------------------------

export function fileClaim(account: GenAccount, jobId: string) {
  return write(account, "file_claim", [jobId], VERDICT_BOND_ATTO);
}

/**
 * Two-phase claims (FIX-19 / H-02): `fileClaim` only escrows the verdict bond
 * and records the claim as pending -- the GenLayer consensus judgement runs in
 * the non-payable `judgeClaim`, so a failed/aborted judgement can never burn the
 * buyer's bond. Any caller may trigger it once the deliverable is submitted.
 */
export function judgeClaim(account: GenAccount, jobId: string) {
  return write(account, "judge_claim", [jobId]);
}

/** Buyer-only recovery route: refunds the escrowed bond and returns the policy
 * to active, letting the buyer file again. */
export function rescindPendingClaim(account: GenAccount, jobId: string) {
  return write(account, "rescind_pending_claim", [jobId]);
}

export function getClaimStatus(jobId: string) {
  return read<"unresolved" | "pending" | "upheld" | "rejected">(
    "get_claim_status",
    [jobId]
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** The SDK may decode on-chain u256 values as either `number` or `bigint`
 * depending on size -- normalize to bigint before doing any math on them. */
export function toBig(value: number | bigint): bigint {
  return typeof value === "bigint" ? value : BigInt(Math.trunc(value));
}

/** The contract classifies errors with prefixes for the GenLayer validator
 * machinery ([EXPECTED], [EXTERNAL], [TRANSIENT], [LLM_ERROR]). Those leak into
 * the error text a user sees and are noise -- strip them before surfacing. */
export function cleanContractError(message: string): string {
  return message.replace(/\[(?:EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\]\s*/g, "");
}

/** Parses a decimal GEN string ("1.5") into exact atto (10^18) as a bigint,
 * without going through floating point. */
export function parseGenToAtto(input: string): bigint {
  const trimmed = input.trim();
  if (!/^\d+(\.\d+)?$/.test(trimmed)) {
    throw new Error(`Invalid amount: ${input}`);
  }
  const [whole, frac = ""] = trimmed.split(".");
  const paddedFrac = (frac + "0".repeat(18)).slice(0, 18);
  return BigInt(whole) * 10n ** 18n + BigInt(paddedFrac || "0");
}

/** Formats atto (bigint or number) back to a human GEN string for display. */
export function formatAttoToGen(atto: bigint | number, decimals = 6): string {
  const value = typeof atto === "bigint" ? atto : BigInt(Math.trunc(atto));
  const whole = value / 10n ** 18n;
  const frac = value % 10n ** 18n;
  const fracStr = frac.toString().padStart(18, "0").slice(0, decimals);
  return `${whole}.${fracStr}`;
}
