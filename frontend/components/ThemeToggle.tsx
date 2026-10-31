"use client";
// Dark mode: follows the OS by default; an explicit choice is stored in
// localStorage (gr-theme) and applied as data-theme on <html>, which wins over
// the prefers-color-scheme media query.
import { useEffect, useState } from "react";
import { IconMoon, IconMonitor, IconSun } from "./icons";

type Mode = "auto" | "dark" | "light";

function apply(mode: Mode) {
  const el = document.documentElement;
  if (mode === "auto") {
    localStorage.removeItem("gr-theme");
    el.removeAttribute("data-theme");
  } else {
    localStorage.setItem("gr-theme", mode);
    el.dataset.theme = mode;
  }
}

export default function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("auto");

  useEffect(() => {
    const stored = localStorage.getItem("gr-theme");
    setMode(stored === "light" || stored === "dark" ? stored : "auto");
  }, []);

  function cycle() {
    const next: Mode = mode === "auto" ? "dark" : mode === "dark" ? "light" : "auto";
    setMode(next);
    apply(next);
  }

  const Icon = mode === "auto" ? IconMonitor : mode === "dark" ? IconMoon : IconSun;
  const label = mode === "auto" ? "Theme: follow system" : `Theme: ${mode}`;

  return (
    <button type="button" onClick={cycle} className="icon-btn" title={label} aria-label={label}>
      <Icon size={17} />
    </button>
  );
}
