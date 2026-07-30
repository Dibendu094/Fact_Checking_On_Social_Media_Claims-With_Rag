import { Eye, Trash2, Loader2 } from "lucide-react";
import { verdictClass } from "../utils/verisVerdicts";

export default function HistoryList({ items, onView, onDelete, deletingId }) {
  if (!items.length) {
    return (
      <div className="veris-empty-state">
        No claims checked yet. Head to Fact Check to analyze your first claim.
      </div>
    );
  }

  return (
    <div className="veris-history-list">
      {items.map((item) => (
        <div className="veris-history-row" key={item.id}>
          <div className="veris-history-claim" title={item.claim}>
            {item.claim}
          </div>
          <div className={`veris-history-badge veris-${verdictClass(item.verdict)}`}>
            {item.verdict}
          </div>
          <div className="veris-history-confidence">{item.confidence}%</div>
          <div className="veris-history-date">{item.date}</div>
          <div className="veris-history-actions">
            <button
              className="veris-view-btn"
              onClick={() => onView(item)}
              aria-label="View evidence"
            >
              <Eye size={16} />
            </button>
            <button
              className="veris-delete-btn"
              onClick={() => onDelete(item)}
              disabled={deletingId === item.id}
              aria-label="Delete entry"
            >
              {deletingId === item.id ? (
                <Loader2 size={16} className="veris-spin" />
              ) : (
                <Trash2 size={16} />
              )}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
