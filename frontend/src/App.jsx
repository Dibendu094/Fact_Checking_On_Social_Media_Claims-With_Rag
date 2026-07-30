import { Route, Routes } from "react-router-dom";
import Navbar from "./components/Navbar";
import Hero from "./components/Hero";
import FactCheck from "./pages/FactCheck";
import Dashboard from "./pages/Dashboard";
import Auth from "./pages/Auth";
import About from "./pages/About";

export default function App() {
  return (
    <div className="veris">
      <Navbar />
      <main>
        <Routes>
          <Route path="/" element={<Hero />} />
          <Route path="/fact-check" element={<FactCheck />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/auth" element={<Auth />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<Hero />} />
        </Routes>
      </main>
    </div>
  );
}
