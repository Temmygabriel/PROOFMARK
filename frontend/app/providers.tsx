"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  adoptIdentity,
  createEncryptedIdentity,
  createSessionIdentity,
  forgetIdentity,
  loadIdentityState,
  lockIdentity,
  unlockIdentity,
  type Identity,
  type IdentityState,
  type IdentityStatus,
} from "@/lib/identity";

interface IdentityCtx {
  identity: Identity | null;
  /** False until the browser-only keystore read has run. */
  ready: boolean;
  status: IdentityStatus;
  /** Public address, known even while the keystore is locked. */
  address: string | null;
  /** A legacy plaintext key on disk awaiting encrypt-or-discard. */
  legacyPk: `0x${string}` | null;
  /** True when the live identity is session-only (never written to disk). */
  sessionOnly: boolean;
  /** Create a fresh identity, encrypted at rest under a passphrase. */
  create: (passphrase: string) => Promise<void>;
  /** Encrypt an existing key (typed, or the legacy on-disk one) and adopt it. */
  adopt: (pk: string, passphrase: string) => Promise<void>;
  /** Unlock the on-disk keystore for this tab. Throws on a wrong passphrase. */
  unlock: (passphrase: string) => Promise<void>;
  /** Generate a session-only identity (weaker; lost with the tab). */
  useSessionOnly: () => void;
  /** Drop the in-memory key. The keystore stays on disk. */
  lock: () => void;
  /** Delete the keystore and any legacy plaintext key from this browser. */
  forget: () => void;
}

const EMPTY: IdentityState = {
  status: "needs-setup",
  identity: null,
  address: null,
  legacyPk: null,
  sessionOnly: false,
};

const Ctx = createContext<IdentityCtx>({
  ...EMPTY,
  ready: false,
  create: async () => {},
  adopt: async () => {},
  unlock: async () => {},
  useSessionOnly: () => {},
  lock: () => {},
  forget: () => {},
});

export function Providers({ children }: { children: ReactNode }) {
  const [state, setState] = useState<IdentityState>(EMPTY);
  const [ready, setReady] = useState(false);

  // localStorage + key derivation happen only in the browser, never during SSR.
  useEffect(() => {
    try {
      setState(loadIdentityState());
    } catch {
      setState(EMPTY);
    } finally {
      setReady(true);
    }
  }, []);

  const create = useCallback(async (passphrase: string) => {
    // Derive + persist first; only publish state once the keystore is written,
    // so a failed derivation can never leave a half-set identity behind.
    const identity = await createEncryptedIdentity(passphrase);
    setState({
      status: "unlocked",
      identity,
      address: identity.address,
      legacyPk: null,
      sessionOnly: false,
    });
  }, []);

  const adopt = useCallback(async (pk: string, passphrase: string) => {
    const identity = await adoptIdentity(pk, passphrase);
    setState({
      status: "unlocked",
      identity,
      address: identity.address,
      legacyPk: null,
      sessionOnly: false,
    });
  }, []);

  const unlock = useCallback(async (passphrase: string) => {
    const identity = await unlockIdentity(passphrase);
    setState({
      status: "unlocked",
      identity,
      address: identity.address,
      legacyPk: null,
      sessionOnly: false,
    });
  }, []);

  const useSessionOnly = useCallback(() => {
    const identity = createSessionIdentity();
    setState({
      status: "unlocked",
      identity,
      address: identity.address,
      legacyPk: null,
      sessionOnly: true,
    });
  }, []);

  const lock = useCallback(() => {
    setState((prev) => lockIdentity(prev.address));
  }, []);

  const forget = useCallback(() => {
    forgetIdentity();
    setState(EMPTY);
  }, []);

  return (
    <Ctx.Provider
      value={{
        ...state,
        ready,
        create,
        adopt,
        unlock,
        useSessionOnly,
        lock,
        forget,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useIdentity() {
  return useContext(Ctx);
}
