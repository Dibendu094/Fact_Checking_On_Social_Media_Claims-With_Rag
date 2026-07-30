import { useState } from "react";
import {
  ArrowRight, ArrowLeft, Check, Eye, EyeOff,
  AlertCircle, CheckCircle2, Loader2,
} from "lucide-react";
import useAuth from "../hooks/useAuth";

/** Client-side password rules, kept from the design file as a first check. */
export function pwChecks(pw) {
  const lengthOk = pw.length >= 6;
  const digitsOk = (pw.match(/\d/g) || []).length >= 2;
  const specialOk = /[^A-Za-z0-9]/.test(pw);
  return { lengthOk, digitsOk, specialOk, allOk: lengthOk && digitsOk && specialOk };
}

const isValidEmail = (email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());

function PwRules({ checks }) {
  const rows = [
    [checks.lengthOk, "At least 6 characters"],
    [checks.digitsOk, "At least 2 numbers"],
    [checks.specialOk, "At least 1 special character"],
  ];
  return (
    <div className="veris-pw-rules">
      {rows.map(([ok, label]) => (
        <span key={label} className={`veris-pw-rule ${ok ? "veris-ok" : ""}`}>
          <span className="veris-dot">{ok && <Check size={9} />}</span>
          {label}
        </span>
      ))}
    </div>
  );
}

/**
 * Auth screens wired to Supabase Auth.
 *
 * `mode` / `setMode`: signin | signup | forgot
 * "forgot" resets the password via a backend admin endpoint (email + new
 * password) — no email link or current password needed.
 */
