"use client";

import { createAccount, generatePrivateKey } from "genlayer-js";

// Proofmark uses a browser-stored identity, not a real wallet. GenLayer
// studionet transactions are signed by a genlayer-js account (an in-browser
// keypair) — MetaMask cannot sign them directly. This is honest and clearly
// labeled in the UI as a browser identity.
//
// ---------------------------------------------------------------------------
// CUSTODY (review item 10)
// ---------------------------------------------------------------------------
// Earlier builds kept the raw private key in localStorage under
// `proofmark.identity.pk.v1` (and, before the rename, `aegis.identity.pk.v1` /
// `specmark.identity.pk.v1`). Any script on the origin — including a compromised
// dependency — could read the key straight out of storage and drain the
// address. This module replaces that with an encrypted keystore:
//
//   localStorage["proofmark.identity.keystore.v1"] = {
//     v, kdf: "PBKDF2-SHA256", iterations, salt, iv, ct, address
//   }
//
// `ct` is the AES-GCM-256 ciphertext of the private key under a key derived
// from the user's passphrase (PBKDF2-SHA256, 310k iterations, random 16-byte
// salt, random 12-byte IV). The private key exists in cleartext only in memory,
// only after an unlock, and only for the lifetime of the tab.
//
// A plaintext key is NEVER written to disk by this module. The only two ways to
// have a usable identity are:
//   1. encrypted keystore + passphrase unlock (persists across reloads), or
//   2. a session-only identity held in sessionStorage (survives a reload of the
//      same tab, dies with the tab, and is explicitly labeled as not
//      recommended because it is still readable by same-origin script).
//
// A legacy plaintext key found on disk is offered for adoption (encrypt it) or
// discard — it is never silently re-persisted in the clear, and it is deleted
// from localStorage the moment the user chooses.
//
// THE VIEM PRIVATE-KEY TRAP (learned from the Rigor frontend, earned the hard
// way): createAccount() returns a viem account created via privateKeyToAccount().
// That object does NOT expose `.privateKey`. WE generate the key with
// generatePrivateKey(), keep OUR copy, and restore the account by passing that
// key back into createAccount(key).

/** Encrypted keystore record. `address` is public and safe to store in clear. */
export interface KeystoreBlob {
  v: 1;
  kdf: "PBKDF2-SHA256";
  iterations: number;
  salt: string;
  iv: string;
  ct: string;
  address: string;
}

const KS_KEY = "proofmark.identity.keystore.v1";
const SESSION_KEY = "proofmark.identity.session.v1";
// Plaintext keys written by earlier builds. Read once for migration, then
// deleted. (The literal key strings cannot be reworded: they are the exact keys
// earlier builds wrote to localStorage.)
const PK_KEY = "proofmark.identity.pk.v1";
const PK_KEY_LEGACY_V1 = "aegis.identity.pk.v1";
const PK_KEY_LEGACY_SPECMARK = "specmark.identity.pk.v1";

const KDF_ITERATIONS = 310_000;
const SALT_BYTES = 16;
const IV_BYTES = 12;

export type GenAccount = ReturnType<typeof createAccount>;

export interface Identity {
  privateKey: `0x${string}`;
  address: `0x${string}`;
  account: GenAccount;
}

export function isValidPk(pk: string | null | undefined): pk is `0x${string}` {
  return !!pk && /^0x[0-9a-fA-F]{64}$/.test(pk);
}

/** Build an identity from a key WITHOUT persisting it (live previews, unlock result). */
export function identityFromPk(pk: string): Identity {
  const account = createAccount(pk as `0x${string}`);
  return { privateKey: pk as `0x${string}`, address: account.address as `0x${string}`, account };
}

