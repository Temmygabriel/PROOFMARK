"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import {
  PROOFMARK_ADDRESS,
  NETWORK_NAME,
  VERDICT_BOND_ATTO,
  VALID_TIERS,
  Tier,
  register,
  getProfile,
  quotePremium,
  issuePolicy,
  submitDeliverable,
  acceptJob,
  getPolicy,
  deposit,
  withdraw,
  getPoolInfo,
  getLpPosition,
  fileClaim,
  judgeClaim,
  getClaimStatus,
  ContractRejectionError,
  explorerTxUrl,
  explorerAddressUrl,
  parseGenToAtto,
  formatAttoToGen,
  cleanContractError,
  toBig,
  toRawEvidenceUrl,
  fetchEvidenceSha256,
  EVIDENCE_HOST,
} from "@/lib/proofmarkClient";
import { useIdentity } from "@/app/providers";
import { IdentityBadge } from "@/components/IdentityBadge";
import { ProofmarkLogo } from "@/components/ProofmarkLogo";
import type { GenAccount } from "@/lib/identity";

/* ------------------------------------------------------------------ utils */

const NET_LABEL =
  NETWORK_NAME === "testnetBradbury" ? "Bradbury Testnet" : "StudioNet";

const TIERS: Tier[] = [...VALID_TIERS];

const TIER_NAMES: Record<Tier, string> = {
  unrated: "Unrated",
  bronze: "Bronze",
  silver: "Silver",
  gold: "Gold",
  penalty: "Penalty",
};

/** Format atto-GEN to a tidy GEN string with trailing zeros trimmed. */
function gen(atto: bigint | number, decimals = 4): string {
  const s = formatAttoToGen(toBig(atto), decimals);
  return s.replace(/\.?0+$/, "") || "0";
}

/** Strip GenLayer error-classification prefixes before showing to a human. */
function errText(e: any): string {
  return cleanContractError(e?.message ?? String(e)).trim();
}

/**
 * Notice for a caught error (review item 4). A ContractRejectionError is NOT a
 * transaction failure: the call SUCCEEDED on-chain and the contract refunded
 * the attached value in the same transaction (FIX-21), so there is no revert
 * message to show. Surface the precise on-chain reason plus a link to the
 * transaction that proves the refund.
 */
function errNotice(title: string, e: any): Notice {
  if (e instanceof ContractRejectionError) {
    return {
      status: "error",
      title: `${title.replace(/\s+failed$/i, "")}: not accepted, refunded in full`,
      detail: e.reason,
      href: e.explorerUrl,
      linkLabel: "Verify the refund on the explorer",
    };
  }
  return { status: "error", title, detail: errText(e) };
}

/** Notice for a write proven to have executed, linked to its transaction. */
function txNotice(title: string, hash: string, detail?: string): Notice {
  return {
    status: "ok",
    title,
    detail,
    href: explorerTxUrl(hash),
    linkLabel: "View transaction on the explorer",
  };
}

/* ------------------------------------------------------ live activity feed */

const FEED_KEY = "proofmark.activity.v1";

type FeedEntry = {
  action: "register" | "deposit" | "issue" | "deliverable" | "claim" | "verdict";
  jobId?: string;
  agentId?: string;
  amount?: string; // formatted "X GEN" for the right-hand column
  tier?: string; // human tier name, e.g. "Unrated"
  verdict?: "upheld" | "rejected";
  ts: number;
};

// Canonical seeded StudioNet deployment only (FIX-22 contract, 2026-09-12): on a
// brand-new browser (empty localStorage), replay the REAL activity on that
// contract into the feed so "Recent activity" matches the board a first-time
// reviewer sees. Every entry below is a genuine finalized write on
// 0x849b576f… -- two agents registered, both 1 GEN covers issued, one settled
// upheld claim (the §05 demo: deadline passed with nothing delivered, the
// agent's bond paid the buyer, no LP capital spent), and the LP capital that
// backs each tier. ids/amounts mirror the on-chain txs; the ids embed Date.now()
// so the timestamps come from the runs themselves.
// Any other network or address keeps the feed local-only.
const SEEDED_CONTRACT = "0x849b576f64eca308300d278223951e4a88e1b5d4";
const SEED_TS = 1789233308766; // Date.now() when the §05 demo run landed (2026-09-12)
const SEED_ACTIVITY: FeedEntry[] = [
  // The §05 demo claim, settled: auto-breach upheld, paid from the agent bond.
  { action: "verdict", jobId: "job-live-1789233308766", verdict: "upheld", ts: SEED_TS },
  { action: "issue", jobId: "job-live-1789233308766", agentId: "agent-live-1789233308766", amount: "0.06 GEN", tier: "Unrated", ts: SEED_TS },
  { action: "register", agentId: "agent-live-1789233308766", ts: SEED_TS - 60_000 },
  // The seed policy, still LIVE: active with a 1 GEN bond escrowed (the locked
  // sliver the board shows), so there is deliberately no verdict entry for it.
  { action: "issue", jobId: "job-live-1789232711989", agentId: "agent-live-1789232711989", amount: "0.06 GEN", tier: "Unrated", ts: SEED_TS - 600_000 },
  { action: "register", agentId: "agent-live-1789232711989", ts: SEED_TS - 660_000 },
  // LP capital: these ARE the tier balances the board reads, on-chain right now.
  { action: "deposit", amount: "4 GEN", tier: "Gold", ts: SEED_TS - 700_000 },
  { action: "deposit", amount: "6 GEN", tier: "Silver", ts: SEED_TS - 720_000 },
  { action: "deposit", amount: "10 GEN", tier: "Bronze", ts: SEED_TS - 740_000 },
  { action: "deposit", amount: "20 GEN", tier: "Unrated", ts: SEED_TS - 760_000 },
];

function readFeed(): FeedEntry[] {
  try {
    const raw = localStorage.getItem(FEED_KEY);
    const arr = raw ? (JSON.parse(raw) as FeedEntry[]) : [];
    return Array.isArray(arr) ? arr.slice(0, 20) : [];
  } catch {
    return [];
  }
}

/** Record a confirmed on-chain write so the hero feed can show it. Fire-and-
 * forget: never throws, safe to call from any tab panel. */
function pushFeed(entry: Omit<FeedEntry, "ts">) {
  try {
    seedFeedOnce(); // a first write on a fresh browser stacks above the seeded history
    const next = [{ ...entry, ts: Date.now() }, ...readFeed()].slice(0, 20);
    localStorage.setItem(FEED_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event("proofmark:feed"));
  } catch {
    /* storage can be blocked (private windows) -- the app keeps working */
  }
}

/** First write / first render on a fresh browser: if this is the canonical
 * seeded deploy and localStorage has never been written, lay down the genuine
 * seed history so the feed isn't empty next to the funded board. No-op
 * otherwise (never throws). */
function seedFeedOnce() {
  try {
    if (localStorage.getItem(FEED_KEY) !== null) return; // not a brand-new browser
    if (PROOFMARK_ADDRESS?.toLowerCase() !== SEEDED_CONTRACT) return; // not the seeded deploy
    localStorage.setItem(FEED_KEY, JSON.stringify(SEED_ACTIVITY));
  } catch {
    /* storage can be blocked (private windows) -- the app keeps working */
  }
}

type Notice =
  | { status: "idle" }
  | { status: "pending"; title: string; detail?: string; href?: string; linkLabel?: string }
  | { status: "ok" | "error"; title: string; detail?: string; href?: string; linkLabel?: string };

const idleNotice: Notice = { status: "idle" };

