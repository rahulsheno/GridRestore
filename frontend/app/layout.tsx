import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GridRestore · Restoration planning",
  description: "Resource-constrained power restoration planner",
};

// Applied before first paint so the chosen theme never flashes.
// app/layout.tsx
const themeBootstrap = `
try {
  var m = localStorage.getItem("gr-theme");
  if (m === "dark" || (!m && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.documentElement.classList.add("dark");
  }
} catch (e) {}
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: themeBootstrap }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}