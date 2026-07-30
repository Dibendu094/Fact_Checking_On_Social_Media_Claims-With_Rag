import { useCallback, useEffect, useState } from "react";
import useAuth from "./useAuth";
import { countTodayChecks } from "../services/history";

export const ANON_LIMIT = 20;
export const DAILY_LIMIT = 1000;

const ANON_KEY = "veris_anonymous_claims";
const DAILY_COUNT_KEY = "veris_daily_claims_count";
const DAILY_DATE_KEY = "veris_daily_claims_date";

const todayString = () => {
  const d = new Date();
  // Local calendar day, not UTC — matches "reset at midnight" for the user's clock.
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
};

const readInt = (key, fallback = 0) => {
  const raw = localStorage.getItem(key);
  const n = raw == null ? NaN : parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
};

/**
 * Freemium claim-check gate.
 *
 * Anonymous visitors: up to ANON_LIMIT claims per browser, tracked purely in
 * localStorage (`veris_anonymous_claims`) — persists across refreshes, resets
 * only if the user clears storage.
 *
 * Signed-in users: up to DAILY_LIMIT claims per local calendar day, tracked
 * in localStorage (`veris_daily_claims_count` / `veris_daily_claims_date`)
 * for instant UI feedback, reconciled against the real count of today's
 * saved checks in Supabase on login/mount so a second device (or a cleared
 * localStorage) doesn't under-count. The server value wins when available.
 */
export default function useClaimLimits() {
  const { user } = useAuth();
  const kind = user ? "daily" : "anonymous";
  const limit = user ? DAILY_LIMIT : ANON_LIMIT;

  const [count, setCount] = useState(0);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    let active = true;

    if (!user) {
      setCount(readInt(ANON_KEY, 0));
      return undefined;
    }

    // Signed in: roll the local counter over if the stored date isn't today,
    // then reconcile with the server's real count for today.
    const today = todayString();
    let localCount = readInt(DAILY_COUNT_KEY, 0);
    if (localStorage.getItem(DAILY_DATE_KEY) !== today) {
      localCount = 0;
      localStorage.setItem(DAILY_DATE_KEY, today);
      localStorage.setItem(DAILY_COUNT_KEY, "0");
    }
    setCount(localCount);

    setSyncing(true);
    countTodayChecks()
      .then((serverCount) => {
        if (!active) return;
        const reconciled = Math.max(localCount, serverCount);
        setCount(reconciled);
        localStorage.setItem(DAILY_DATE_KEY, today);
        localStorage.setItem(DAILY_COUNT_KEY, String(reconciled));
      })
      .catch(() => {
        // Offline or query failed — keep the local count, don't block the UI.
      })
      .finally(() => {
        if (active) setSyncing(false);
      });

    return () => {
      active = false;
    };
  }, [user]);

  /** Call once, after a claim check succeeds. */
  const registerClaim = useCallback(() => {
    if (!user) {
      const next = readInt(ANON_KEY, 0) + 1;
      localStorage.setItem(ANON_KEY, String(next));
      setCount(next);
      return;
    }
    const today = todayString();
    const base = localStorage.getItem(DAILY_DATE_KEY) === today ? readInt(DAILY_COUNT_KEY, 0) : 0;
    const next = base + 1;
    localStorage.setItem(DAILY_DATE_KEY, today);
    localStorage.setItem(DAILY_COUNT_KEY, String(next));
    setCount(next);
  }, [user]);

  const remaining = Math.max(0, limit - count);
  const atLimit = count >= limit;

  return { kind, count, limit, remaining, atLimit, syncing, registerClaim };
}
