/**
 * The backend returns four verdicts. The original two-verdict mock only styled
 * TRUE/FALSE, so MISLEADING and UNVERIFIED were added to the palette rather
 * than collapsed onto FALSE — reporting an uncertain result as definitive
 * would misrepresent what the pipeline actually found.
 */

export const VERDICTS = ["TRUE", "FALSE", "MISLEADING", "UNVERIFIED"];

/** CSS modifier class: `stamp.true`, `history-badge.misleading`, … */
export const verdictClass = (verdict) =>
  String(verdict || "UNVERIFIED").toLowerCase();

/** Text shown inside the stamp. */
export const verdictLabel = (verdict) =>
  String(verdict || "UNVERIFIED").toUpperCase();

export const isPositive = (verdict) => verdictLabel(verdict) === "TRUE";

/** How the check was sourced, in plain language. */
export const TIER_LABELS = {
  HIGH: "Close match in the fact-check database",
  MEDIUM: "Partial match in the fact-check database",
  LOW: "No close match — checked against live sources",
  VERY_LOW: "No matching fact-check found",
};

export const tierLabel = (tier) => TIER_LABELS[tier] || null;