export default function AuthCard({ mode, setMode, suppressRedirectRef, onSignedIn }) {
  const { signUp, signIn, resetPassword } = useAuth();

  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const [signupForm, setSignupForm] = useState({ username: "", email: "", password: "", confirm: "" });
  const [signinForm, setSigninForm] = useState({ email: "", password: "" });
  const [changeForm, setChangeForm] = useState({ email: "", password: "", confirm: "" });

  const [showSignupPw, setShowSignupPw] = useState(false);
  const [showConfirmPw, setShowConfirmPw] = useState(false);
  const [showSigninPw, setShowSigninPw] = useState(false);
  const [showChangePw, setShowChangePw] = useState(false);
  const [showChangeConfirmPw, setShowChangeConfirmPw] = useState(false);

  const signupChecks = pwChecks(signupForm.password);
  const changeChecks = pwChecks(changeForm.password);

  const switchMode = (next) => {
    setMode(next);
    setNotice(null);
  };

  async function handleSignup(e) {
    e.preventDefault();
    if (!signupForm.username.trim()) return setNotice({ type: "error", text: "Enter a username." });
    if (!isValidEmail(signupForm.email)) return setNotice({ type: "error", text: "Enter a valid email address." });
    if (!signupChecks.allOk) return setNotice({ type: "error", text: "Password does not meet all the requirements below." });
    if (signupForm.password !== signupForm.confirm) return setNotice({ type: "error", text: "Passwords do not match." });

    setBusy(true);
    // Held true until any transient session from signUp() is fully cleared,
    // so Auth.jsx's "already signed in" redirect can't fire on that flash
    // and bounce the user away before they see the sign-in form.
    if (suppressRedirectRef) suppressRedirectRef.current = true;
    try {
      await signUp(signupForm);
      const email = signupForm.email.trim();
      setSignupForm({ username: "", email: "", password: "", confirm: "" });
      // No confirmation ceremony: the account is usable immediately. Prefill
      // the sign-in form with the email just used and let the user log in,
      // same as a normal sign-in.
      setSigninForm({ email, password: "" });
      setMode("signin");
      setNotice({ type: "success", text: "Account created. Sign in with your credentials." });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setBusy(false);
      if (suppressRedirectRef) suppressRedirectRef.current = false;
    }
  }

  async function handleSignin(e) {
    e.preventDefault();
    if (!isValidEmail(signinForm.email)) return setNotice({ type: "error", text: "Enter a valid email address." });
    if (!signinForm.password) return setNotice({ type: "error", text: "Enter your password." });

    setBusy(true);
    try {
      await signIn(signinForm);
      setNotice(null);
      onSignedIn?.();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  async function handleResetPassword(e) {
    e.preventDefault();
    if (!isValidEmail(changeForm.email)) return setNotice({ type: "error", text: "Enter a valid email address." });
    if (!changeChecks.allOk) return setNotice({ type: "error", text: "New password does not meet all the requirements below." });
    if (changeForm.password !== changeForm.confirm) return setNotice({ type: "error", text: "Passwords do not match." });

    setBusy(true);
    try {
      await resetPassword(changeForm.email, changeForm.password);
      setChangeForm({ email: "", password: "", confirm: "" });
      setMode("signin");
      setNotice({ type: "success", text: "Password updated. Sign in with your new password." });
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || "Something went wrong.";
      setNotice({ type: "error", text: msg });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="veris-auth-wrap">
      <div className="veris-auth-card">
        {mode !== "forgot" ? (
          <div className="veris-auth-switch">
            <button className={mode === "signin" ? "veris-active" : ""} onClick={() => switchMode("signin")}>Sign in</button>
            <button className={mode === "signup" ? "veris-active" : ""} onClick={() => switchMode("signup")}>Sign up</button>
          </div>
        ) : (
          <button className="veris-back-link" onClick={() => switchMode("signin")}>
            <ArrowLeft size={14} />
            Back to sign in
          </button>
        )}

        <p className="veris-eyebrow veris-auth-eyebrow">
          {mode === "signup" && "Join Veris"}
          {mode === "signin" && "Welcome back"}
          {mode === "forgot" && "Account recovery"}
        </p>
        <h2 className="veris-section-title veris-auth-title">
          {mode === "signup" && "Create your account"}
          {mode === "signin" && "Sign in to continue"}
          {mode === "forgot" && "Reset your password"}
        </h2>

        {notice && (
          <div className={`veris-auth-notice veris-${notice.type}`} role="status">
            {notice.type === "error" ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
            <span>{notice.text}</span>
          </div>
        )}

        {mode === "signup" && (
          <form className="veris-auth-form" onSubmit={handleSignup}>
            <div className="veris-field">
              <label htmlFor="su-user">Username</label>
              <div className="veris-input-wrap">
                <input id="su-user" type="text" value={signupForm.username}
                  onChange={(e) => setSignupForm((f) => ({ ...f, username: e.target.value }))}
                  placeholder="e.g. priya_sharma" />
              </div>
            </div>
            <div className="veris-field">
              <label htmlFor="su-email">Email</label>
              <div className="veris-input-wrap">
                <input id="su-email" type="email" value={signupForm.email}
                  onChange={(e) => setSignupForm((f) => ({ ...f, email: e.target.value }))}
                  placeholder="you@example.com" />
              </div>
            </div>
            <div className="veris-field">
              <label htmlFor="su-pw">Password</label>
              <div className="veris-input-wrap">
                <input id="su-pw" type={showSignupPw ? "text" : "password"} value={signupForm.password}
                  onChange={(e) => setSignupForm((f) => ({ ...f, password: e.target.value }))}
                  placeholder="Create a password" />
                <button type="button" className="veris-eye-btn" onClick={() => setShowSignupPw((s) => !s)} aria-label="Toggle password visibility">
                  {showSignupPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            <PwRules checks={signupChecks} />
            <div className="veris-field">
              <label htmlFor="su-confirm">Confirm password</label>
              <div className="veris-input-wrap">
                <input id="su-confirm" type={showConfirmPw ? "text" : "password"} value={signupForm.confirm}
                  onChange={(e) => setSignupForm((f) => ({ ...f, confirm: e.target.value }))}
                  placeholder="Re-enter password" />
                <button type="button" className="veris-eye-btn" onClick={() => setShowConfirmPw((s) => !s)} aria-label="Toggle password visibility">
                  {showConfirmPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {signupForm.confirm && (
                <span className={`veris-pw-rule ${signupForm.password === signupForm.confirm ? "veris-ok" : ""}`}>
                  <span className="veris-dot">{signupForm.password === signupForm.confirm && <Check size={9} />}</span>
                  Passwords match
                </span>
              )}
            </div>
            <button type="submit" className="veris-auth-submit" disabled={busy}>
              {busy ? <><Loader2 size={16} className="veris-spin" />Creating…</> : <>Create account <ArrowRight size={16} /></>}
            </button>
          </form>
        )}

        {mode === "signin" && (
          <form className="veris-auth-form" onSubmit={handleSignin}>
            <div className="veris-field">
              <label htmlFor="si-email">Email</label>
              <div className="veris-input-wrap">
                <input id="si-email" type="email" value={signinForm.email}
                  onChange={(e) => setSigninForm((f) => ({ ...f, email: e.target.value }))}
                  placeholder="you@example.com" />
              </div>
            </div>
            <div className="veris-field">
              <label htmlFor="si-pw">Password</label>
              <div className="veris-input-wrap">
                <input id="si-pw" type={showSigninPw ? "text" : "password"} value={signinForm.password}
                  onChange={(e) => setSigninForm((f) => ({ ...f, password: e.target.value }))}
                  placeholder="Enter your password" />
                <button type="button" className="veris-eye-btn" onClick={() => setShowSigninPw((s) => !s)} aria-label="Toggle password visibility">
                  {showSigninPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <button type="button" className="veris-forgot-link" onClick={() => { setMode("forgot"); setNotice(null); }}>
                Forgot password?
              </button>
            </div>
            <button type="submit" className="veris-auth-submit" disabled={busy}>
              {busy ? <><Loader2 size={16} className="veris-spin" />Signing in…</> : <>Sign in <ArrowRight size={16} /></>}
            </button>
          </form>
        )}

        {mode === "forgot" && (
          <form className="veris-auth-form" onSubmit={handleResetPassword}>
            <div className="veris-field">
              <label htmlFor="cp-email">Email</label>
              <div className="veris-input-wrap">
                <input id="cp-email" type="email" value={changeForm.email}
                  onChange={(e) => setChangeForm((f) => ({ ...f, email: e.target.value }))}
                  placeholder="you@example.com" />
              </div>
            </div>
            <div className="veris-field">
              <label htmlFor="cp-new">New password</label>
              <div className="veris-input-wrap">
                <input id="cp-new" type={showChangePw ? "text" : "password"} value={changeForm.password}
                  onChange={(e) => setChangeForm((f) => ({ ...f, password: e.target.value }))}
                  placeholder="Create a new password" />
                <button type="button" className="veris-eye-btn" onClick={() => setShowChangePw((s) => !s)} aria-label="Toggle password visibility">
                  {showChangePw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            <PwRules checks={changeChecks} />
            <div className="veris-field">
              <label htmlFor="cp-confirm">Confirm new password</label>
              <div className="veris-input-wrap">
                <input id="cp-confirm" type={showChangeConfirmPw ? "text" : "password"} value={changeForm.confirm}
                  onChange={(e) => setChangeForm((f) => ({ ...f, confirm: e.target.value }))}
                  placeholder="Re-enter new password" />
                <button type="button" className="veris-eye-btn" onClick={() => setShowChangeConfirmPw((s) => !s)} aria-label="Toggle password visibility">
                  {showChangeConfirmPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {changeForm.confirm && (
                <span className={`veris-pw-rule ${changeForm.password === changeForm.confirm ? "veris-ok" : ""}`}>
                  <span className="veris-dot">{changeForm.password === changeForm.confirm && <Check size={9} />}</span>
                  Passwords match
                </span>
              )}
            </div>
            <button type="submit" className="veris-auth-submit" disabled={busy}>
              {busy ? <><Loader2 size={16} className="veris-spin" />Updating…</> : <>Reset password <ArrowRight size={16} /></>}
            </button>
          </form>
        )}

        {mode !== "forgot" && (
          <p className="veris-auth-footer-link">
            {mode === "signin" ? (
              <>Don't have an account? <button onClick={() => switchMode("signup")}>Sign up</button></>
            ) : (
              <>Already have an account? <button onClick={() => switchMode("signin")}>Sign in</button></>
            )}
          </p>
        )}
      </div>
    </div>
  );
}
