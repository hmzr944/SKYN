import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, clearToken, getToken, setToken } from "@/src/services/api";

type User = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
};

type Profile = {
  user_id: string;
  age?: number | null;
  feeling?: string | null;
  goal?: string | null;
  onboarded?: boolean;
};

type AuthState = {
  loading: boolean;
  user: User | null;
  profile: Profile | null;
  refreshProfile: () => Promise<void>;
  signInWithSessionToken: (token: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthCtx = createContext<AuthState | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);

  const loadSession = useCallback(async () => {
    try {
      const token = await getToken();
      if (!token) {
        setUser(null);
        setProfile(null);
        return;
      }
      const me = await api.me();
      setUser(me);
      try {
        const p = await api.getProfile();
        setProfile(p);
      } catch {
        setProfile(null);
      }
    } catch {
      await clearToken();
      setUser(null);
      setProfile(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSession();
  }, [loadSession]);

  const signInWithSessionToken = useCallback(async (token: string) => {
    await setToken(token);
    setLoading(true);
    await loadSession();
  }, [loadSession]);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    await clearToken();
    setUser(null);
    setProfile(null);
  }, []);

  const refreshProfile = useCallback(async () => {
    try {
      const p = await api.getProfile();
      setProfile(p);
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <AuthCtx.Provider
      value={{ loading, user, profile, refreshProfile, signInWithSessionToken, signOut }}
    >
      {children}
    </AuthCtx.Provider>
  );
};

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
