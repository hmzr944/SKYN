import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { api } from "@/src/services/api";
import { supabase } from "@/src/services/supabase";

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
  skin_type?: string | null;
  goals?: string[] | null;
  onboarded?: boolean;
};

type AuthState = {
  loading: boolean;
  user: User | null;
  profile: Profile | null;
  refreshProfile: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthCtx = createContext<AuthState | null>(null);

function userFromSession(session: Session | null): User | null {
  if (!session?.user) return null;
  const { id, email, user_metadata } = session.user;
  return {
    user_id: id,
    email: email ?? "",
    name: user_metadata?.full_name || user_metadata?.name || (email ? email.split("@")[0] : "User"),
    picture: user_metadata?.avatar_url || user_metadata?.picture || null,
  };
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);

  const loadProfile = useCallback(async () => {
    try {
      const p = await api.getProfile();
      setProfile(p);
    } catch {
      setProfile(null);
    }
  }, []);

  useEffect(() => {
    let mounted = true;

    supabase.auth.getSession().then(async ({ data }) => {
      if (!mounted) return;
      const sessionUser = userFromSession(data.session);
      setUser(sessionUser);
      if (sessionUser) await loadProfile();
      setLoading(false);
    });

    const { data: subscription } = supabase.auth.onAuthStateChange(async (_event, session) => {
      const sessionUser = userFromSession(session);
      setUser(sessionUser);
      if (sessionUser) {
        await loadProfile();
      } else {
        setProfile(null);
      }
    });

    return () => {
      mounted = false;
      subscription.subscription.unsubscribe();
    };
  }, [loadProfile]);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setUser(null);
    setProfile(null);
  }, []);

  const refreshProfile = useCallback(async () => {
    await loadProfile();
  }, [loadProfile]);

  return (
    <AuthCtx.Provider value={{ loading, user, profile, refreshProfile, signOut }}>
      {children}
    </AuthCtx.Provider>
  );
};

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
