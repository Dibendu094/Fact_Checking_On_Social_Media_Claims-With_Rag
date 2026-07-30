import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { supabase, authErrorMessage } from "../services/supabase";
import { resetPassword as resetPasswordApi } from "../services/api";

const AuthContext = createContext(null);

/**
 * Session state backed by Supabase Auth.
 *
 * We do not store tokens ourselves: supabase-js persists the session and
 * refreshes it, and onAuthStateChange keeps React in sync (including across
 * tabs and after the email-confirmation redirect).
 */
export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
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
          // username comes from user_metadata, set at signup; fall back to the
          // local-part of the email so the avatar/initial always renders.
          username:
            supaUser.user_metadata?.username ||
            (supaUser.email ? supaUser.email.split("@")[0] : "User"),
        }
      : null;

    return {
      user,
      session,
      loading,

      signUp: async ({ username, email, password }) => {
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: { data: { username: username.trim() } },
        });
        if (error) throw new Error(authErrorMessage(error));
        // Accounts are usable immediately (a DB trigger auto-confirms the
        // email on insert — see project notes). Whether this call itself
        // also returns a live session is inconsistent, so it's forced off:
        // the caller always sends the user to the sign-in form to log in
        // manually, matching a normal login flow rather than a surprise
        // auto-login.
        if (data.session) {
          await supabase.auth.signOut();
        }
        return { user: data.user };
      },

      signIn: async ({ email, password }) => {
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
