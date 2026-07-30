import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { LogIn, LogOut } from "lucide-react";
import useAuth from "../hooks/useAuth";

const LINKS = [
  { to: "/", label: "Home", end: true },
  { to: "/fact-check", label: "Fact Check" },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/about", label: "About" },
];

export default function Navbar() {
  const { user, signOut } = useAuth();
  const [showMenu, setShowMenu] = useState(false);
  const navigate = useNavigate();

  const initial = (user?.username || "?").charAt(0).toUpperCase();

  const handleLogout = async () => {
    await signOut();
    setShowMenu(false);
    navigate("/");
  };

  return (
    <nav className="veris-nav">
      <div className="veris-nav-left">
        <div className="veris-logo-mark">V</div>
        <div className="veris-logo-text">
          <span className="veris-logo-name">Veris</span>
          <span className="veris-logo-tag">Verify. Reason. Trust.</span>
        </div>
      </div>

      <div className="veris-nav-center">
        {LINKS.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) => `veris-nav-link ${isActive ? "veris-active" : ""}`}
          >
            {l.label}
          </NavLink>
        ))}
      </div>

      <div className="veris-nav-right">
        {user ? (
          <div className="veris-user-menu-wrap">
            <button
              className="veris-user-chip"
              onClick={() => setShowMenu((s) => !s)}
              aria-label={`Account menu for ${user.username}`}
            >
              <span className="veris-avatar">{initial}</span>
            </button>
            {showMenu && (
              <>
                <div className="veris-menu-overlay" onClick={() => setShowMenu(false)} />
                <div className="veris-user-dropdown">
                  <div className="veris-dropdown-avatar">{initial}</div>
                  <div className="veris-dropdown-name">{user.username}</div>
                  <div className="veris-dropdown-email">{user.email}</div>
                  <button className="veris-dropdown-logout" onClick={handleLogout}>
                    <LogOut size={15} />
                    Log out
                  </button>
                </div>
              </>
            )}
          </div>
        ) : (
          <>
            <button className="veris-btn-login" onClick={() => navigate("/auth?mode=signin")}>
              <LogIn size={15} />
              Log in
            </button>
            <button className="veris-btn-signup" onClick={() => navigate("/auth?mode=signup")}>
              Sign up
            </button>
          </>
        )}
      </div>
    </nav>
  );
}
