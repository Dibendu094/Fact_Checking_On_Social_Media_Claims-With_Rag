import { useEffect, useState } from "react";
import { Check, X, AlertTriangle, HelpCircle, ExternalLink } from "lucide-react";
import { verdictClass, verdictLabel, tierLabel } from "../utils/verisVerdicts";

const RADIUS = 46;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

const ICONS = {
  true: Check,
  false: X,
  misleading: AlertTriangle,
  unverified: HelpCircle,
};

/**
 * Verdict stamp + confidence ring, driven entirely by the real API response.
 * The ring animates from 0 to the returned confidence on mount.
 */
export default function ResultCard({ result }) {
  const [ringProgress, setRingProgress] = useState(0);

  const cls = verdictClass(result?.verdict);
  const confidence = Math.round(result?.confidence ?? 0);

  useEffect(() => {
    if (!result) return undefined;
    setRingProgress(0);
    const t = setTimeout(() => setRingProgress(confidence), 60);
    return () => clearTimeout(t);
  }, [result, confidence]);

  if (!result) return null;

  const Icon = ICONS[cls] || HelpCircle;
  const evidence = result.key_points || [];
  const sources = result.sources || [];
  const tier = tierLabel(result.confidence_tier);

  return (
    <div className="veris-result-card">
      <div className={`veris-stamp veris-${cls}`}>
        <Icon size={26} />
        <span>{verdictLabel(result.verdict)}</span>
      </div>

      <div className="veris-confidence-ring">
        <svg width="120" height="120" viewBox="0 0 120 120">
          <circle className="veris-ring-bg" cx="60" cy="60" r={RADIUS} />
          <circle
            className="veris-ring-fg"
            cx="60"
            cy="60"
            r={RADIUS}
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE - (ringProgress / 100) * CIRCUMFERENCE}
          />
        </svg>
        <span className="veris-ring-value">{confidence}%</span>
        <span className="veris-ring-label">Confidence</span>
      </div>

      <div className="veris-explanation">
        <h4>Evidence</h4>
        <p>{result.explanation}</p>

        {evidence.length > 0 && (
          <ul>
            {evidence.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        )}

        {result.recommendation && (
          <p style={{ marginTop: 14 }}>{result.recommendation}</p>
        )}

        {sources.length > 0 && (
          <>
            <h4 style={{ marginTop: 20 }}>Published fact-checks</h4>
            <ul className="veris-source-list">
              {sources.map((s, i) => (
                <li key={i} className="veris-source-item">
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    {s.title || s.url}
                    <ExternalLink size={12} />
                  </a>
                  {s.publisher && <div className="veris-source-pub">{s.publisher}</div>}
                </li>
              ))}
            </ul>
          </>
        )}

        {tier && <span className="veris-tier-note">{tier}</span>}
      </div>
    </div>
  );
}
