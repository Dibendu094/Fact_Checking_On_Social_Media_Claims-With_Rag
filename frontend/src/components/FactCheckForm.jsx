import { ArrowRight, Loader2 } from "lucide-react";

export const MIN_CLAIM = 10;
export const MAX_CLAIM = 1000;

const EXAMPLE_CLAIMS = [
  "NASA confirmed the moon landing footage was staged using CGI technology.",
  "Drinking 8 glasses of water a day is scientifically proven to boost memory by 50%.",
  "A viral post claims a new law bans all social media for under-18s starting next month.",
];

/**
 * Claim entry with the 10–1000 character client-side guard kept from the
 * design file. The backend enforces the same bounds (422), and those errors
 * surface through the parent's error slot.
 *
 * Limit props (from useClaimLimits, via the parent page): when `atLimit` is
 * true the submit button LOOKS disabled but stays clickable — the click
 * opens the limit modal (via `onLimitHit`) instead of running `onAnalyze`,
 * so the "21st claim" tap always gets a clear explanation, not a dead button.
 */
export default function FactCheckForm({
  claim,
  setClaim,
  onAnalyze,
  isAnalyzing,
  limitCount = 0,
  limitMax = 0,
  atLimit = false,
  onLimitHit,
}) {
  const len = claim.length;
  const lengthOk = len >= MIN_CLAIM && len <= MAX_CLAIM;
  const canSubmit = lengthOk && !isAnalyzing;
  const countClass = len > 0 && len < MIN_CLAIM ? "veris-warn" : len >= MIN_CLAIM ? "veris-ready" : "";

  const handleClick = () => {
    if (atLimit) {
      onLimitHit?.();
      return;
    }
    onAnalyze();
  };

  return (
    <div className="veris-claim-box">
      <div className="veris-claim-box-header">
        <span className="veris-claim-label">Your claim</span>
        <span className={`veris-char-count ${countClass}`}>
          {len}/{MAX_CLAIM}
        </span>
      </div>

      <textarea
        value={claim}
        onChange={(e) => setClaim(e.target.value.slice(0, MAX_CLAIM))}
        maxLength={MAX_CLAIM}
        aria-label="Claim to fact-check"
        placeholder="e.g. Drinking celery juice every morning cures anxiety within a week."
      />

      <div className="veris-progress-track">
        <div
          className="veris-progress-fill"
          style={{
            width: `${Math.min((len / MAX_CLAIM) * 100, 100)}%`,
            background: len < MIN_CLAIM ? "var(--wine)" : "var(--periwinkle)",
          }}
        />
      </div>

      <div className="veris-claim-meta">
        <span className={`veris-char-count ${countClass}`}>
          {len < MIN_CLAIM
            ? len === 0
              ? `Minimum ${MIN_CLAIM} characters`
              : `${MIN_CLAIM - len} more characters needed`
            : "Looks good — ready to analyze"}
        </span>
        <button
          className={`veris-btn-analyze ${atLimit ? "veris-limit-reached" : ""}`}
          disabled={!canSubmit && !atLimit}
          onClick={handleClick}
        >
          {isAnalyzing ? (
            <>
              <Loader2 size={16} className="veris-spin" />
              Analyzing
            </>
          ) : (
            <>
              Analyze claim <ArrowRight size={16} />
            </>
          )}
        </button>
      </div>

      {limitMax > 0 && (
        <div className={`veris-limit-note ${atLimit ? "veris-limit-low" : ""}`} style={{ marginTop: 10 }}>
          Claims checked{limitMax === 20 ? "" : " today"}: {Math.min(limitCount, limitMax)}/{limitMax}
        </div>
      )}

      <div className="veris-examples-row">
        <span className="veris-examples-label">Try an example:</span>
        {EXAMPLE_CLAIMS.map((ex, i) => (
          <button
            key={i}
            className="veris-example-chip"
            onClick={() => setClaim(ex)}
            title={ex}
            disabled={isAnalyzing}
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
