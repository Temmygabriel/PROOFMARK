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

/** Block explorer for the selected network. Review item 4: every write result
 * the UI reports links back to the exact transaction, so a reviewer can verify
 * a claim about a payout (or a rejection) independently of this app. */
export const EXPLORER_BASE =
  NETWORK_NAME === "testnetBradbury"
    ? "https://explorer-bradbury.genlayer.com"
    : "https://explorer-studio.genlayer.com";

export function explorerTxUrl(hash: string): string {
  return `${EXPLORER_BASE}/tx/${hash}`;
}

export function explorerAddressUrl(address: string): string {
  return `${EXPLORER_BASE}/address/${address}`;
}

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

/**
 * A payable call that SUCCEEDED on-chain but was rejected by the contract, with
 * the attached value refunded in the same transaction (FIX-21).
 *
 * This is deliberate, and it is the only value-safe shape available: a reverted
 * payable call on GenLayer does NOT return the attached value — the sender is
 * debited and the value is retained by the contract with no ledger entry
 * (proven live: tx 0x429b0177… left 0.06 GEN in the contract, explorer balance
 * 19.06 → 19.12, against an issue_policy that finalized GENVM RESULT: ERROR).
 * So the contract never reverts on a caller-fixable condition; it accepts the
 * call, refunds in full, and records the precise reason on-chain in
 * `payable_rejections`, readable via `get_rejection(payer, job_id)`.
 *
 * Consequence for this client: a rejected call has NO revert message in its
 * receipt — the receipt is a success. The reason is read back and surfaced
 * here together with the transaction link, so the user sees both the cause and
 * the independent on-chain proof that the refund happened.
 */
export class ContractRejectionError extends Error {
  readonly hash: string;
  readonly explorerUrl: string;
  /** The contract's reason, with GenLayer classification prefixes stripped. */
  readonly reason: string;

  constructor(reason: string, hash: string) {
    const clean = cleanContractError(reason).trim();
    super(
      `${clean} Your funds were refunded in the same transaction — the contract ` +
        `retained nothing. Verify it on the explorer: ${explorerTxUrl(hash)}`
    );
    this.name = "ContractRejectionError";
    this.hash = hash;
    this.explorerUrl = explorerTxUrl(hash);
    this.reason = clean;
  }
}

/** The reason a payable call from `payer` (optionally for `jobId`) was rejected
 * and refunded, or "" if the last such call was not rejected. */
export function getRejection(payer: string, jobId = "") {
  return read<string>("get_rejection", [payer, jobId]);
}

/**
 * After a payable write finalizes, ask the contract whether it rejected the
 * call. A rejection is not a transaction failure — it is a success carrying a
 * refund — so it cannot be caught by the receipt classifier and must be read
 * back explicitly. A failed read-back never turns a proven success into a
 * reported failure: the reason stays readable on-chain via `get_rejection`.
 */
async function assertNotRejected(
  account: GenAccount,
  hash: `0x${string}`,
  jobId = ""
): Promise<void> {
  let reason = "";
  try {
    reason = await getRejection(account.address, jobId);
  } catch {
    return;
  }
  if (reason) throw new ContractRejectionError(reason, hash);
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

export async function issuePolicy(
  account: GenAccount,
  jobId: string,
  agentId: string,
  coverageAtto: bigint,
  specUrl: string,
  specSha256: string,
  deadlineIso: string,
  premiumAtto: bigint
) {
  const res = await write(
    account,
    "issue_policy",
    [jobId, agentId, coverageAtto, specUrl, specSha256, deadlineIso],
    premiumAtto
  );
  // A rejected issue SUCCEEDS on-chain (refund in-call, FIX-21) — read the
  // precise reason back so the UI can show it instead of a bare success.
  await assertNotRejected(account, res.hash, jobId);
  return res;
}

/** Agent attaches the deliverable evidence: a commit-pinned GitHub URL plus the
 * sha256 of the exact bytes it serves. The contract fetches the URL live and
 * refuses the submission outright if the bytes do not hash to `deliverableSha256`
 * (FIX-22) -- so the agent cannot submit a link that does not resolve, and the
 * buyer cannot be shown evidence that differs from what was committed. */
export function submitDeliverable(
  account: GenAccount,
  jobId: string,
  deliverableUrl: string,
  deliverableSha256: string
) {
  return write(account, "submit_deliverable", [jobId, deliverableUrl, deliverableSha256]);
}

export function expirePolicy(account: GenAccount, jobId: string) {
  return write(account, "expire_policy", [jobId]);
}

/** Agent accepts a pending policy, activating it (and starting the clock).
 * PAYABLE and must carry at least the coverage as the agent's bond (FIX-22):
 * the bond — not LP capital — is what pays a breach claim, which is what makes
 * a self-dealing buyer/agent pair lose money instead of draining the pool. */
export function acceptJob(account: GenAccount, jobId: string, bondAtto: bigint) {
  return write(account, "accept_job", [jobId], bondAtto);
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
    // FIX-22 evidence pair: a commit-pinned GitHub URL + the sha256 of the exact
    // bytes it serves. Never a CID -- see EVIDENCE_HOST below.
    spec_url: string;
    spec_sha256: string;
    deliverable_url: string;
    deliverable_sha256: string;
    deadline_iso: string;
    pool_tier: Tier;
    // M-01: the contract also has "pending" (a policy issued but not yet
    // accepted by the agent) -- the frontend type must not drop states the
    // contract can actually return.
    status: "pending" | "active" | "claimed" | "expired";
    agent_accepted: boolean;
    agent_bond_atto: number | bigint;
  }>("get_policy", [jobId]);
}

