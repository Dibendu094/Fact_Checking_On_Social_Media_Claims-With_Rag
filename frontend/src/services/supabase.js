import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // Fail loudly at boot rather than with a confusing null-ref later.
  console.error(
    "Supabase is not configured. Copy frontend/.env.example to frontend/.env " +
      "and set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY."
  );
}

/**
 * Supabase handles auth and session persistence itself (localStorage +
 * auto-refresh). We deliberately do not hand-roll token storage — the client
 * attaches the access token to every PostgREST call, and row-level security
 * on `public.checks` is what guarantees a user only ever sees their own rows.
 */
export const supabase = createClient(url || "", anonKey || "", {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

/** Turn a Supabase error into one clear sentence for the auth-notice UI. */
export const authErrorMessage = (error) => {
  if (!error) return "Something went wrong. Please try again.";
  const msg = (error.message || "").toLowerCase();

  if (msg.includes("already registered") || msg.includes("already been registered")) {
    return "That email is already registered. Try signing in instead.";
  }
  if (msg.includes("invalid login credentials")) {
    return "Incorrect email or password.";
  }
  if (msg.includes("email not confirmed")) {
    return "Confirm your email first — check your inbox for the confirmation link.";
  }
  if (msg.includes("password should be at least")) {
    return "Password is too short — use at least 6 characters.";
  }
  if (msg.includes("unable to validate email") || msg.includes("invalid email")) {
    return "Enter a valid email address.";
  }
  if (msg.includes("rate limit") || msg.includes("too many")) {
    return "Too many attempts. Wait a minute and try again.";
  }
  if (msg.includes("failed to fetch") || msg.includes("network")) {
    return "Can't reach the authentication server. Check your connection.";
  }
  return error.message || "Something went wrong. Please try again.";
};

export default supabase;
