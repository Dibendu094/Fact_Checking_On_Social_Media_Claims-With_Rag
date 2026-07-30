import { useEffect, useRef, useState } from "react";

import { useNavigate, useSearchParams } from "react-router-dom";
import AuthCard from "../components/AuthCard";
import useAuth from "../hooks/useAuth";

export default function Auth() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const paramMode = params.get("mode");
  const [mode, setMode] = useState(paramMode || "signin");

  const suppressRedirectRef = useRef(false);

  useEffect(() => {
    if (!paramMode) return;
    setMode(paramMode);
  }, [paramMode]);

  useEffect(() => {
    if (suppressRedirectRef.current) return;
    if (user && mode !== "forgot") {
      navigate("/", { replace: true });
    }
  }, [user, mode, navigate]);

  return (
    <section className="veris-section">
      <AuthCard
        mode={mode}
        setMode={setMode}
        suppressRedirectRef={suppressRedirectRef}
        onSignedIn={() => navigate("/", { replace: true })}
      />
    </section>
  );
}