// ---------------------------------------------------------------------------
// LP pools
// ---------------------------------------------------------------------------

export async function deposit(account: GenAccount, tier: Tier, amountAtto: bigint) {
  const res = await write(account, "deposit", [tier], amountAtto);
  // Rejection here means the deposit was refused AND the GEN refunded in the
  // same transaction (FIX-21) — surface the reason, not a false success.
  await assertNotRejected(account, res.hash);
  return res;
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

export async function fileClaim(account: GenAccount, jobId: string) {
  const res = await write(account, "file_claim", [jobId], VERDICT_BOND_ATTO);
  // A refused claim refunds the bond in-call (FIX-21); read back the reason.
  await assertNotRejected(account, res.hash, jobId);
  return res;
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
// Evidence — a commit-pinned GitHub file, not an IPFS CID
// ---------------------------------------------------------------------------
// The contract accepts evidence ONLY as a permanent raw.githubusercontent.com
// link that names a full 40-character commit SHA (not a branch), plus the
// sha256 of the exact bytes it serves. The commit SHA is what makes the link
// permanent: a branch moves, a commit does not.
export const EVIDENCE_HOST = "raw.githubusercontent.com";

/** Turns whatever link a user pastes into the raw, commit-pinned form the
 * contract requires, or throws a plain-language reason. Accepts both the
 * normal GitHub "blob" page URL and an already-raw URL. */
export function toRawEvidenceUrl(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) throw new Error("Paste a link to the file first.");
  let u: URL;
  try {
    u = new URL(trimmed);
  } catch {
    throw new Error("That does not look like a link. It should start with https://");
  }
  if (u.protocol !== "https:") throw new Error("The link must start with https://");
  if (u.search || u.hash) {
    throw new Error("Remove anything after a ? or # — a link to the file itself has neither.");
  }
  let rest = "";
  if (u.hostname === EVIDENCE_HOST) {
    rest = u.pathname.replace(/^\/+/, "");
  } else if (u.hostname === "github.com") {
    // https://github.com/OWNER/REPO/blob/COMMIT/PATH -> raw/OWNER/REPO/COMMIT/PATH
    const parts = u.pathname.replace(/^\/+/, "").split("/");
    if (parts[2] === "blob" || parts[2] === "raw") {
      parts.splice(2, 1);
      rest = parts.join("/");
    } else {
      throw new Error(
        'Open the file on GitHub first, then copy the link — it should contain "/blob/".'
      );
    }
  } else {
    throw new Error(
      `Evidence must be a file on GitHub (${EVIDENCE_HOST}). Other sites cannot be checked.`
    );
  }
  const segs = rest.split("/");
  const commit = segs[2] ?? "";
  if (!/^[0-9a-f]{40}$/.test(commit)) {
    throw new Error(
      "The link must point at one exact version of the file, not a branch. On GitHub, " +
        'click "History", open the version you want, then copy the link — it will contain a ' +
        "40-character commit id."
    );
  }
  if (segs.length < 4 || !segs.slice(3).join("/")) {
    throw new Error("The link must include the file path, not just the repository.");
  }
  return `https://${EVIDENCE_HOST}/${rest}`;
}

/** Fetches an evidence file in the browser and returns its exact bytes hashed
 * as sha256 (hex) plus the byte count. raw.githubusercontent.com sends
 * `Access-Control-Allow-Origin: *`, so this works from the page with no proxy.
 * What the user previews here is byte-for-byte what the contract will fetch and
 * hash on-chain — if the two ever differed, the contract refuses the evidence. */
export async function fetchEvidenceSha256(
  rawUrl: string
): Promise<{ sha256: string; bytes: number; preview: string }> {
  let res: Response;
  try {
    res = await fetch(rawUrl, { cache: "no-store" });
  } catch {
    throw new Error(
      "Could not reach that link from your browser. Check it opens in a new tab, then try again."
    );
  }
  if (!res.ok) {
    throw new Error(
      `That link returned "not found" (${res.status}). Check the file still exists at that exact commit.`
    );
  }
  const buf = new Uint8Array(await res.arrayBuffer());
  const digest = await crypto.subtle.digest("SHA-256", buf);
  const sha256 = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  const preview = new TextDecoder("utf-8", { fatal: false }).decode(buf.slice(0, 400));
  return { sha256, bytes: buf.byteLength, preview };
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
