import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { X, ShieldCheck, Clock } from "lucide-react";
import { ANON_LIMIT, DAILY_LIMIT } from "../hooks/useClaimLimits";

/**
 * Shown when a claim-check gate is hit. Dismissible (X or backdrop) — closing
 * it never submits the pending claim, it just stays unsent.
 *
 * kind: "anonymous" -> offer sign in / sign up.
 *       "daily"      -> signed-in user hit the 1000/day cap; just an OK.
 */
export default function LimitModal({ open, kind, onClose }) {
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const goTo = (path) => {
    onClose();
    navigate(path);
  };

  return (
    <div className="veris-modal-overlay" onClick={onClose}>
      <div
        className="veris-modal-box"
        role="dialog"
        aria-modal="true"
        aria-label={kind === "anonymous" ? "Sign in to continue" : "Daily limit reached"}
        onClick={(e) => e.stopPropagation()}
        style={{ textAlign: "center" }}
      >
        <button className="veris-modal-close" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>

        <div
          style={{
            width: 48, height: 48, borderRadius: "50%", margin: "4px auto 16px",
            display: "flex", alignItems: "center", justifyContent: "center",
            background: kind === "anonymous" ? "var(--periwinkle-soft)" : "var(--amber-soft)",
            color: kind === "anonymous" ? "var(--periwinkle)" : "var(--amber)",
          }}
        >
          {kind === "anonymous" ? <ShieldCheck size={22} /> : <Clock size={22} />}
        </div>

        {kind === "anonymous" ? (
          <>
            <h3 className="veris-section-title" style={{ fontSize: 24, marginBottom: 10 }}>
              You've checked {ANON_LIMIT} claims
            </h3>
            <p style={{ color: "var(--slate)", fontSize: 15, lineHeight: 1.6, margin: "0 0 24px" }}>
              Sign in or create an account to check unlimited claims and save your history.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <button className="veris-btn-primary" style={{ justifyContent: "center" }}
                onClick={() => goTo("/auth?mode=signin")}>
                Sign in
              </button>
              <button className="veris-forgot-link" style={{ alignSelf: "center" }}
                onClick={() => goTo("/auth?mode=signup")}>
                Create an account
              </button>
            </div>
          </>
        ) : (
          <>
            <h3 className="veris-section-title" style={{ fontSize: 24, marginBottom: 10 }}>
              Daily limit reached
            </h3>
            <p style={{ color: "var(--slate)", fontSize: 15, lineHeight: 1.6, margin: "0 0 24px" }}>
              You've checked {DAILY_LIMIT} claims today. Check back tomorrow for more.
            </p>
            <button className="veris-btn-primary" style={{ justifyContent: "center", width: "100%" }}
              onClick={onClose}>
              OK
            </button>
          </>
        )}
      </div>
    </div>
  );
}
