import { useEffect, useState } from "react";
import {
  Brain, Database, Zap, Globe, Search, Cpu, MessageSquare, ShieldCheck,
} from "lucide-react";
import { getStats } from "../services/api";

// Fallback shown until the live count loads (or if the backend is briefly
// unreachable) — kept roughly current, but the real number always wins.
const FALLBACK_COUNT = 484848;

const STEPS = [
  { icon: MessageSquare, title: "Submit a claim", desc: "You paste a statement you saw on social media." },
  { icon: Cpu, title: "Embed it", desc: "multilingual-e5-large turns it into a 1024-dimension vector." },
  { icon: Brain, title: "Reason", desc: "If the match is weak, a live web search runs too, then Groq weighs it all." },
  { icon: ShieldCheck, title: "Return a verdict", desc: "You get TRUE / FALSE / MISLEADING / UNVERIFIED, a confidence score, and sources." },
];

const STACK = [
  "FastAPI", "React + Vite", "Supabase (auth + history)", "Pinecone",
  "multilingual-e5-large", "Groq · Llama 3.3 70B", "Google Fact Check Tools API",
];

export default function About() {
  const [totalClaims, setTotalClaims] = useState(FALLBACK_COUNT);

  useEffect(() => {
    let active = true;
    getStats()
      .then((s) => {
        if (active && typeof s.total_claims === "number") setTotalClaims(s.total_claims);
      })
      .catch(() => {
        // Keep the fallback — an About page stat isn't worth an error banner.
      });
    return () => {
      active = false;
    };
  }, []);

  const countLabel = totalClaims.toLocaleString();
  const FEATURES = [
    { icon: Brain, title: "AI-powered", desc: "Groq's Llama 3.3 70B reasons over retrieved evidence to reach a verdict." },
    { icon: Database, title: `${countLabel}+ claims`, desc: "A curated, multilingual database of previously fact-checked claims." },
    { icon: Zap, title: "Fast", desc: "Most checks return in a few seconds once the model is warm." },
    { icon: Globe, title: "Multilingual", desc: "Understands claims in English, Hindi, Arabic, Tamil, Spanish, and more." },
  ];
  const retrieveStep = {
    icon: Search, title: "Retrieve evidence",
    desc: `Pinecone finds the closest matches among ${countLabel} indexed claims.`,
  };
  const steps = [STEPS[0], STEPS[1], retrieveStep, STEPS[2], STEPS[3]];

  return (
    <section className="veris-section">
      <p className="veris-eyebrow">About</p>
      <h2 className="veris-section-title">
        Grounded in <em>evidence</em>, not opinion.
      </h2>
      <p className="veris-section-sub" style={{ maxWidth: 640 }}>
        Veris checks a claim against a database of {countLabel} previously fact-checked
        claims and, when nothing close is found, a live web search — then asks an AI
        model to weigh the evidence and explain its reasoning in plain language.
      </p>

      <div
        style={{
          display: "grid", gap: 16, marginTop: 8,
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        {FEATURES.map((f) => (
          <div key={f.title} className="veris-stat-card">
            <span
              style={{
                display: "grid", placeItems: "center", width: 40, height: 40,
                borderRadius: 12, background: "var(--periwinkle-soft)", color: "var(--periwinkle)",
              }}
            >
              <f.icon size={20} />
            </span>
            <h3 style={{ fontFamily: "var(--font-display)", fontSize: 16, fontWeight: 600, margin: "12px 0 4px" }}>
              {f.title}
            </h3>
            <p style={{ fontSize: 13.5, color: "var(--slate)", margin: 0, lineHeight: 1.55 }}>{f.desc}</p>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 56 }}>
        <p className="veris-eyebrow" style={{ fontSize: 20 }}>How it works</p>
        <h2 className="veris-section-title" style={{ fontSize: 32, marginBottom: 24 }}>
          Five steps, start to finish
        </h2>
        <ol
          style={{
            display: "grid", gap: 14, listStyle: "none", padding: 0, margin: 0,
            gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
          }}
        >
          {steps.map((s, i) => (
            <li key={s.title} className="veris-stat-card">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    display: "grid", placeItems: "center", width: 26, height: 26,
                    borderRadius: "50%", background: "var(--ink)", color: "var(--cream)",
                    fontSize: 12.5, fontWeight: 700, flexShrink: 0,
                  }}
                >
                  {i + 1}
                </span>
                <s.icon size={16} color="var(--slate)" />
              </div>
              <h3 style={{ fontFamily: "var(--font-display)", fontSize: 15, fontWeight: 600, margin: "10px 0 4px" }}>
                {s.title}
              </h3>
              <p style={{ fontSize: 13, color: "var(--slate)", margin: 0, lineHeight: 1.5 }}>{s.desc}</p>
            </li>
          ))}
        </ol>
      </div>

      <div style={{ marginTop: 56 }}>
        <p className="veris-eyebrow" style={{ fontSize: 20 }}>Technology</p>
        <h2 className="veris-section-title" style={{ fontSize: 32, marginBottom: 20 }}>
          Under the hood
        </h2>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {STACK.map((t) => (
            <span
              key={t}
              style={{
                border: "1px solid var(--line)", background: "var(--card)",
                borderRadius: 999, padding: "8px 16px", fontSize: 13.5,
                fontWeight: 500, color: "var(--ink-soft)",
              }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 56, maxWidth: 640 }}>
        <p className="veris-eyebrow" style={{ fontSize: 20 }}>What it can't do</p>
        <h2 className="veris-section-title" style={{ fontSize: 32, marginBottom: 16 }}>
          Read this before you trust a verdict
        </h2>
        <p style={{ color: "var(--slate)", fontSize: 15, lineHeight: 1.65, margin: "0 0 14px" }}>
          Veris can be wrong. It's weakest on very recent events, since a claim has to be
          fact-checked and indexed before it can be matched, and on claims that depend on
          an image or video rather than the words themselves.
        </p>
        <p style={{ color: "var(--slate)", fontSize: 15, lineHeight: 1.65, margin: 0 }}>
          A verdict here is a starting point, not a ruling. When sources are listed,
          follow them and read what the fact-checker actually wrote.
        </p>
      </div>
    </section>
  );
}
