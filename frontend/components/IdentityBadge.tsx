"use client";

import { useEffect, useRef, useState } from "react";
import { useIdentity } from "@/app/providers";
import { shortAddr } from "@/lib/format";
import { addressFromPk, isValidPk } from "@/lib/identity";

const MIN_PASSPHRASE = 8;

export function IdentityBadge() {
  const {
    identity,
    ready,
    status,
    address,
    legacyPk,
    sessionOnly,
    create,
    adopt,
    unlock,
    useSessionOnly,
    lock,
    forget,
  } = useIdentity();

  const [open, setOpen] = useState(false);

  // -- passphrase form (shared by create / unlock / change)
  const [pass, setPass] = useState("");
  const [pass2, setPass2] = useState("");
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [formMsg, setFormMsg] = useState<string | null>(null);

  // -- adopt-an-existing-key form
  const [adoptOpen, setAdoptOpen] = useState(false);
  const [adoptPk, setAdoptPk] = useState("");
  const [recovers, setRecovers] = useState<string | null>(null);
  const [adoptErr, setAdoptErr] = useState<string | null>(null);

  const [showKey, setShowKey] = useState(false);
  const [copiedAddr, setCopiedAddr] = useState(false);
  const [copiedKey, setCopiedKey] = useState(false);

  const [mmAddress, setMmAddress] = useState<string | null>(null);
  const [mmError, setMmError] = useState<string | null>(null);

  // -- "change passphrase" inline form
  const [rekeyOpen, setRekeyOpen] = useState(false);

  // -- destructive confirmation (type DELETE)
  const [delConfirm, setDelConfirm] = useState(false);
  const [delTyped, setDelTyped] = useState("");

  const menuRef = useRef<HTMLDivElement>(null);

  // Reset all ephemeral state every time the menu closes.
  useEffect(() => {
    if (!open) {
      setShowKey(false);
      setCopiedAddr(false);
      setCopiedKey(false);
      setMmError(null);
      setAdoptOpen(false);
      setAdoptPk("");
      setRecovers(null);
      setAdoptErr(null);
      setDelConfirm(false);
      setDelTyped("");
      setRekeyOpen(false);
      setPass("");
      setPass2("");
      setFormErr(null);
      setFormMsg(null);
    }
  }, [open]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  function copyText(text: string, setter: (v: boolean) => void) {
    if (!navigator.clipboard?.writeText) return;
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setter(true);
        setTimeout(() => setter(false), 1800);
      })
      .catch(() => {
        /* clipboard denied — nothing else sensible to do */
      });
  }

  function onAdoptChange(v: string) {
    setAdoptPk(v);
    setAdoptErr(null);
    setFormMsg(null);
    const trimmed = v.trim();
    if (!trimmed) {
      setRecovers(null);
      return;
    }
    setRecovers(isValidPk(trimmed) ? addressFromPk(trimmed) : null);
  }

  /** Run a keystore action with shared busy/error handling. */
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setFormErr(null);
    setFormMsg(null);
    try {
      await fn();
      setPass("");
      setPass2("");
    } catch (e: any) {
      setFormErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  function doCreate() {
    if (pass.length < MIN_PASSPHRASE) {
      setFormErr(`Passphrase must be at least ${MIN_PASSPHRASE} characters.`);
      return;
    }
    if (pass !== pass2) {
      setFormErr("The two passphrases don't match.");
      return;
    }
    void run(() => create(pass));
  }

  function doUnlock() {
    if (!pass) {
      setFormErr("Enter your passphrase.");
      return;
    }
    void run(() => unlock(pass));
  }

  function doAdopt() {
    const pk = adoptPk.trim();
    if (!isValidPk(pk)) {
      setAdoptErr("Not a valid private key — needs 0x followed by 64 hex characters.");
      return;
    }
    if (pass.length < MIN_PASSPHRASE) {
      setFormErr(`Passphrase must be at least ${MIN_PASSPHRASE} characters.`);
      return;
    }
    if (pass !== pass2) {
      setFormErr("The two passphrases don't match.");
      return;
    }
    void run(() => adopt(pk, pass));
  }

  function doRekey() {
    if (!identity) return;
    if (pass.length < MIN_PASSPHRASE) {
      setFormErr(`Passphrase must be at least ${MIN_PASSPHRASE} characters.`);
      return;
    }
    if (pass !== pass2) {
      setFormErr("The two passphrases don't match.");
      return;
    }
    void run(async () => {
      await adopt(identity.privateKey, pass);
      setRekeyOpen(false);
      setFormMsg("Passphrase updated — the keystore was re-encrypted.");
    });
  }

  async function connectMetaMask() {
    setMmError(null);
    const eth = (window as {
      ethereum?: { request: (a: { method: string }) => Promise<string[]> };
    }).ethereum;
    if (!eth) {
      setMmError("MetaMask isn't installed. Add the extension and try again.");
      return;
    }
    try {
      const accounts = await eth.request({ method: "eth_requestAccounts" });
      setMmAddress(accounts[0] ?? null);
    } catch (err: unknown) {
      if ((err as { code?: number }).code === 4001) {
        setMmError("Connection cancelled.");
      } else {
        setMmError("MetaMask connection failed.");
      }
    }
  }

  // ---------------------------------------------------------------- chip ---
  if (!ready) {
    return (
      <span className="idchip">
        <span className="seal" />
        <span className="mono muted">identity…</span>
      </span>
    );
  }

  const chipLabel =
    status === "unlocked" && identity
      ? shortAddr(identity.address)
      : status === "locked"
        ? "Locked"
        : "Set up identity";

  return (
    <div ref={menuRef} style={{ position: "relative" }}>
      <button
        className={`idchip ${open ? "open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        title="Open identity menu"
      >
        <span className={`seal ${status === "unlocked" ? "" : "seal-idle"}`} />
        <span className="idchip-addr mono">{chipLabel}</span>
        <span className="idcaret">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="idmenu">
          {/* ============================================= LOCKED =========== */}
          {status === "locked" && (
            <>
              <div className="idsec">
                <div className="idlabel">Encrypted keystore — locked</div>
                <div className="idnote">
                  Your signing key is stored encrypted in this browser. Enter your
                  passphrase to unlock it for this tab. The key never leaves this
                  device and is never written to disk in the clear.
                </div>
                {address && (
                  <div className="idwell-row">
                    <span className="idwell mono">{shortAddr(address)}</span>
                  </div>
                )}
                <div className="idstack">
                  <input
                    className="input mono"
                    type="password"
                    autoComplete="current-password"
                    placeholder="Passphrase"
                    value={pass}
                    onChange={(e) => {
                      setPass(e.target.value);
                      setFormErr(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") doUnlock();
                    }}
                  />
                  {formErr && <div className="iderr mono">{formErr}</div>}
                  <button
                    className="btn btn-primary btn-sm idwide"
                    disabled={busy}
                    onClick={doUnlock}
                  >
                    {busy ? "Unlocking…" : "Unlock"}
                  </button>
                </div>
              </div>
              <hr className="idsep" />
              <div className="idsec danger">
                <div className="idlabel">Lost the passphrase?</div>
                <div className="idhint">
                  There is no recovery — the keystore is encrypted with it. The
                  address stays on-chain, but this browser can no longer sign for
                  it. You can still start a new identity below.
                </div>
                <button
                  className="btn btn-danger btn-sm idwide"
                  onClick={() => {
                    forget();
                  }}
                >
                  Forget keystore and start over
                </button>
              </div>
            </>
          )}

          {/* ========================================= NEEDS SETUP ========== */}
          {status === "needs-setup" && (
            <>
              <div className="idsec">
                <div className="idlabel">
                  {legacyPk ? "Secure your existing identity" : "Create your identity"}
                </div>
                <div className="idnote">
                  {legacyPk
                    ? "An earlier build left your private key in this browser unprotected. Set a passphrase to encrypt it — the key is deleted from plaintext storage the moment you do."
                    : "Proofmark signs GenLayer transactions with a key held in this browser (MetaMask can't sign for GenLayer). It's encrypted at rest under a passphrase you choose."}
                </div>
                {legacyPk && addressFromPk(legacyPk) && (
                  <div className="idok mono">
                    Recovers: <b>{addressFromPk(legacyPk)}</b>
                  </div>
                )}
                <div className="idstack">
                  <input
                    className="input mono"
                    type="password"
                    autoComplete="new-password"
                    placeholder={`Passphrase (min ${MIN_PASSPHRASE} chars)`}
                    value={pass}
                    onChange={(e) => {
                      setPass(e.target.value);
                      setFormErr(null);
                    }}
                  />
                  <input
                    className="input mono"
                    type="password"
                    autoComplete="new-password"
                    placeholder="Confirm passphrase"
                    value={pass2}
                    onChange={(e) => {
                      setPass2(e.target.value);
                      setFormErr(null);
                    }}
                  />
                  {formErr && <div className="iderr mono">{formErr}</div>}
                  <button
                    className="btn btn-primary btn-sm idwide"
                    disabled={busy}
                    onClick={legacyPk ? doAdopt : doCreate}
                  >
                    {busy
                      ? "Encrypting…"
                      : legacyPk
                        ? "Encrypt and adopt this key"
                        : "Create encrypted identity"}
                  </button>
                </div>
              </div>

              <hr className="idsep" />

              {/* adopt a key the user already has */}
              <div className="idsec">
                <div className="idlabel">Use an existing key</div>
                {!adoptOpen ? (
                  <button
                    className="btn btn-ghost btn-sm idwide"
                    onClick={() => setAdoptOpen(true)}
                  >
                    Import from private key
                  </button>
                ) : (
                  <div className="idstack">
                    <input
                      className="input mono"
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder="0x… your private key"
                      value={adoptPk}
                      onChange={(e) => onAdoptChange(e.target.value)}
                    />
                    {adoptErr && <div className="iderr mono">{adoptErr}</div>}
                    {!adoptErr && recovers && (
                      <div className="idok mono">
                        Recovers: <b>{recovers}</b>
                      </div>
                    )}
                    <div className="idhint">
                      Use the passphrase fields above, then adopt. Importing swaps
                      the whole signer — this browser will act as that address from
                      now on.
                    </div>
                    <button
                      className="btn btn-primary btn-sm idwide"
                      disabled={busy || !isValidPk(adoptPk.trim())}
                      onClick={doAdopt}
                    >
                      {busy ? "Encrypting…" : "Encrypt and adopt"}
                    </button>
                  </div>
                )}
              </div>

              <hr className="idsep" />

              <div className="idsec danger">
                <div className="idlabel">No passphrase?</div>
                <div className="idhint">
                  You can use a session-only identity instead. It is never written
                  to disk, but it lives in this tab only — close the tab and the
                  address is gone from this browser.
                </div>
                <button
                  className="btn btn-danger btn-sm idwide"
                  onClick={() => {
                    useSessionOnly();
                    setOpen(false);
                  }}
                >
                  Use a session-only identity (not recommended)
                </button>
              </div>
            </>
          )}

          {/* ============================================ UNLOCKED ========== */}
          {status === "unlocked" && identity && (
            <>
              <div className="idsec">
                <div className="idlabel">
                  {mmAddress ? "MetaMask (display only)" : "Browser identity"}
                </div>
                <div className="idwell-row">
                  <span className="idwell mono">{mmAddress ?? identity.address}</span>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => copyText(mmAddress ?? identity.address, setCopiedAddr)}
                  >
                    {copiedAddr ? "Copied" : "Copy"}
                  </button>
                </div>
                {mmAddress && (
                  <div className="idhint mono">
                    Signer (actual): {shortAddr(identity.address)}
                  </div>
                )}
              </div>

              <hr className="idsep" />

              <div className="idnote">
                {sessionOnly
                  ? "This is a SESSION-ONLY identity: the key is held in this tab and never written to disk. Close the tab and it's gone from this browser."
                  : "Your key is stored encrypted (AES-GCM under a PBKDF2-derived passphrase) and only decrypted in memory while this tab is unlocked. It never leaves this device."}
              </div>

              <hr className="idsep" />

              <div className="idsec">
                <div className="idlabel">Private key</div>
                {!showKey ? (
                  <button
                    className="btn btn-ghost btn-sm idwide"
                    onClick={() => setShowKey(true)}
                  >
                    Show private key
                  </button>
                ) : (
                  <div className="idstack">
                    <div className="idwell mono idkey" style={{ userSelect: "all" }}>
                      {identity.privateKey}
                    </div>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => copyText(identity.privateKey, setCopiedKey)}
                    >
                      {copiedKey ? "Copied" : "Copy private key"}
                    </button>
                    <div className="idhint">
                      Anyone who sees this controls the address. If it holds funds,
                      save it somewhere safe — clearing site data loses the
                      encrypted copy.
                    </div>
                  </div>
                )}
              </div>

              {/* ---- security: rekey / lock / forget ---- */}
              <hr className="idsep" />

              <div className="idsec">
                <div className="idlabel">Security</div>
                {!sessionOnly && (
                  <>
                    {!rekeyOpen ? (
                      <button
                        className="btn btn-ghost btn-sm idwide"
                        onClick={() => setRekeyOpen(true)}
                      >
                        Change passphrase
                      </button>
                    ) : (
                      <div className="idstack">
                        <input
                          className="input mono"
                          type="password"
                          autoComplete="new-password"
                          placeholder={`New passphrase (min ${MIN_PASSPHRASE} chars)`}
                          value={pass}
                          onChange={(e) => {
                            setPass(e.target.value);
                            setFormErr(null);
                          }}
                        />
                        <input
                          className="input mono"
                          type="password"
                          autoComplete="new-password"
                          placeholder="Confirm new passphrase"
                          value={pass2}
                          onChange={(e) => {
                            setPass2(e.target.value);
                            setFormErr(null);
                          }}
                        />
                        <button
                          className="btn btn-primary btn-sm idwide"
                          disabled={busy}
                          onClick={doRekey}
                        >
                          {busy ? "Re-encrypting…" : "Re-encrypt keystore"}
                        </button>
                      </div>
                    )}
                  </>
                )}
                {formErr && <div className="iderr mono">{formErr}</div>}
                {formMsg && <div className="idok mono">{formMsg}</div>}
                <div className="btn-row">
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      lock();
                      setOpen(false);
                    }}
                  >
                    Lock now
                  </button>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => setMmAddress(null)}
                    style={{ display: mmAddress ? undefined : "none" }}
                  >
                    Hide MetaMask
                  </button>
                </div>
                <div className="idhint">
                  Locking drops the decrypted key from memory. The encrypted
                  keystore stays in this browser.
                </div>
              </div>

              <hr className="idsep" />

              <div className="idsec mm">
                <div className="idlabel">MetaMask</div>
                {!mmAddress ? (
                  <div className="idstack">
                    <button className="btn btn-ghost btn-sm idwide" onClick={connectMetaMask}>
                      Connect MetaMask (display only)
                    </button>
                    {mmError && <div className="iderr mono">{mmError}</div>}
                  </div>
                ) : (
                  <div className="idhint">
                    Showing {shortAddr(mmAddress)} for reference only.
                  </div>
                )}
                <div className="idhint">
                  MetaMask can&apos;t sign GenLayer transactions. This is here just to
                  show you why.
                </div>
              </div>

              <hr className="idsep" />

              <div className="idsec danger">
                <div className="idlabel">Danger zone</div>
                {!delConfirm ? (
                  <button
                    className="btn btn-danger btn-sm idwide"
                    onClick={() => setDelConfirm(true)}
                  >
                    Generate new identity
                  </button>
                ) : (
                  <div className="idstack">
                    <div className="idhint">
                      Generating a new identity swaps the browser signer. Your current
                      address stays on-chain, but this browser will act as a different
                      address from now on — any agent registration or funded LP
                      position tied to the current one becomes unreachable from here.
                    </div>
                    <input
                      className="input mono"
                      placeholder="Type DELETE to confirm"
                      autoComplete="off"
                      spellCheck={false}
                      value={delTyped}
                      onChange={(e) => setDelTyped(e.target.value)}
                    />
                    <div className="btn-row">
                      <button
                        className="btn btn-danger btn-sm"
                        disabled={delTyped.trim().toUpperCase() !== "DELETE"}
                        onClick={() => {
                          forget();
                          setOpen(false);
                        }}
                      >
                        Generate new identity
                      </button>
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                          setDelConfirm(false);
                          setDelTyped("");
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
