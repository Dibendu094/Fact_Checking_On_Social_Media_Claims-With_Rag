import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabaseConfigured = Boolean(url && anonKey);

if (!supabaseConfigured) {
  console.warn(
    "Supabase env vars missing (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY). " +
      "Auth features will be disabled until they are set in Vercel and the app is redeployed."
  );
}

export const supabase = supabaseConfigured
  ? createClient(url, anonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;

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
