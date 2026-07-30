import { useNavigate } from "react-router-dom";
import { ArrowRight, ShieldCheck } from "lucide-react";

export default function Hero() {
  const navigate = useNavigate();

  return (
    <section className="veris-section veris-hero">
      <p className="veris-hero-eyebrow">Grounded in evidence,</p>
      <h1 className="veris-hero-title">
        <span className="veris-line">not opinion.</span>
        <span className="veris-line">Check any</span>
        <span className="veris-line">
          claim
          <span className="veris-hang-tag">
            <ShieldCheck size={12} />
            RAG verified →
          </span>
        </span>
      </h1>
      <div className="veris-hero-bottom">
        <div className="veris-hero-sub-block">
          <p>
            Veris retrieves current, credible sources for any claim circulating on
            social media, then returns a verdict, a confidence score, and the
            evidence behind it.
          </p>
          <button className="veris-btn-primary" onClick={() => navigate("/fact-check")}>
            Check a claim <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </section>
  );
}
