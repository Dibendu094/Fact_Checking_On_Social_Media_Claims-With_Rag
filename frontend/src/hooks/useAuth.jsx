import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { supabase, supabaseConfigured, authErrorMessage } from "../services/supabase";
import { resetPassword as resetPasswordApi } from "../services/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!supabaseConfigured) {
      setLoading(false);
      return;
    }

    let active = true;

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session ?? null);
      setLoading(false);
    });

    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      setSession(s ?? null);
    });

    return () => {
      active = false;
      sub?.subscription?.unsubscribe();
    };
  }, []);

  const value = useMemo(() => {
    const supaUser = session?.user ?? null;
    const user = supaUser
      ? {
          id: supaUser.id,
          email: supaUser.email,
          username:
            supaUser.user_metadata?.username ||
            (supaUser.email ? supaUser.email.split("@")[0] : "User"),
        }
      : null;

    return {
      user,
      session,
      loading,
      supabaseConfigured,

      signUp: async ({ username, email, password }) => {
        if (!supabaseConfigured) throw new Error("Auth is not configured.");
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: { data: { username: username.trim() } },
        });
        if (error) throw new Error(authErrorMessage(error));
        if (data.session) await supabase.auth.signOut();
        return { user: data.user };
      },

      signIn: async ({ email, password }) => {
        if (!supabaseConfigured) throw new Error("Auth is not configured.");
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (error) throw new Error(authErrorMessage(error));
      },

      resetPassword: async (email, newPassword) => {
        await resetPasswordApi(email, newPassword);
      },

      signOut: async () => {
        if (!supabaseConfigured) return;
        await supabase.auth.signOut();
      },
    };
  }, [session, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export default useAuth;
