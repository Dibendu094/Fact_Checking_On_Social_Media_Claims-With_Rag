import axios from "axios";

// In dev, baseURL is empty and Vite proxies /api and /health to :8000.
// In prod, set VITE_API_URL to the backend origin.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "",
  headers: { "Content-Type": "application/json" },
  timeout: 60000,
});

/**
 * POST a claim to the RAG fact-check endpoint.
 *
 * Uses a much longer timeout than the default: the embedding model loads
 * lazily on the backend's first request after a (re)start, which alone can
 * take 60-120s on CPU. The default 60s timeout was firing before that cold
 * request ever got a chance to return, showing a false "timed out" error on
 * an otherwise-successful check.
 */
export const factCheck = async (claim) => {
  const { data } = await api.post("/api/fact-check", { claim }, { timeout: 180000 });
  return data;
};

/** GET backend health. */
export const getHealth = async () => {
  const { data } = await api.get("/health");
  return data;
};

/** POST reset a user's password (no email link — admin endpoint). */
export const resetPassword = async (email, newPassword) => {
  const { data } = await api.post("/api/reset-password", {
    email,
    new_password: newPassword,
  });
  return data;
};

// Turn an Axios error into one line that says what happened and what to do.
export const extractErrorMessage = (err) => {
  if (err?.code === "ECONNABORTED") {
    return "The check took too long and stopped. Try again in a moment.";
  }
  if (err?.response) {
    const { status, data } = err.response;
    if (status === 422) return "That claim is too short or too long to check.";
    if (status === 503) {
      return "The checking service is still starting up. Wait a moment and try again.";
    }
    const detail = data?.detail;
    if (typeof detail === "string" && detail) return detail;
    return `The server returned an error (${status}). Try again in a moment.`;
  }
  const isProd = Boolean(import.meta.env.VITE_API_URL);
  return isProd
    ? "The fact-check service is offline or still starting up. Please try again in a moment."
    : "The server isn't responding. Check that it's running on port 8000, then try again.";
};

export default api;
