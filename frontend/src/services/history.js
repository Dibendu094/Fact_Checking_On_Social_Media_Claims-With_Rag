import { supabase } from "./supabase";

/**
 * Per-user claim history, stored in Supabase (`public.checks`).
 *
 * Isolation is enforced by row-level security in Postgres, not here:
 *   select/insert/delete policies all require auth.uid() = user_id.
 * Even a tampered client cannot read another user's rows.
 */

const TABLE = "checks";

/** Map a row from the DB into the shape the UI components expect. */
const fromRow = (row) => ({
  id: row.id,
  claim: row.claim,
  verdict: row.verdict,
  confidence: row.confidence,
  explanation: row.explanation || "",
  evidence: Array.isArray(row.evidence) ? row.evidence : [],
  tier: row.tier || null,
  sources: Array.isArray(row.sources) ? row.sources : [],
  createdAt: row.created_at,
  date: new Date(row.created_at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }),
});

/** Fetch the signed-in user's checks, newest first. */
export async function listChecks() {
  const { data, error } = await supabase
    .from(TABLE)
    .select("*")
    .order("created_at", { ascending: false })
    .limit(100);
  if (error) throw error;
  return (data || []).map(fromRow);
}

/**
 * Persist a completed fact-check for the signed-in user.
 * `user_id` must be set explicitly so the RLS insert policy passes.
 */
export async function saveCheck(userId, claim, result) {
  const payload = {
    user_id: userId,
    claim,
    verdict: result.verdict,
    confidence: Math.round(result.confidence ?? 0),
    explanation: result.explanation || "",
    evidence: result.key_points || [],
    tier: result.confidence_tier || null,
    sources: result.sources || [],
  };
  const { data, error } = await supabase
    .from(TABLE)
    .insert(payload)
    .select()
    .single();
  if (error) throw error;
  return fromRow(data);
}

/**
 * Count the signed-in user's checks saved today (local calendar day), for the
 * daily claim-limit gate. RLS already restricts this to the caller's own
 * rows, so no explicit user filter is needed. Backing this off `checks`
 * (rather than a separate counter table) means the count is naturally
 * accurate across devices — whichever device saved a check, this query sees it.
 */
export async function countTodayChecks() {
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);
  const { count, error } = await supabase
    .from(TABLE)
    .select("id", { count: "exact", head: true })
    .gte("created_at", startOfDay.toISOString());
  if (error) throw error;
  return count ?? 0;
}

/** Delete one entry. RLS ensures this only ever affects the caller's own row. */
export async function deleteCheck(id) {
  const { error } = await supabase.from(TABLE).delete().eq("id", id);
  if (error) throw error;
  return true;
}

export const historyErrorMessage = (error) => {
  const msg = (error?.message || "").toLowerCase();
  if (msg.includes("jwt") || msg.includes("expired")) {
    return "Your session expired. Please sign in again.";
  }
  if (msg.includes("row-level security") || msg.includes("policy")) {
    return "You don't have permission to do that.";
  }
  if (msg.includes("failed to fetch") || msg.includes("network")) {
    return "Can't reach the history service. Check your connection.";
  }
  return error?.message || "Could not load your history.";
};