/** Preview the address a key would recover, or null if the key is malformed. */
export function addressFromPk(pk: string): string | null {
  try {
    return isValidPk(pk) ? identityFromPk(pk).address : null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// WebCrypto helpers
// ---------------------------------------------------------------------------

function subtle(): SubtleCrypto {
  const c = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (!c || !c.subtle) {
    throw new Error(
      "This browser can't encrypt your key at rest (WebCrypto unavailable). Open Proofmark over https:// (or localhost) and try again.",
    );
  }
  return c.subtle;
}

function randomBytes(n: number): Uint8Array {
  const out = new Uint8Array(n);
  globalThis.crypto.getRandomValues(out);
  return out;
}

function toB64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

function fromB64(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function deriveAesKey(
  passphrase: string,
  salt: Uint8Array,
  iterations: number,
): Promise<CryptoKey> {
  const base = await subtle().importKey(
    "raw",
    new TextEncoder().encode(passphrase) as unknown as BufferSource,
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return subtle().deriveKey(
    {
      name: "PBKDF2",
      salt: salt as unknown as BufferSource,
      iterations,
      hash: "SHA-256",
    },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

/** Encrypt a private key under a passphrase. Pure — the caller persists it. */
export async function encryptPrivateKey(
  pk: `0x${string}`,
  passphrase: string,
): Promise<KeystoreBlob> {
  if (passphrase.length < 8) {
    throw new Error("Passphrase must be at least 8 characters.");
  }
  const salt = randomBytes(SALT_BYTES);
  const iv = randomBytes(IV_BYTES);
  const key = await deriveAesKey(passphrase, salt, KDF_ITERATIONS);
  const ct = await subtle().encrypt(
    { name: "AES-GCM", iv: iv as unknown as BufferSource },
    key,
    new TextEncoder().encode(pk) as unknown as BufferSource,
  );
  return {
    v: 1,
    kdf: "PBKDF2-SHA256",
    iterations: KDF_ITERATIONS,
    salt: toB64(salt),
    iv: toB64(iv),
    ct: toB64(new Uint8Array(ct)),
    address: identityFromPk(pk).address,
  };
}

/** Decrypt a keystore blob. Throws a human-readable error on a wrong passphrase. */
export async function decryptPrivateKey(
  blob: KeystoreBlob,
  passphrase: string,
): Promise<`0x${string}`> {
  const key = await deriveAesKey(
    passphrase,
    fromB64(blob.salt),
    blob.iterations || KDF_ITERATIONS,
  );
  let plain: ArrayBuffer;
  try {
    plain = await subtle().decrypt(
      { name: "AES-GCM", iv: fromB64(blob.iv) as unknown as BufferSource },
      key,
      fromB64(blob.ct) as unknown as BufferSource,
    );
  } catch {
    // AES-GCM authentication failed — wrong passphrase or a tampered keystore.
    throw new Error("Wrong passphrase — that keystore could not be decrypted.");
  }
  const pk = new TextDecoder().decode(plain);
  if (!isValidPk(pk)) throw new Error("Keystore is corrupt — it did not decrypt to a key.");
  return pk;
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

export function readKeystore(): KeystoreBlob | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KS_KEY);
    if (!raw) return null;
    const blob = JSON.parse(raw) as KeystoreBlob;
    if (blob?.v !== 1 || typeof blob.ct !== "string" || typeof blob.salt !== "string") {
      return null;
    }
    return blob;
  } catch {
    return null;
  }
}

function writeKeystore(blob: KeystoreBlob): void {
  window.localStorage.setItem(KS_KEY, JSON.stringify(blob));
}

/** The plaintext key an earlier build left behind, if any (never rewritten). */
export function readLegacyPlaintextKey(): `0x${string}` | null {
  if (typeof window === "undefined") return null;
  const found =
    window.localStorage.getItem(PK_KEY) ||
    window.localStorage.getItem(PK_KEY_LEGACY_V1) ||
    window.localStorage.getItem(PK_KEY_LEGACY_SPECMARK);
  return isValidPk(found) ? found : null;
}

/** Remove every plaintext key an earlier build wrote. */
export function purgeLegacyPlaintextKeys(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(PK_KEY);
  window.localStorage.removeItem(PK_KEY_LEGACY_V1);
  window.localStorage.removeItem(PK_KEY_LEGACY_SPECMARK);
}

function readSessionKey(): `0x${string}` | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.sessionStorage.getItem(SESSION_KEY);
    return isValidPk(v) ? v : null;
  } catch {
    return null;
  }
}

function writeSessionKey(pk: `0x${string}`): void {
  try {
    window.sessionStorage.setItem(SESSION_KEY, pk);
  } catch {
    /* private mode / storage disabled — the identity still works in memory */
  }
}

function clearSessionKey(): void {
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* nothing to clear */
  }
}

// ---------------------------------------------------------------------------
// State machine consumed by the React provider
// ---------------------------------------------------------------------------

/**
 * `needs-setup` — nothing usable on disk: the user must create or adopt an
 *                 identity (and choose a passphrase).
 * `locked`      — an encrypted keystore exists; unlock needs the passphrase.
 * `unlocked`    — an identity is live in memory for this tab.
 */
export type IdentityStatus = "needs-setup" | "locked" | "unlocked";

export interface IdentityState {
  status: IdentityStatus;
  identity: Identity | null;
  /** Known even while locked — the address is public, the key is not. */
  address: string | null;
  /** A legacy plaintext key found on disk, awaiting encrypt-or-discard. */
  legacyPk: `0x${string}` | null;
  /** True when the live identity is session-only (not persisted at rest). */
  sessionOnly: boolean;
}

export function loadIdentityState(): IdentityState {
  if (typeof window === "undefined") {
    return { status: "needs-setup", identity: null, address: null, legacyPk: null, sessionOnly: false };
  }

  const blob = readKeystore();
  if (blob) {
    return {
      status: "locked",
      identity: null,
      address: blob.address || null,
      legacyPk: null,
      sessionOnly: false,
    };
  }

  const session = readSessionKey();
  if (session) {
    return {
      status: "unlocked",
      identity: identityFromPk(session),
      address: identityFromPk(session).address,
      legacyPk: null,
      sessionOnly: true,
    };
  }

  const legacy = readLegacyPlaintextKey();
  return {
    status: "needs-setup",
    identity: null,
    address: legacy ? addressFromPk(legacy) : null,
    legacyPk: legacy,
    sessionOnly: false,
  };
}

/** Create a brand-new identity, encrypted at rest under `passphrase`. */
export async function createEncryptedIdentity(passphrase: string): Promise<Identity> {
  const pk = generatePrivateKey();
  const blob = await encryptPrivateKey(pk, passphrase);
  writeKeystore(blob);
  purgeLegacyPlaintextKeys();
  clearSessionKey();
  return identityFromPk(pk);
}

/**
 * Adopt an existing private key (a legacy on-disk key, or one the user typed)
 * and persist it ENCRYPTED. This is the only path that turns a typed key into
 * durable storage, and it never writes the key in the clear.
 */
export async function adoptIdentity(pk: string, passphrase: string): Promise<Identity> {
  if (!isValidPk(pk)) {
    throw new Error("That doesn't look like a private key (needs 0x + 64 hex chars).");
  }
  const blob = await encryptPrivateKey(pk, passphrase);
  writeKeystore(blob);
  purgeLegacyPlaintextKeys();
  clearSessionKey();
  return identityFromPk(pk);
}

/** Unlock the on-disk keystore for this tab. */
export async function unlockIdentity(passphrase: string): Promise<Identity> {
  const blob = readKeystore();
  if (!blob) throw new Error("No keystore found in this browser.");
  const pk = await decryptPrivateKey(blob, passphrase);
  return identityFromPk(pk);
}

/**
 * Generate an identity held ONLY in sessionStorage for this tab. Not written to
 * localStorage, so it never sits on disk — but it is still readable by
 * same-origin script, so the UI labels it as the weaker option.
 */
export function createSessionIdentity(): Identity {
  const pk = generatePrivateKey();
  writeSessionKey(pk);
  purgeLegacyPlaintextKeys();
  return identityFromPk(pk);
}

/** Forget this browser's identity entirely (keystore + any legacy plaintext). */
export function forgetIdentity(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KS_KEY);
  purgeLegacyPlaintextKeys();
  clearSessionKey();
}

/** Drop the in-memory key for this tab. The keystore on disk is untouched. */
export function lockIdentity(knownAddress: string | null): IdentityState {
  clearSessionKey();
  return {
    status: readKeystore() ? "locked" : "needs-setup",
    identity: null,
    address: knownAddress,
    legacyPk: null,
    sessionOnly: false,
  };
}
