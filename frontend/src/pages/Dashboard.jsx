import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, Loader2 } from "lucide-react";
import HistoryList from "../components/HistoryList";
import EvidenceModal from "../components/EvidenceModal";
import { listChecks, deleteCheck, historyErrorMessage } from "../services/history";
import useAuth from "../hooks/useAuth";

export default function Dashboard() {
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  const load = useCallback(async () => {
    if (!user) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setItems(await listChecks());
    } catch (err) {
      setError(historyErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (!authLoading) load();
  }, [authLoading, load]);

  async function handleDelete(item) {
    setDeletingId(item.id);
    setError(null);
    const previous = items;
    // Optimistic removal, rolled back if the server rejects it.
    setItems((list) => list.filter((i) => i.id !== item.id));
    setViewing((v) => (v && v.id === item.id ? null : v));
    try {
      await deleteCheck(item.id);
    } catch (err) {
      setItems(previous);
      setError(historyErrorMessage(err));
    } finally {
      setDeletingId(null);
    }
  }

  const trueCount = items.filter((i) => i.verdict === "TRUE").length;
  const falseCount = items.filter((i) => i.verdict === "FALSE").length;
  const avgConfidence = items.length
    ? Math.round(items.reduce((s, i) => s + (i.confidence || 0), 0) / items.length)
    : 0;

  if (!authLoading && !user) {
    return (
      <section className="veris-section">
        <p className="veris-eyebrow">Your activity</p>
        <h2 className="veris-section-title">Dashboard</h2>
        <div className="veris-empty-state">
          <Link to="/auth?mode=signin" style={{ color: "var(--periwinkle)", fontWeight: 600 }}>
            Sign in
          </Link>{" "}
          to see the claims you've checked.
        </div>
      </section>
    );
  }

  return (
    <section className="veris-section">
      <p className="veris-eyebrow">Your activity</p>
      <h2 className="veris-section-title">Dashboard</h2>
      <p className="veris-section-sub">
        Track how many claims you've checked and revisit past results.
      </p>

      <div className="veris-stats-row">
        <div className="veris-stat-card">
          <span className="veris-stat-num">{items.length}</span>
          <span className="veris-stat-label">Claims checked</span>
        </div>
        <div className="veris-stat-card">
          <span className="veris-stat-num">{trueCount}</span>
          <span className="veris-stat-label">Marked true</span>
        </div>
        <div className="veris-stat-card">
          <span className="veris-stat-num">{falseCount}</span>
          <span className="veris-stat-label">Marked false</span>
        </div>
        <div className="veris-stat-card">
          <span className="veris-stat-num">{avgConfidence || "—"}</span>
          <span className="veris-stat-label">Avg. confidence</span>
        </div>
      </div>

      {error && (
        <div className="veris-auth-notice veris-error" style={{ marginBottom: 18 }} role="alert">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {loading || authLoading ? (
        <div className="veris-empty-state">
          <Loader2 size={18} className="veris-spin" style={{ verticalAlign: "middle" }} /> Loading
          your history…
        </div>
      ) : (
        <HistoryList
          items={items}
          onView={setViewing}
          onDelete={handleDelete}
          deletingId={deletingId}
        />
      )}

      <EvidenceModal item={viewing} onClose={() => setViewing(null)} />
    </section>
  );
}
