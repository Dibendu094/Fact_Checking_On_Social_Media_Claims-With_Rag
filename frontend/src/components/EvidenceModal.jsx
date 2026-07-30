import { useEffect } from "react";
import { X, ExternalLink } from "lucide-react";
import { verdictClass, tierLabel } from "../utils/verisVerdicts";

export default function EvidenceModal({ item, onClose }) {
  useEffect(() => {
    if (!item) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, onClose]);

  if (!item) return null;

  const tier = tierLabel(item.tier);

  return (
    <div className="veris-modal-overlay" onClick={onClose}>
      <div
        className="veris-modal-box"
        role="dialog"
        aria-modal="true"
        aria-label="Claim evidence"
        onClick={(e) => e.stopPropagation()}
      >
        <button className="veris-modal-close" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>

        <p className="veris-eyebrow" style={{ fontSize: 16 }}>
          Claim reviewed
        </p>
        <p className="veris-modal-claim-text">"{item.claim}"</p>

        <div className="veris-modal-verdict-row">
          <span
            className={`veris-history-badge veris-${verdictClass(item.verdict)}`}
            style={{ fontSize: 12.5, padding: "6px 14px" }}
          >
            {item.verdict}
          </span>
          <span className="veris-modal-confidence">{item.confidence}% confidence</span>
          <span className="veris-modal-confidence">{item.date}</span>
        </div>

        <div className="veris-explanation">
          <h4>Evidence</h4>
          <p>{item.explanation}</p>
          {item.evidence?.length > 0 && (
            <ul>
              {item.evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}

          {item.sources?.length > 0 && (
            <>
              <h4 style={{ marginTop: 20 }}>Published fact-checks</h4>
              <ul className="veris-source-list">
                {item.sources.map((s, i) => (
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
    </div>
  );
}
