import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, RotateCcw } from "lucide-react";
import FactCheckForm, { MIN_CLAIM, MAX_CLAIM } from "../components/FactCheckForm";
import ResultCard from "../components/ResultCard";
import LimitModal from "../components/LimitModal";
import { factCheck, extractErrorMessage } from "../services/api";
import { saveCheck, historyErrorMessage } from "../services/history";
import useAuth from "../hooks/useAuth";
import useClaimLimits from "../hooks/useClaimLimits";

export default function FactCheck() {
  const { user } = useAuth();
  const { kind, count, limit, atLimit, registerClaim } = useClaimLimits();
  const [claim, setClaim] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [saveWarning, setSaveWarning] = useState(null);
  const [showLimitModal, setShowLimitModal] = useState(false);

  async function handleAnalyze() {
    const text = claim.trim();
    if (text.length < MIN_CLAIM || text.length > MAX_CLAIM || isAnalyzing) return;
    // Defense in depth: the form's button already intercepts clicks at the
    // limit, but never let a check through this path either.
    if (atLimit) {
      setShowLimitModal(true);
      return;
    }

    setIsAnalyzing(true);
    setError(null);
    setSaveWarning(null);
    setResult(null);

    try {
      // Real RAG call: embed -> Pinecone -> LLM. Drives the stamp + ring.
      const data = await factCheck(text);
      setResult(data);
      // Count only successful checks toward the limit.
      registerClaim();

      // Persist to this user's history. A save failure must not discard a
      // verdict the user is already looking at, so it only warns.
      if (user) {
        try {
          await saveCheck(user.id, text, data);
        } catch (err) {
          setSaveWarning(historyErrorMessage(err));
        }
      }
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setIsAnalyzing(false);
    }
  }

  function handleReset() {
    setClaim("");
    setResult(null);
    setError(null);
    setSaveWarning(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <section className="veris-section">
      <p className="veris-eyebrow">Submit a claim</p>
      <h2 className="veris-section-title">
        Is it <em>true</em>?
      </h2>
      <p className="veris-section-sub">
        Paste a claim you saw on social media. Veris retrieves relevant evidence and
        returns a verdict.
      </p>

      <FactCheckForm
        claim={claim}
        setClaim={setClaim}
        onAnalyze={handleAnalyze}
        isAnalyzing={isAnalyzing}
        limitCount={count}
        limitMax={limit}
        atLimit={atLimit}
        onLimitHit={() => setShowLimitModal(true)}
      />

      {error && (
        <div className="veris-auth-notice veris-error" style={{ marginTop: 18 }} role="alert">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {saveWarning && (
        <div className="veris-auth-notice veris-error" style={{ marginTop: 18 }} role="status">
          <AlertCircle size={16} />
          <span>Verdict shown, but it wasn't saved to your history: {saveWarning}</span>
        </div>
      )}

      {result && !user && (
        <div className="veris-auth-notice veris-success" style={{ marginTop: 18 }} role="status">
          <AlertCircle size={16} />
          <span>
            <Link to="/auth?mode=signin" style={{ color: "inherit", fontWeight: 600 }}>
              Sign in
            </Link>{" "}
            to save checks to your dashboard history.
          </span>
        </div>
      )}

      <ResultCard result={result} />

      {result && (
        <div style={{ marginTop: 20, display: "flex", justifyContent: "center" }}>
          <button className="veris-btn-secondary" onClick={handleReset}>
            <RotateCcw size={15} />
            Try another claim
          </button>
        </div>
      )}

      <LimitModal open={showLimitModal} kind={kind} onClose={() => setShowLimitModal(false)} />
    </section>
  );
}
