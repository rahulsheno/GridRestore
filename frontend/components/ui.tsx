"use client";
// Small presentational primitives. Kept dumb on purpose: they only map props to
// the design-system classes in globals.css, so views stay readable.
import type { ReactNode } from "react";
import { IconAlert, IconCheck, IconInfo } from "./icons";

export function PageHead({ title, sub, actions }: { title: string; sub?: string; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1 className="page-title">{title}</h1>
        {sub && <p className="page-sub">{sub}</p>}
      </div>
      {actions && <div className="row gap-8">{actions}</div>}
    </div>
  );
}

export function Card({ title, sub, actions, children, flush, className = "" }: {
  title?: string; sub?: string; actions?: ReactNode; children: ReactNode; flush?: boolean; className?: string;
}) {
  return (
    <section className={`card ${className}`.trim()}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {sub && <p className="card-sub">{sub}</p>}
          </div>
          {actions && <div className="row gap-8">{actions}</div>}
        </div>
      )}
      <div className={flush ? "card-body tight" : "card-body"}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-top">
        <span className="stat-label">{label}</span>
        {icon && <span className="stat-ico">{icon}</span>}
      </div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Field({ label, hint, htmlFor, children }: {
  label: string; hint?: string; htmlFor?: string; children: ReactNode;
}) {
  return (
    <label className="field" htmlFor={htmlFor}>
      <span className="label">{label}</span>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

export function Alert({ kind = "info", children }: { kind?: "info" | "danger" | "success" | "warn"; children: ReactNode }) {
  const Icon = kind === "danger" || kind === "warn" ? IconAlert : kind === "success" ? IconCheck : IconInfo;
  return (
    <div className={`alert alert-${kind}`} role={kind === "danger" ? "alert" : "status"}>
      <span className="alert-icon"><Icon size={16} /></span>
      <div>{children}</div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon && <span className="empty-icon">{icon}</span>}
      <strong>{title}</strong>
      {children && <div className="small">{children}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row gap-8 small muted" role="status" aria-live="polite">
      <span className="spinner" /> {label ?? "Loading…"}
    </span>
  );
}