function Notice({ n, style }: { n: Notice; style?: CSSProperties }) {
  if (n.status === "idle") return null;
  const icon = n.status === "pending" ? "" : n.status === "ok" ? "✓" : "✕";
  const title =
    n.title ||
    (n.status === "pending"
      ? "Working…"
      : n.status === "ok"
        ? "Done"
        : "Something went wrong");
  return (
    <div className={`notice ${n.status}`} style={style} role="status">
      <span className="notice-icon">{icon}</span>
      <div className="notice-body">
        <div className="notice-title">{title}</div>
        {n.detail ? <div className="notice-detail">{n.detail}</div> : null}
        {n.href ? (
          <a
            className="notice-link"
            href={n.href}
            target="_blank"
            rel="noreferrer noopener"
          >
            {n.linkLabel ?? "View on the block explorer"} ↗
          </a>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------- evidence (FIX-22) */
// Evidence is a permanently-linked file on GitHub, not a file upload and not an
// IPFS CID. The buyer and the agent use the same three steps, so both sides of a
// job commit to exactly the same bytes and validators can re-fetch them years
// later. Pasting the link here opens it in YOUR browser, fingerprints it
// (sha256), and shows the byte count before anything touches the chain.

type Evidence = {
  /** The canonical https://raw.githubusercontent.com/... link that is committed. */
  rawUrl: string;
  /** sha256 of the exact bytes, committed on-chain alongside the link. */
  sha256: string;
  /** Size of those bytes -- so the user can sanity-check the right file. */
  bytes: number;
  /** First few hundred bytes of the file, so the user sees what was fingerprinted. */
  preview: string;
};

function EvidenceInput({
  id,
  label,
  what,
  hint,
  value,
  onChange,
}: {
  id: string;
  label: string;
  /** Plain-language noun for the file, e.g. "the spec" or "the deliverable". */
  what: string;
  hint?: string;
  value: Evidence | null;
  onChange: (e: Evidence | null) => void;
}) {
  const [link, setLink] = useState("");
  const [n, setN] = useState<Notice>(idleNotice);
  const [busy, setBusy] = useState(false);

  async function doCheck() {
    setBusy(true);
    setN({ status: "pending", title: "Opening your link and fingerprinting the file…" });
    try {
      const rawUrl = toRawEvidenceUrl(link);
      const { sha256, bytes, preview } = await fetchEvidenceSha256(rawUrl);
      onChange({ rawUrl, sha256, bytes, preview });
      setN({
        status: "ok",
        title: `Ready — ${bytes.toLocaleString()} bytes fingerprinted`,
        detail: `sha256 ${sha256}`,
      });
    } catch (e: any) {
      onChange(null);
      setN({ status: "error", title: "That link can't be used yet", detail: errText(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className="input"
        value={link}
        onChange={(e) => {
          setLink(e.target.value);
          if (value) onChange(null); // edited link must be re-checked
          setN(idleNotice);
        }}
        placeholder="https://github.com/you/your-repo/blob/…/file.md"
      />
      <div className="btn-row" style={{ marginTop: 8 }}>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy || !link.trim()}
          onClick={doCheck}
        >
          {busy ? "Checking…" : value ? "Re-check link" : "Check this link"}
        </button>
      </div>
      <p className="hint" style={{ marginTop: 6 }}>
        How to get this link, in three steps:
      </p>
      <ol className="hint" style={{ marginTop: 0, paddingLeft: 20 }}>
        <li>Put {what} in any public GitHub repository.</li>
        <li>
          Open the file on GitHub, click <strong>History</strong>, and open the version you
          want to lock in.
        </li>
        <li>
          Copy the address bar and paste it above. We open it, fingerprint it, and show you
          the size — then that exact fingerprint goes on-chain.
        </li>
      </ol>
      <p className="hint" style={{ marginTop: 0 }}>
        Anything that changes the file changes its fingerprint, so a link that still works
        later is proof the file was never altered. Only files on{" "}
        <span className="mono">{EVIDENCE_HOST}</span> can be checked, and the link must name
        one exact version (a 40-character commit id), never a branch.
        {hint ? <> {hint}</> : null}
      </p>
      <Notice n={n} />
      {value && (
        <div className="evidence-box">
          <div className="evidence-row">
            <span className="pol-k">File size</span>
            <span className="mono">{value.bytes.toLocaleString()} bytes</span>
          </div>
          <div className="evidence-row">
            <span className="pol-k">Fingerprint (sha256)</span>
            <span className="mono evidence-hash">{value.sha256}</span>
          </div>
          <div className="evidence-row">
            <span className="pol-k">Link</span>
            <a
              className="mono evidence-link"
              href={value.rawUrl}
              target="_blank"
              rel="noreferrer noopener"
            >
              {value.rawUrl} ↗
            </a>
          </div>
          {value.preview && (
            <details className="evidence-peek">
              <summary>Preview what was fingerprinted</summary>
              <pre>{value.preview}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

/** Last-N confirmed writes, persisted locally so the board survives reloads. */
function Feed() {  const [entries, setEntries] = useState<FeedEntry[]>([]);

  useEffect(() => {
    seedFeedOnce(); // a fresh browser on the seeded deploy sees its real history
    const load = () => setEntries(readFeed());
    load();
    window.addEventListener("proofmark:feed", load);
    return () => window.removeEventListener("proofmark:feed", load);
  }, []);

  if (entries.length === 0) {
    return (
      <p className="feed-empty">
        Nothing yet. Every confirmed write lands here — register an agent, fund a
        pool, back a job, request a verdict.
      </p>
    );
  }

  return (
    <div className="feed">
      {entries.slice(0, 6).map((e, i) => (
        <div className="feed-item" key={`${e.ts}-${i}`}>
          <span className="feed-dot" style={{ background: feedDotColor(e) }} />
          <div className="feed-action">
            <FeedBody e={e} />
            <div className="feed-time">{timeAgo(e.ts)}</div>
          </div>
          {e.amount && <span className="feed-amount">{e.amount}</span>}
        </div>
      ))}
    </div>
  );
}

function timeAgo(ts: number): string {
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return `${h}h ago`;
}

function feedDotColor(e: FeedEntry): string {
  if (e.action === "verdict") {
    // A verdict marks the delivery OUTCOME: upheld claim = not delivered =
    // breach amber; rejected claim = delivered = settled green.
    return e.verdict === "upheld"
      ? "var(--breach)"
      : e.verdict === "rejected"
        ? "var(--ok)"
        : "var(--text-faint)";
  }
  switch (e.action) {
    case "register":
      return "var(--unrated)";
    case "deposit":
      return "var(--ok)";
    case "issue":
      return "var(--proof)";
    case "deliverable":
      return "var(--proof-bright)";
    case "claim":
    default:
      return "var(--text-faint)";
  }
}

function FeedBody({ e }: { e: FeedEntry }) {
  switch (e.action) {
    case "register":
      return (
        <span>
          Registered agent <b>{e.agentId}</b>
        </span>
      );
    case "deposit":
      return (
        <span>
          Funded the <b>{e.tier ?? "tier"}</b> pool as an LP
        </span>
      );
    case "issue":
      return (
        <span>
          Backed <b>{e.agentId}</b>&apos;s job <b>{e.jobId}</b>
        </span>
      );
    case "deliverable":
      return (
        <span>
          Deliverable recorded for job <b>{e.jobId}</b>
        </span>
      );
    case "claim":
      return (
        <span>
          Verdict requested on job <b>{e.jobId}</b>
        </span>
      );
    case "verdict":
      return e.verdict === "upheld" ? (
        <span>
          Job <b>{e.jobId}</b> <b>NOT DELIVERED</b> — coverage paid to buyer
        </span>
      ) : e.verdict === "rejected" ? (
        <span>
          Job <b>{e.jobId}</b> <b>DELIVERED</b> — claim bond returned
        </span>
      ) : (
        <span>
          Verdict pending for job <b>{e.jobId}</b>
        </span>
      );
  }
}

/** A physical ink stamp for a resolved claim — the one unmistakable element.
 * The stamp names the DELIVERY OUTCOME, not the legal status of the claim:
 * an upheld claim means the job was NOT DELIVERED (amber); a rejected claim
 * means it WAS delivered (settled green). */
function ConformanceStamp({
  v,
  jobId,
  detail,
  amount,
  note,
}: {
  v: Verdict;
  jobId: string;
  detail: string;
  amount?: string;
  note?: string;
}) {
  if (v === "unresolved" || v === "pending") {
    return (
      <div className="verdict-card pending">
        <div className="stamp pending">
          <div className="stamp-text">{v === "pending" ? "In judgement" : "Pending"}</div>
        </div>
        <div className="verdict-info">
          <div className="verdict-job mono">{jobId}</div>
          <div className="verdict-headline">{detail}</div>
          {note && <div className="verdict-detail">{note}</div>}
        </div>
      </div>
    );
  }
  const notDelivered = v === "upheld";
  const state = notDelivered ? "not-delivered" : "delivered";
  return (
    <div className={`verdict-card ${state}`}>
      <div className={`stamp ${state}`}>
        <span className="stamp-icon">{notDelivered ? "✗" : "✓"}</span>
        <span className="stamp-text">
          {notDelivered ? "Not\nDelivered" : "Delivered"}
        </span>
      </div>
      <div className="verdict-info">
        <div className="verdict-job mono">{jobId}</div>
        <div className="verdict-headline">
          {notDelivered
            ? "Delivery failed conformance — coverage paid to buyer"
            : "Delivery confirmed — claim bond returned to claimant"}
        </div>
        {detail && <div className="verdict-detail">{detail}</div>}
      </div>
      {amount && (
        <div className="verdict-amount-col">
          <div className={`verdict-amount ${state}`}>{amount}</div>
          <div className="verdict-amount-label">
            {notDelivered ? "covered" : "bond returned"}
          </div>
        </div>
      )}
      {note && <div className="verdict-note">{note}</div>}
    </div>
  );
}

/** Hero-left pool bars: each tier's pool balance as a share of TVL, with the
 * locked-exposure region drawn dark inside the fill. */
function PoolBars({ pools, tvl }: { pools: Record<Tier, PoolSnap>; tvl: bigint }) {
  const configs: { tier: Tier; color: string; rate: string }[] = [
    { tier: "unrated", color: "var(--unrated)", rate: "6%" },
    { tier: "bronze", color: "var(--bronze)", rate: "4%" },
    { tier: "silver", color: "var(--silver)", rate: "2.5%" },
    { tier: "gold", color: "var(--gold)", rate: "1.5%" },
    { tier: "penalty", color: "var(--penalty)", rate: "12%" },
  ];

  return (
    <div className="tier-bars">
      {configs.map(({ tier, color, rate }) => {
        const p = pools[tier];
        const pct = tvl > 0n && p ? Number((p.balance * 100n) / tvl) : 0;
        const lockedPct = p && p.balance > 0n ? Number((p.locked * 100n) / p.balance) : 0;
        return (
          <div key={tier} className="tb-row">
            <span className="tb-label" style={{ color }}>
              {TIER_NAMES[tier]}
            </span>
            <div className="tb-track">
              <div className="tb-fill" style={{ width: `${pct}%`, background: color }}>
                {lockedPct > 0 && (
                  <div className="tb-locked" style={{ width: `${lockedPct}%` }} />
                )}
              </div>
            </div>
            <span className="tb-val" style={{ color }}>
              {p ? gen(p.balance, 1) : "—"} GEN
            </span>
            <span className="tb-rate" style={{ color }}>
              {rate}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Ticking elapsed-seconds readout for the long consensus waits. */
function Elapsed({ since }: { since: number }) {
  const [s, setS] = useState(0);
  useEffect(() => {
    if (!since) return;
    const id = setInterval(() => setS(Math.max(0, Math.round((Date.now() - since) / 1000))), 1000);
    return () => clearInterval(id);
  }, [since]);
  return <>{s}s</>;
}

/** One-line hint shown while a claim is waiting on validator consensus. */
function ConsensusPending({ since }: { since: number }) {
  if (!since) return null;
  return (
    <p className="hint" style={{ marginTop: 2 }}>
      Validators are independently re-fetching the spec and deliverable and
      scoring conformance. This typically takes 30–90 seconds. (
      <Elapsed since={since} /> elapsed)
    </p>
  );
}

type EnsureWallet = () => Promise<GenAccount>;

/* ------------------------------------------------ domain shapes from reads */

type Profile = {
  owner: string;
  tier: Tier;
  jobs_insured: number | bigint;
  distinct_buyers: number | bigint;
  claims_filed_against: number | bigint;
  claims_upheld_against: number | bigint;
  registered_at: string;
};

type PolicyInfo = {
  buyer: string;
  agent_id: string;
  coverage_atto: number | bigint;
  // FIX-22 evidence: a commit-pinned GitHub link + the sha256 of the exact bytes
  // it serves. Not a CID -- see lib/proofmarkClient.ts.
  spec_url: string;
  spec_sha256: string;
  deliverable_url: string;
  deliverable_sha256: string;
  deadline_iso: string;
  pool_tier: Tier;
  // M-01: the contract also returns "pending" (policy issued, agent has not
  // accepted yet) -- the frontend type must not drop states the contract can
  // actually return.
  status: "pending" | "active" | "claimed" | "expired";
  agent_bond_atto: number | bigint;
};

type Verdict = "unresolved" | "pending" | "upheld" | "rejected";

type PolicyDisplayState = {
  label: string;
  cls: string; // css chip class
  action: string | null; // action-tip text, or null when nothing to do
};

/** Turn raw policy fields into a plain-language statement of where the job
 * stands. "active" is only set once the agent accepts; a "pending" policy is
 * still awaiting acceptance. The real claim signal is the deliverable link +
 * deadline vs now: an empty deliverable past the deadline is an automatic
 * breach the buyer can claim with no risk. */
function derivePolicyState(p: PolicyInfo): PolicyDisplayState {
  const hasDeliv = (p.deliverable_url ?? "").trim().length > 0;
  const dl = Date.parse(p.deadline_iso);
  const pastDeadline = Number.isNaN(dl) ? false : dl <= Date.now();
  if (p.status === "pending")
    return {
      label: "Pending acceptance",
      cls: "awaiting",
      action: "The insured agent hasn't accepted this job yet — premium is escrowed until they do.",
    };
  if (p.status === "claimed")
    return {
      label: "Coverage paid",
      cls: "closed",
      action: "Verdict is final — the coverage already left the pool.",
    };
  if (p.status === "expired")
    return { label: "Closed", cls: "closed", action: null };
  // status === "active":
  if (!hasDeliv && !pastDeadline)
    return { label: "Waiting for delivery", cls: "awaiting", action: null };
  if (!hasDeliv && pastDeadline)
    return {
      label: "Claimable — no delivery",
      cls: "breach",
      action:
        "No deliverable was submitted before the deadline — the clock has already decided. File a claim to collect; there is no bond risk.",
    };
  if (hasDeliv && !pastDeadline)
    return {
      label: "Evidence submitted",
      cls: "submitted",
      action:
        "Only file a claim if the deliverable does not conform to the spec — a wrong claim is rejected and the bond is forfeited.",
    };
  return {
    label: "Ready for verdict",
    cls: "ready",
    action: "Deadline passed with a deliverable on file. File a claim if it did not meet the spec.",
  };
}

/* ============================================================ AGENTS TAB */

function AgentsPanel({ ensureWallet }: { ensureWallet: EnsureWallet }) {
  const [agentId, setAgentId] = useState("agent-alice");
  const [regN, setRegN] = useState<Notice>(idleNotice);

  const [lookId, setLookId] = useState("agent-alice");
  const [prof, setProf] = useState<Profile | null>(null);
  const [profN, setProfN] = useState<Notice>(idleNotice);

  async function doRegister() {
    setRegN({ status: "pending", title: "Registering agent…" });
    try {
      const addr = await ensureWallet();
      const { hash } = await register(addr, agentId);
      setRegN({ status: "ok", title: "Agent registered", detail: `tx ${hash}` });
      pushFeed({ action: "register", agentId: agentId.trim() });
      setLookId(agentId);
      // Surface their own fresh profile straight away so "now what?" is
      // answerable at a glance instead of requiring another Look up click.
      try {
        const p = await getProfile(agentId);
        setProf(p);
      } catch {
        /* profile read is a bonus -- the registration is already confirmed */
      }
    } catch (e: any) {
      setRegN({ status: "error", title: "Registration failed", detail: errText(e) });
    }
  }

  async function doLookup() {
    setProfN({ status: "pending", title: "Reading profile from the ledger…" });
    try {
      const p = await getProfile(lookId);
      setProf(p);
      setProfN(idleNotice);
    } catch (e: any) {
      setProf(null);
      setProfN({ status: "error", title: "Lookup failed", detail: errText(e) });
    }
  }

  return (
    <div className="grid grid-gap-lg">
      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Register your agent</h3>
            <p className="panel-desc">
              Your on-chain track record starts here. Every job you deliver builds
              your reputation. Better track records mean lower rates for your buyers.
            </p>
          </div>
        </div>
        <div className="field">
          <label htmlFor="agentId">Agent ID</label>
          <input id="agentId" className="input" value={agentId} onChange={(e) => setAgentId(e.target.value)} />
        </div>
        <div className="btn-row">
          <button className="btn btn-primary" disabled={regN.status === "pending"} onClick={doRegister}>
            {regN.status === "pending" ? "Registering…" : "Register agent"}
          </button>
        </div>
        <Notice n={regN} />
        {regN.status === "ok" && (
          <p className="hint" style={{ marginTop: -6 }}>
            Your agent is registered. Coverage for your jobs is now available.
            Your rate improves automatically as you build a delivery record.
          </p>
        )}
        <p className="hint">
          Backing a job for an unregistered agent won't work — every job record points
          back at a real registered identity.
        </p>
      </div>

      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Agent reputation</h3>
            <p className="panel-desc">
              Tier, jobs covered, and claim history. This is exactly what the premium
              engine prices off.
            </p>
          </div>
        </div>
        <div className="field">
          <label htmlFor="profId">Agent ID</label>
          <input id="profId" className="input" value={lookId} onChange={(e) => setLookId(e.target.value)} />
        </div>
        <div className="btn-row">
          <button className="btn btn-ghost" disabled={profN.status === "pending"} onClick={doLookup}>
            {profN.status === "pending" ? "Loading…" : "Look up"}
          </button>
        </div>
        <Notice n={profN} />

        {prof && (
          <div className="kv">
            <div>
              <span className="kv-label">Owner</span>
              <span className="kv-value mono">{prof.owner}</span>
            </div>
            <div>
              <span className="kv-label">Tier</span>
              <span className="kv-value">
                <span className={`tier-badge t-${prof.tier}`}>{TIER_NAMES[prof.tier]}</span>
              </span>
            </div>
            <div>
              <span className="kv-label">Jobs covered</span>
              <span className="kv-value">{toBig(prof.jobs_insured).toString()}</span>
            </div>
            <div>
              <span className="kv-label">Distinct buyers</span>
              <span className="kv-value">{toBig(prof.distinct_buyers).toString()}</span>
            </div>
            <div>
              <span className="kv-label">Claims against</span>
              <span className="kv-value">{toBig(prof.claims_filed_against).toString()}</span>
            </div>
            <div>
              <span className="kv-label">Upheld against</span>
              <span className="kv-value">{toBig(prof.claims_upheld_against).toString()}</span>
            </div>
            <div>
              <span className="kv-label">Registered</span>
              <span className="kv-value mono">{prof.registered_at}</span>
            </div>
          </div>
        )}
        {!prof && profN.status !== "error" && (
          <p className="hint">
            Enter an ID above and hit <b>Look up</b> — try{" "}
            <code>{lookId}</code> if you just registered it.
          </p>
        )}
      </div>
    </div>
  );
}

/* ============================================================== POOLS TAB */

function PoolsPanel({
  ensureWallet,
  refreshPools,
  identityReady,
}: {
  ensureWallet: EnsureWallet;
  refreshPools: () => Promise<void>;
  identityReady: boolean;
}) {
  const [depTier, setDepTier] = useState<Tier>("unrated");
  const [depAmount, setDepAmount] = useState("5");
  const [depN, setDepN] = useState<Notice>(idleNotice);

  const [stakeTier, setStakeTier] = useState<Tier>("unrated");
  const [position, setPosition] = useState<bigint | null>(null);
  const [stakeN, setStakeN] = useState<Notice>(idleNotice);
  const [withdrawN, setWithdrawN] = useState<Notice>(idleNotice);

  async function doDeposit() {
    setDepN({ status: "pending", title: "Depositing into the pool…" });
    try {
      const addr = await ensureWallet();
      const atto = parseGenToAtto(depAmount);
      const { hash } = await deposit(addr, depTier, atto);
      setDepN(
        txNotice(
          `Deposited ${gen(atto)} GEN to ${TIER_NAMES[depTier].toLowerCase()}`,
          hash
        )
      );
      pushFeed({ action: "deposit", amount: `${gen(atto)} GEN`, tier: TIER_NAMES[depTier] });
      void refreshPools();
    } catch (e: any) {
      setDepN(errNotice("Deposit failed", e));
    }
  }

  async function doLoadStake() {
    setPosition(null);
    setWithdrawN(idleNotice);
    setStakeN({ status: "pending", title: "Reading your stake…" });
    try {
      const acct = await ensureWallet();
      const shares = toBig(await getLpPosition(stakeTier, acct.address));
      setPosition(shares);
      if (shares === 0n) {
        setStakeN({ status: "ok", title: `No stake in ${TIER_NAMES[stakeTier].toLowerCase()}` });
      } else {
        setStakeN(idleNotice);
      }
    } catch (e: any) {
      setStakeN({ status: "error", title: "Couldn't read your position", detail: errText(e) });
    }
  }

  async function doWithdraw() {
    if (!position || position === 0n) return;
    setWithdrawN({ status: "pending", title: "Withdrawing…" });
    try {
      const addr = await ensureWallet();
      const { hash } = await withdraw(addr, stakeTier, position);
      setPosition(null);
      setWithdrawN({ status: "ok", title: `Withdrew your ${stakeTier} stake`, detail: `tx ${hash}` });
      void refreshPools();
    } catch (e: any) {
      setWithdrawN({ status: "error", title: "Withdrawal failed", detail: errText(e) });
    }
  }

  return (
    <div className="grid grid-gap-lg">
      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Underwrite</h3>
            <p className="panel-desc">
              Earn premiums by underwriting AI agent delivery risk. Capital is pooled
              by agent tier. Payouts are capped per claim. Verdicts are reached by
              GenLayer consensus — not a single judge.
            </p>
          </div>
        </div>
        <div className="form-2col">
          <div className="field">
            <label htmlFor="depTier">Tier</label>
            <select id="depTier" className="input" value={depTier} onChange={(e) => setDepTier(e.target.value as Tier)}>
              {TIERS.map((t) => (
                <option key={t} value={t}>
                  {TIER_NAMES[t]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="depAmt">Amount (GEN)</label>
            <input id="depAmt" className="input" value={depAmount} onChange={(e) => setDepAmount(e.target.value)} />
          </div>
        </div>
        <div className="btn-row">
          <button className="btn btn-primary" disabled={depN.status === "pending"} onClick={doDeposit}>
            {depN.status === "pending" ? "Depositing…" : "Add capital"}
          </button>
        </div>
        <Notice n={depN} />
        <p className="hint">
          The wallet you connect must actually hold GEN on {NET_LABEL} — premium and
          deposits are real token transfers, not just gas. Amounts are matched to the
          atto (10⁻¹⁸), so what you type is exactly what moves.
        </p>
      </div>

      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Your LP stake</h3>
            <p className="panel-desc">
              Shares are minted proportional to the pool at deposit time. See what you
              hold, then pull it back out.
            </p>
          </div>
        </div>
        <div className="form-2col">
          <div className="field">
            <label htmlFor="stakeTier">Tier</label>
            <select id="stakeTier" className="input" value={stakeTier} onChange={(e) => setStakeTier(e.target.value as Tier)}>
              {TIERS.map((t) => (
                <option key={t} value={t}>
                  {TIER_NAMES[t]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Your shares</label>
            <input
              className="input"
              value={position === null ? (!identityReady ? "identity loading…" : "—") : position.toString()}
              readOnly
            />
          </div>
        </div>
        <div className="btn-row">
          <button
            className="btn btn-ghost"
            disabled={stakeN.status === "pending" || !identityReady}
            onClick={doLoadStake}
          >
            {stakeN.status === "pending"
              ? "Loading…"
              : !identityReady
                ? "Identity loading…"
                : position === null
                  ? "Load my stake"
                  : "Re-check"}
          </button>
          {position !== null && position > 0n && (
            <button className="btn btn-primary" disabled={withdrawN.status === "pending"} onClick={doWithdraw}>
              {withdrawN.status === "pending" ? "Withdrawing…" : "Withdraw capital"}
            </button>
          )}
        </div>
        <Notice n={stakeN} />
        <Notice n={withdrawN} />
        {position !== null && position > 0n && (
          <p className="hint">
            Withdrawing converts your {position.toString()} shares back to GEN at the
            pool&apos;s current value and removes the backing they provided.
          </p>
        )}
      </div>
    </div>
  );
}

/* =========================================================== COVERAGE TAB */

function CoveragePanel({
  ensureWallet,
  onGoPools,
  identityAddr,
}: {
  ensureWallet: EnsureWallet;
  onGoPools: () => void;
  /** Current signer address (lowercased), used to gate agent-only actions. */
  identityAddr: string | null;
}) {
  const [jobId, setJobId] = useState("job-001");
  const [covAgentId, setCovAgentId] = useState("agent-alice");
  const [coverage, setCoverage] = useState("1");
  // The spec the job is judged against: verified in-browser, then committed
  // as (link, sha256) on-chain at issue time.
  const [spec, setSpec] = useState<Evidence | null>(null);
  const [deadline, setDeadline] = useState(() => {
    const d = new Date(Date.now() + 30 * 86400000);
    return d.toISOString().slice(0, 19) + "Z";
  });

  const [quote, setQuote] = useState<{ tier: Tier; rate_bps: number; premiumAtto: bigint } | null>(null);
  const [quoteN, setQuoteN] = useState<Notice>(idleNotice);
  const [issueN, setIssueN] = useState<Notice>(idleNotice);

  // Set when the quote succeeded but the agent's tier pool has no LP capital.
  const [needPool, setNeedPool] = useState<Tier | null>(null);

  const [polJob, setPolJob] = useState("job-001");
  const [pol, setPol] = useState<PolicyInfo | null>(null);
  // Verdict read for a looked-up policy, only present once it was claimed.
  const [polClaim, setPolClaim] = useState<Verdict | null>(null);
  const [polN, setPolN] = useState<Notice>(idleNotice);
  // Agent accept/reject on a pending policy (the agent's own wallet only).
  const [actN, setActN] = useState<Notice>(idleNotice);
  // Owner of the looked-up policy's agent — a pending policy only becomes
  // active when that wallet accepts it, so gate the action on the signer.
  const [polOwner, setPolOwner] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    if (!pol || pol.status !== "pending") {
      setPolOwner(null);
      return;
    }
    getProfile(pol.agent_id)
      .then((p) => {
        if (alive) setPolOwner(String(p.owner).toLowerCase());
      })
      .catch(() => {
        if (alive) setPolOwner(null);
      });
    return () => {
      alive = false;
    };
  }, [pol]);
  const isAgentOwner =
    !!identityAddr && !!polOwner && identityAddr === polOwner;

  async function doQuote() {
    setQuote(null);
    setNeedPool(null);
    setQuoteN({ status: "pending", title: "Pricing the risk…" });
    try {
      const cov = parseGenToAtto(coverage);
      const q = await quotePremium(covAgentId, cov);
      const premiumAtto = toBig(q.premium_atto);
      setQuote({ tier: q.tier, rate_bps: Number(q.rate_bps), premiumAtto });
      // Empty-pool gate surfaces here, right after the quote, so the box below
      // shows the "fund the pool" action instead of a dead "Issue" button.
      const pool = await getPoolInfo(q.tier);
      if (toBig(pool.balance_atto) === 0n) {
        setNeedPool(q.tier);
        setQuoteN({
          status: "error",
          title: `No capital in the ${TIER_NAMES[q.tier]} pool yet`,
          detail: `Add capital in the Underwrite tab to enable coverage for this agent tier.`,
        });
        return;
      }
      setQuoteN(idleNotice);
    } catch (e: any) {
      setQuoteN({ status: "error", title: "Couldn't get a quote", detail: errText(e) });
    }
  }

  /** One-click buy. Re-quotes at the exact moment of payment so a stale tier
   * can never fire a wrong-premium revert — a drift just refreshes the box
   * and asks for one more click. Empty pools redirect to funding. On success
   * the new policy auto-appears in the status panel. */
  async function doIssue() {
    if (!quote) return;
    setIssueN(idleNotice);
    setNeedPool(null);
    try {
      const cov = parseGenToAtto(coverage);
      const q = await quotePremium(covAgentId, cov);
      const freshPremium = toBig(q.premium_atto);
      setQuote({ tier: q.tier, rate_bps: Number(q.rate_bps), premiumAtto: freshPremium });
      const pool = await getPoolInfo(q.tier);
      if (toBig(pool.balance_atto) === 0n) {
        setNeedPool(q.tier);
        setIssueN({
          status: "error",
          title: `No capital in the ${TIER_NAMES[q.tier]} pool yet`,
          detail: `Add capital in the Underwrite tab to enable coverage for this agent tier.`,
        });
        return;
      }
      // Premium drifted since the quote was shown: refresh the box rather than
      // send an amount the chain would reject as a wrong exact premium.
      if (freshPremium !== quote.premiumAtto) {
        setQuoteN(idleNotice);
        setIssueN({
          status: "ok",
          title: "Premium updated",
          detail: `The tier rate moved — the box now shows the current ${gen(freshPremium)} GEN. Press "Back this job" again to pay exactly that.`,
        });
        return;
      }
      if (!spec) {
        setIssueN({
          status: "error",
          title: "Check the spec link first",
          detail:
            "Paste a link to the spec file and press “Check this link”. The job is judged against those exact bytes, so the link and its fingerprint must be locked in before backing.",
        });
        return;
      }
      setIssueN({ status: "pending", title: "Backing job on-chain…" });
      const addr = await ensureWallet();
      const job = jobId.trim();
      const agent = covAgentId.trim();
      const { hash } = await issuePolicy(
        addr,
        job,
        agent,
        cov,
        spec.rawUrl,
        spec.sha256,
        deadline,
        quote.premiumAtto
      );
      setQuote(null);
      setQuoteN(idleNotice);
      setIssueN(txNotice("Job is backed", hash));
      pushFeed({
        action: "issue",
        jobId: job,
        agentId: agent,
        amount: `${gen(quote.premiumAtto)} GEN`,
        tier: TIER_NAMES[q.tier],
      });
      // Surface the new policy in the status panel immediately.
      setPolJob(job);
      setPolN({ status: "pending", title: "Reading your new job record…" });
      try {
        const p = await getPolicy(job);
        setPol(p);
        setPolClaim(p.status === "claimed" ? await readClaimStatus(job) : null);
        setPolN(idleNotice);
      } catch {
        setPolN(idleNotice);
      }
    } catch (e: any) {
      setIssueN(errNotice("Back failed", e));
    }
  }

  /** get_claim_status is a bonus read that can 404 if no claim ever existed. */
  async function readClaimStatus(job: string): Promise<Verdict | null> {
    try {
      return (await getClaimStatus(job)) as Verdict;
    } catch {
      return null;
    }
  }

  async function doPolicyLookup() {
    setPolN({ status: "pending", title: "Reading job record…" });
    try {
      const p = await getPolicy(polJob);
      setPol(p);
      setPolClaim(p.status === "claimed" ? await readClaimStatus(polJob.trim()) : null);
      setPolN(idleNotice);
    } catch (e: any) {
      setPol(null);
      setPolClaim(null);
      setPolN({ status: "error", title: "Lookup failed", detail: errText(e) });
    }
  }

  /** Agent-only: bind a pending policy by accepting it (pending -> active), and
   * post the FIX-22 agent bond. Only the wallet registered as the policy's agent
   * succeeds; the contract enforces it, and the notice shows the revert if a
   * wrong wallet tries. The bond is what pays a breach claim — never LP capital
   * — and it comes back in full when the job is delivered or expires. */
  async function doAccept() {
    if (!pol) return;
    const bond = toBig(pol.coverage_atto);
    setActN({
      status: "pending",
      title: `Posting ${gen(bond)} GEN bond and accepting…`,
    });
    try {
      const addr = await ensureWallet();
      const { hash } = await acceptJob(addr, polJob.trim(), bond);
      setActN({
        status: "ok",
        title: "Job accepted — bond posted",
        detail: `tx ${hash} — coverage is live and the clock is running. Your ${gen(bond)} GEN bond is held and returns in full if you deliver or the job expires.`,
      });
      await doPolicyLookup(); // refresh the card: pending -> Waiting for delivery
    } catch (e: any) {
      setActN({ status: "error", title: "Accept failed", detail: errText(e) });
    }
  }

  // Derived display state for the policy-status card + verdict strip.
  const st = pol ? derivePolicyState(pol) : null;
  const resolved =
    pol?.status === "claimed" && (polClaim === "upheld" || polClaim === "rejected")
      ? polClaim
      : null;
  const chipLabel =
    pol?.status === "claimed"
      ? polClaim === "upheld"
        ? "Coverage paid"
        : polClaim === "rejected"
          ? "Delivery confirmed"
          : "Pending"
      : st?.label;
  const chipCls =
    pol?.status === "claimed"
      ? polClaim === "upheld"
        ? "closed"
        : polClaim === "rejected"
          ? "delivered"
          : "awaiting"
      : st?.cls ?? "";
  const noDeliverable = !pol || !(pol.deliverable_url ?? "").trim();
  const scoreNote = resolved
    ? resolved === "upheld"
      ? noDeliverable
        ? "Deterministic breach: no deliverable was on file by the deadline, so validators committed it — no conformance score."
        : "Validators independently re-fetched the spec and the deliverable and scored conformance below 40. NOT DELIVERED — the pool paid the buyer the coverage."
      : "Validators independently re-fetched the spec and the deliverable and scored conformance at 40 or above. DELIVERED — the claim was rejected and the bond forfeited to the pool."
    : pol?.status === "claimed"
      ? "This claim is being resolved — validators are independently re-fetching the evidence."
      : pol
        ? "Conformance is scored 0–100 against the spec. A claim is upheld below 40; 40 or higher pays nothing."
        : null;

  return (
    <div className="grid grid-gap-lg coverage-main">
      {/* --------------------------------------------- quote & issue (left) */}
      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Back a job</h3>
            <p className="panel-desc">
              Premiums are exact and deterministic — quote first, then back.
            </p>
          </div>
        </div>
        <div className="form-2col">
          <div className="field">
            <label htmlFor="covAgent">Agent ID</label>
            <input id="covAgent" className="input" value={covAgentId} onChange={(e) => setCovAgentId(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="covAmt">Coverage (GEN)</label>
            <input id="covAmt" className="input" value={coverage} onChange={(e) => setCoverage(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="covJob">Job ID</label>
          <input id="covJob" className="input" value={jobId} onChange={(e) => setJobId(e.target.value)} />
        </div>
        <EvidenceInput
          id="specUrl"
          label="Spec — link to the file on GitHub"
          what="the spec (what the job must deliver)"
          hint="This is the document validators score the deliverable against."
          value={spec}
          onChange={setSpec}
        />
        <div className="field">
          <label htmlFor="deadline">Deadline (ISO, must be future)</label>
          <input id="deadline" className="input" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
        </div>
        <div className="btn-row">
          <button className="btn btn-ghost" disabled={quoteN.status === "pending"} onClick={doQuote}>
            {quoteN.status === "pending" ? "Pricing…" : quote ? "Re-quote" : "Get quote"}
          </button>
        </div>
        <Notice n={quoteN} />

        {quote && (
          <div className="quote-box">
            <div className="quote-left">
              <span className={`quote-tier-badge t-${quote.tier}`}>
                {TIER_NAMES[quote.tier]} tier · {quote.rate_bps / 100}%
              </span>
              <span className="quote-label">Premium due</span>
              <span className="quote-premium">
                {gen(quote.premiumAtto)} <span>GEN</span>
              </span>
            </div>
            {!needPool ? (
              <button
                className="btn btn-primary issue-cta"
                disabled={issueN.status === "pending"}
                onClick={doIssue}
              >
                {issueN.status === "pending" ? "Backing…" : "Back this job →"}
              </button>
            ) : (
              <button className="btn btn-ghost btn-sm issue-cta" onClick={onGoPools}>
                Fund the {TIER_NAMES[needPool].toLowerCase()} pool as an LP
              </button>
            )}
          </div>
        )}
        <Notice n={issueN} />
      </div>

      {/* ------------------------------------------- policy status (right) */}
      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Job record</h3>
            <p className="panel-desc">Live state of any job on the rail.</p>
          </div>
        </div>
        <div className="field">
          <label htmlFor="polJob">Job ID</label>
          <div className="pol-lookup-row">
            <input
              id="polJob"
              className="input"
              value={polJob}
              onChange={(e) => setPolJob(e.target.value)}
            />
            <button className="btn btn-ghost" disabled={polN.status === "pending"} onClick={doPolicyLookup}>
              {polN.status === "pending" ? "Loading…" : "Look up"}
            </button>
          </div>
        </div>
        <Notice n={polN} />

        {pol && st && (
          <div className={`pol-card ${chipCls}`}>
            <div className="pol-head">
              <span className="pol-k">Status</span>
              <span className={`chip ${chipCls}`}>{chipLabel}</span>
            </div>
            <div className="pol-grid">
              <div className="pol-cell">
                <span className="pol-k">Agent</span>
                <span className="pol-v mono">{pol.agent_id}</span>
              </div>
              <div className="pol-cell">
                <span className="pol-k">Pool tier</span>
                <span className="pol-v">
                  <span className={`tier-badge t-${pol.pool_tier}`}>{TIER_NAMES[pol.pool_tier]}</span>
                </span>
              </div>
              <div className="pol-cell">
                <span className="pol-k">Coverage</span>
                <span className="pol-v mono">{gen(pol.coverage_atto)} GEN</span>
              </div>
              <div className="pol-cell">
                <span className="pol-k">
                  {resolved
                    ? resolved === "upheld"
                      ? "Coverage paid"
                      : "Bond forfeited"
                    : "Payout"}
                </span>
                <span
                  className={`pol-v mono ${resolved === "upheld" ? "ok" : resolved === "rejected" ? "dim" : ""}`}
                >
                  {resolved === "upheld"
                    ? `${gen(pol.coverage_atto)} GEN`
                    : resolved === "rejected"
                      ? `${gen(VERDICT_BOND_ATTO)} GEN`
                      : "—"}
                </span>
              </div>
              <div className="pol-cell">
                <span className="pol-k">Agent bond held</span>
                <span className="pol-v mono">
                  {toBig(pol.agent_bond_atto) > 0n
                    ? `${gen(pol.agent_bond_atto)} GEN`
                    : "— not posted yet"}
                </span>
              </div>
            </div>

            <div className="pol-evidence">
              <div className="pol-k">Evidence on file</div>
              <div className="evidence-row">
                <span className="pol-k">Spec</span>
                {pol.spec_url ? (
                  <a
                    className="mono evidence-link"
                    href={pol.spec_url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {pol.spec_url} ↗
                  </a>
                ) : (
                  <span className="dim">—</span>
                )}
              </div>
              {pol.spec_sha256 ? (
                <div className="evidence-row">
                  <span className="pol-k">Spec sha256</span>
                  <span className="mono evidence-hash">{pol.spec_sha256}</span>
                </div>
              ) : null}
              <div className="evidence-row">
                <span className="pol-k">Deliverable</span>
                {pol.deliverable_url ? (
                  <a
                    className="mono evidence-link"
                    href={pol.deliverable_url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {pol.deliverable_url} ↗
                  </a>
                ) : (
                  <span className="dim">— nothing submitted</span>
                )}
              </div>
              {pol.deliverable_sha256 ? (
                <div className="evidence-row">
                  <span className="pol-k">Deliverable sha256</span>
                  <span className="mono evidence-hash">{pol.deliverable_sha256}</span>
                </div>
              ) : null}
            </div>

            {pol.status === "pending" && isAgentOwner && (
              <div className="pol-act">
                <p className="hint" style={{ margin: 0 }}>
                  You registered this agent. Accepting binds the coverage, starts the
                  clock, and posts a{" "}
                  <strong>{gen(pol.coverage_atto)} GEN bond</strong> — the same size as
                  the coverage. The bond is what pays the buyer if you breach; it comes
                  back in full when you deliver or when the job expires. The buyer&apos;s
                  premium stays escrowed until you accept.
                </p>
                <div className="btn-row" style={{ marginTop: 10 }}>
                  <button
                    className="btn btn-primary"
                    disabled={actN.status === "pending"}
                    onClick={doAccept}
                  >
                    {actN.status === "pending"
                      ? "Posting bond…"
                      : `Accept job + post ${gen(pol.coverage_atto)} GEN bond`}
                  </button>
                </div>
                <Notice n={actN} />
              </div>
            )}
          </div>
        )}
        {!pol && polN.status !== "error" && (
          <p className="hint">
            Look up a job id to see its status, coverage, pool tier — and, once a
            claim resolves, the verdict stamp lands below.
          </p>
        )}
      </div>

      {/* full-width verdict strip: only for a real, resolved inspection */}
      {resolved && pol && (
        <div className="verdict-panel">
          <ConformanceStamp
            v={resolved}
            jobId={`${polJob.trim()} · ${pol.agent_id} · ${TIER_NAMES[pol.pool_tier]} tier`}
            detail={
              resolved === "upheld"
                ? "Conformance scored below 40 — the deliverable failed the spec, so the pool paid the buyer the full coverage."
                : "Conformance scored at or above 40 — the deliverable met the spec, so the claim was dismissed and the bond forfeited to the pool."
            }
            amount={
              resolved === "upheld"
                ? `${gen(pol.coverage_atto)} GEN`
                : `${gen(VERDICT_BOND_ATTO)} GEN`
            }
            note={
              resolved === "upheld"
                ? "The verdict is final on-chain — the coverage moved from the pool and the claim bond was returned. No one clicked pay."
                : "The verdict is final on-chain — the claim bond was forfeited into the pool."
            }
          />
        </div>
      )}
      {pol?.status === "claimed" && !resolved && (
        <div className="verdict-panel">
          <p className="hint" style={{ gridColumn: "1 / -1" }}>
            This claim is still being resolved — the verdict stamp will land here once
            consensus commits.
          </p>
        </div>
      )}
    </div>
  );
}

/* ============================================================ VERDICTS TAB */

function ClaimsPanel({ ensureWallet }: { ensureWallet: EnsureWallet }) {
  // -- deliverable (agent side)
  const [dJobId, setDJobId] = useState("job-001");
  // The delivered work: verified in-browser, then committed as (link, sha256).
  const [dEvidence, setDEvidence] = useState<Evidence | null>(null);
  const [dN, setDN] = useState<Notice>(idleNotice);

  // -- claim (buyer side)
  const [cJobId, setCJobId] = useState("job-001");
  const [cN, setCN] = useState<Notice>(idleNotice);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  // When a claim started waiting on validator consensus (epoch ms) -- drives
  // the ticking "what are the validators doing" hint.
  const [cSince, setCSince] = useState<number | null>(null);

  // -- verdict check
  const [vJobId, setVJobId] = useState("job-001");
  const [vResult, setVResult] = useState<Verdict | null>(null);
  const [vN, setVN] = useState<Notice>(idleNotice);

  async function doDeliver() {
    if (!dEvidence) {
      setDN({
        status: "error",
        title: "Check the deliverable link first",
        detail:
          "Paste a link to the delivered file and press “Check this link”. The contract re-opens that exact link and refuses the submission if the bytes no longer match, so an unchecked link would just fail on-chain.",
      });
      return;
    }
    setDN({ status: "pending", title: "Submitting deliverable…" });
    try {
      const addr = await ensureWallet();
      const { hash } = await submitDeliverable(
        addr,
        dJobId,
        dEvidence.rawUrl,
        dEvidence.sha256
      );
      setDN({
        status: "ok",
        title: "Deliverable recorded",
        detail: `tx ${hash} — the contract re-fetched the file and confirmed the fingerprint matches.`,
      });
      pushFeed({ action: "deliverable", jobId: dJobId.trim() });
    } catch (e: any) {
      setDN({ status: "error", title: "Submission failed", detail: errText(e) });
    }
  }

  async function doFileClaim() {
    setVerdict(null);
    setCN({ status: "pending", title: "Requesting verdict — waiting on validator consensus…" });
    setCSince(Date.now());
    try {
      const addr = await ensureWallet();
      const { hash } = await fileClaim(addr, cJobId);
      // Two-phase claim (FIX-19/H-02): file_claim only escrows the bond and
      // records the claim as `pending` -- the consensus judgement runs in the
      // separate, non-payable judge_claim so a failed judgement can never burn
      // the bond. With a deliverable present the claim is still pending after
      // file_claim, so trigger judge_claim before reading the final verdict;
      // with no deliverable (auto-breach) file_claim already resolved it.
      pushFeed({ action: "claim", jobId: cJobId.trim() });
      let v = (await getClaimStatus(cJobId)) as Verdict;
      if (v === "pending") {
        await judgeClaim(addr, cJobId);
        v = (await getClaimStatus(cJobId)) as Verdict;
      }
      setCSince(null);
      setVerdict(v);
      setCN(idleNotice); // the verdict stamp below says it all
      // Only a resolved verdict belongs on the feed -- never a still-pending
      // claim (two-phase) or an unresolved lookup.
      if (v === "upheld" || v === "rejected")
        pushFeed({ action: "verdict", jobId: cJobId.trim(), verdict: v });
    } catch (e: any) {
      setCSince(null);
      setCN(errNotice("Request failed", e));
    }
  }

  async function doCheckVerdict() {
    setVN({ status: "pending", title: "Checking verdict…" });
    try {
      const v = (await getClaimStatus(vJobId)) as Verdict;
      setVResult(v);
      setVN(idleNotice);
    } catch (e: any) {
      setVResult(null);
      setVN({ status: "error", title: "Check failed", detail: errText(e) });
    }
  }

  const verdictText: Record<Verdict, string> = {
    upheld: "Coverage paid out — the deliverable failed conformance.",
    rejected: "Delivery conformed — the claim was dismissed, bond forfeited.",
    pending: "Judgement in progress — the bond is escrowed pending validator consensus.",
    unresolved: "No verdict yet — validators are still scoring the delivery.",
  };

  return (
    <div className="grid grid-gap-lg">
      <div className="group-label">
        <span>Agent actions</span>
      </div>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Submit a deliverable</h3>
            <p className="panel-desc">
              <em>Agent only.</em> Only the wallet registered as the covered agent can do
              this. It&apos;s the one thing a claim is judged against — a buyer can never
              write their own &quot;proof&quot; of non-performance.
            </p>
          </div>
        </div>
        <div className="field">
          <label htmlFor="dJob">Job ID</label>
          <input id="dJob" className="input" value={dJobId} onChange={(e) => setDJobId(e.target.value)} />
        </div>
        <EvidenceInput
          id="dUrl"
          label="Deliverable — link to the file on GitHub"
          what="the work you delivered"
          hint="The contract opens this link itself before accepting the submission, so a link that does not resolve is rejected on the spot — not later, and not at the buyer's expense."
          value={dEvidence}
          onChange={setDEvidence}
        />
        <div className="btn-row">
          <button className="btn btn-primary" disabled={dN.status === "pending"} onClick={doDeliver}>
            {dN.status === "pending" ? "Submitting…" : "Submit deliverable"}
          </button>
        </div>
        <Notice n={dN} />
        <p className="hint">
          The link must point at one exact version of the file (a 40-character commit id),
          not a branch. Once a claim is filed the link is frozen — it cannot be swapped
          while validators are judging.
        </p>
      </div>

      <div className="group-label">
        <span>Buyer actions</span>
      </div>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Request a verdict</h3>
            <p className="panel-desc">
              Needs a fixed {gen(VERDICT_BOND_ATTO)} GEN bond — refunded if you&apos;re right,
              forfeited to the pool if you&apos;re wrong. Validators judge it against the
              submitted deliverable.
            </p>
          </div>
        </div>
        <div className="field">
          <label htmlFor="cJob">Job ID</label>
          <input id="cJob" className="input" value={cJobId} onChange={(e) => setCJobId(e.target.value)} />
        </div>
        <div className="btn-row">
          <button className="btn btn-primary" disabled={cN.status === "pending"} onClick={doFileClaim}>
            {cN.status === "pending" ? "Waiting on consensus…" : `Request verdict (bond ${gen(VERDICT_BOND_ATTO)} GEN)`}
          </button>
        </div>
        <Notice n={cN} />
        {cN.status === "pending" && cSince && <ConsensusPending since={cSince} />}
        {verdict && (
          <ConformanceStamp v={verdict} jobId={cJobId.trim()} detail={verdictText[verdict]} />
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <div>
            <h3 className="panel-title">Check any verdict</h3>
            <p className="panel-desc">How did a past claim resolve? No wallet needed for reads.</p>
          </div>
        </div>
        <div className="field">
          <label htmlFor="vJob">Job ID</label>
          <input id="vJob" className="input" value={vJobId} onChange={(e) => setVJobId(e.target.value)} />
        </div>
        <div className="btn-row">
          <button className="btn btn-ghost" disabled={vN.status === "pending"} onClick={doCheckVerdict}>
            {vN.status === "pending" ? "Checking…" : "Check verdict"}
          </button>
        </div>
        <Notice n={vN} />
        {vResult && (
          <ConformanceStamp v={vResult} jobId={vJobId.trim()} detail={verdictText[vResult]} />
        )}
      </div>
    </div>
  );
}

/* ================================================================ PAGE === */

type PoolSnap = { balance: bigint; locked: bigint; shares: bigint } | null;
type TabKey = "agents" | "coverage" | "pools" | "claims";

const TABS: { key: TabKey; label: string }[] = [
  { key: "agents", label: "Agents" },
  { key: "coverage", label: "Coverage" },
  { key: "pools", label: "Pools" },
  { key: "claims", label: "Verdicts" },
];

export default function Home() {
  const { identity, ready, status } = useIdentity();
  const [tab, setTab] = useState<TabKey>("coverage");

  const [pools, setPools] = useState<Record<Tier, PoolSnap>>({
    unrated: null,
    bronze: null,
    silver: null,
    gold: null,
    penalty: null,
  });
  const [poolsBusy, setPoolsBusy] = useState(true);
  const [poolsError, setPoolsError] = useState<string | null>(null);
  // Epoch ms of the last successful pool load -- drives the "Updated …" stamp
  // next to Refresh (item 19 of the UX review).
  const [lastRefreshed, setLastRefreshed] = useState<number | null>(null);
  // Flips after loadPools has been running >10s, so a flaky network reads as
  // "slow", not as a hung "…" (StudioNet is documented flaky).
  const [poolsSlow, setPoolsSlow] = useState(false);

  const loadPools = useCallback(async () => {
    setPoolsBusy(true);
    setPoolsSlow(false);
    setPoolsError(null);
    const next: Record<Tier, PoolSnap> = { unrated: null, bronze: null, silver: null, gold: null, penalty: null };
    for (const t of TIERS) {
      try {
        const i = await getPoolInfo(t);
        next[t] = {
          balance: toBig(i.balance_atto),
          locked: toBig(i.locked_exposure_atto),
          shares: toBig(i.total_shares),
        };
      } catch (e: any) {
        setPoolsError(errText(e));
      }
    }
    setPools(next);
    setLastRefreshed(Date.now());
    setPoolsBusy(false);
  }, []);

  useEffect(() => {
    void loadPools();
  }, [loadPools]);

  // 10s stall guard for the hero stat card.
  useEffect(() => {
    if (!poolsBusy) {
      setPoolsSlow(false);
      return;
    }
    const id = setTimeout(() => setPoolsSlow(true), 10_000);
    return () => clearTimeout(id);
  }, [poolsBusy]);

  const ensureWallet = useCallback(async (): Promise<GenAccount> => {
    if (!ready) {
      throw new Error("Identity isn't ready yet — give it a second and try again.");
    }
    if (!identity) {
      // The keystore is encrypted at rest (review item 10), so a locked or
      // unconfigured browser has no signer until the user unlocks it. Say so
      // precisely instead of a generic "not ready".
      throw new Error(
        status === "locked"
          ? "Your identity is locked. Open the identity menu (top right) and enter your passphrase to sign."
          : "Set up an identity first — open the identity menu (top right) to create or import one.",
      );
    }
    return identity.account;
  }, [identity, ready, status]);

  const tvl = TIERS.reduce((acc, t) => {
    const p = pools[t];
    return acc + (p ? p.balance : 0n);
  }, 0n);

  const locked = TIERS.reduce((acc, t) => {
    const p = pools[t];
    return acc + (p ? p.locked : 0n);
  }, 0n);

  // Capital utilisation = GEN locked backing live cover / total pooled. This
  // is the honest live stand-in for the mock's "45% · 12 live policies" —
  // the contract exposes no policy count, but it does expose locked exposure.
  const ringArc = tvl > 0n ? Math.min(360, (Number(locked) / Number(tvl)) * 360) : 0;
  const ringBg = `conic-gradient(var(--proof) 0deg ${ringArc}deg, var(--line-strong) ${ringArc}deg 360deg)`;

  return (
    <div className="shell">
      {/* ----------------------------------------------------------- topbar */}
      <header className="topbar">
        <div className="brand">
          <ProofmarkLogo size={34} />
          <div className="brand-meta">
            <span className="brand-mark">Proofmark</span>
            <span className="brand-sub">Trust infrastructure for AI agents</span>
          </div>
        </div>
        <div className="top-actions">
          <span className="net-pill">
            <span className="dot" />
            {NET_LABEL}
          </span>
          <IdentityBadge />
        </div>
      </header>

      {!PROOFMARK_ADDRESS && (
        <div style={{ margin: "18px 0 0" }}>
          <Notice
            n={{
              status: "error",
              title: "Contract address not set",
              detail: "Add NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS (see .env.example) and redeploy on Vercel.",
            }}
          />
        </div>
      )}

      {/* ------------------------------------------------------------ hero */}
      <section className="hero">
        {/* LEFT — coverage pools: utilisation ring, capital underwriting active jobs, pool bars */}
        <div className="hero-left">
          <div className="hero-eyebrow-row">
            <span className="hero-eyebrow">Coverage pools</span>
            <span className="board-tools">
              <span className="proof-pill">
                <span className="proof-dot" />
                Rail active
              </span>
              {poolsBusy && poolsSlow && (
                <span className="ts-note">Network slow — hit Refresh when it settles</span>
              )}
              {poolsBusy && !poolsSlow && <span className="ts-note">Reading…</span>}
              {!poolsBusy && lastRefreshed !== null && (
                <span className="ts-note">Updated {new Date(lastRefreshed).toLocaleTimeString()}</span>
              )}
              <button className="btn btn-ghost btn-sm" onClick={loadPools} disabled={poolsBusy}>
                {poolsBusy ? "Refreshing…" : "Refresh"}
              </button>
            </span>
          </div>

          {poolsError && (
            <Notice
              n={{ status: "error", title: "Some pools are unreachable", detail: poolsError }}
              style={{ marginBottom: 4 }}
            />
          )}

          <div className="hero-gauge-row">
            <div className="gauge-dial">
              <div className="gauge-ring" style={{ background: ringBg }}>
                <ProofmarkLogo size={40} />
              </div>
            </div>
            <div className="hero-numbers">
              <div className="tvl-label">Capital underwriting active jobs</div>
              <div className="tvl-val">
                {tvl > 0n ? gen(tvl, 2) : poolsBusy ? "…" : "0"}
                <span>GEN</span>
              </div>
              <div className="tvl-sub">{gen(locked, 2)} GEN backing active jobs</div>
            </div>
          </div>

          <PoolBars pools={pools} tvl={tvl} />

          <p className="hero-addr">
            <b>Contract</b>{" "}
            {PROOFMARK_ADDRESS ? (
              <a
                href={explorerAddressUrl(PROOFMARK_ADDRESS)}
                target="_blank"
                rel="noreferrer noopener"
              >
                {PROOFMARK_ADDRESS}
              </a>
            ) : (
              "not configured"
            )}
            {PROOFMARK_ADDRESS && (
              <>
                {" · "}
                {NET_LABEL} · conformance rail for AI agent delivery
              </>
            )}
          </p>
        </div>

        {/* RIGHT — recent activity feed */}
        <div className="hero-right">
          <div className="feed-label">Recent activity</div>
          <Feed />
        </div>
      </section>

      {/* -------------------------------------------- pool tiles removed here
          (the redesign moved pool state into the hero-left PoolBars board;
           Pools tab below still owns the deposit/withdraw workflow) */}

      {/* how evidence works — one plain-language strip so a first-time visitor
          understands the deliverable model before touching any form. */}
      <section className="howto" aria-label="How evidence works">
        <div className="howto-head">
          <span className="hero-eyebrow">How proof works here</span>
          <p>
            A job is judged against <strong>files, not promises</strong>. Both the spec and
            the delivered work live on GitHub, and the contract locks in an exact
            fingerprint of each one — so nobody, on either side, can swap what was
            promised or what was handed over.
          </p>
        </div>
        <ol className="howto-steps">
          <li>
            <span className="howto-n">1</span>
            <div>
              <strong>Buyer locks the spec.</strong> Paste a GitHub link to the spec. The
              browser reads the file and shows its size and fingerprint before anything is
              committed; that exact fingerprint goes on-chain with the policy.
            </div>
          </li>
          <li>
            <span className="howto-n">2</span>
            <div>
              <strong>Agent delivers the same way.</strong> The agent pastes a GitHub link
              to the finished work. The contract opens the link itself and refuses the
              submission unless the bytes still match the fingerprint — a dead or doctored
              link is rejected on the spot, before any claim.
            </div>
          </li>
          <li>
            <span className="howto-n">3</span>
            <div>
              <strong>Validators judge the frozen files.</strong> After the deadline,
              independent validators re-fetch both files and score conformance. If the work
              doesn&apos;t match the spec, the agent&apos;s bond — not other people&apos;s
              capital — pays the buyer.
            </div>
          </li>
        </ol>
      </section>

      {/* ------------------------------------------------------------ tabs */}
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`tab ${tab === t.key ? "active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className={`tabpane ${tab === "agents" ? "active" : ""}`}>
        <AgentsPanel ensureWallet={ensureWallet} />
      </div>
      <div className={`tabpane ${tab === "pools" ? "active" : ""}`}>
        <PoolsPanel ensureWallet={ensureWallet} refreshPools={loadPools} identityReady={ready} />
      </div>
      <div className={`tabpane ${tab === "coverage" ? "active" : ""}`}>
        <CoveragePanel
          ensureWallet={ensureWallet}
          onGoPools={() => setTab("pools")}
          identityAddr={identity ? identity.address.toLowerCase() : null}
        />
      </div>
      <div className={`tabpane ${tab === "claims" ? "active" : ""}`}>
        <ClaimsPanel ensureWallet={ensureWallet} />
      </div>

      {/* --------------------------------------------------------- footnote */}
      <footer className="footnote">
        Premiums, bonds, and coverage are quoted in exact GEN — the contract rejects any
        amount that doesn&apos;t match precisely. Wallet transactions need GEN on this
        network; reads (tiles, lookups, verdicts) work without one.
      </footer>
    </div>
  );
}
