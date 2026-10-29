// Inline icon set (no icon dependency). Stroke-based, inherits currentColor.
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 18, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>
      {children}
    </svg>
  );
}

export const IconBolt = (p: IconProps) => (
  <Icon {...p}><path d="M13 2 4.5 13.5H11l-1 8.5L19.5 10H13z" /></Icon>
);

export const IconDashboard = (p: IconProps) => (
  <Icon {...p}><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></Icon>
);

export const IconCalendar = (p: IconProps) => (
  <Icon {...p}><rect x="3" y="4.5" width="18" height="16" rx="2" /><path d="M16 2.5v4M8 2.5v4M3 10h18" />
    <path d="M8 14h.01M12 14h.01M16 14h.01M8 17.5h.01M12 17.5h.01" /></Icon>
);

export const IconHistory = (p: IconProps) => (
  <Icon {...p}><path d="M3 12a9 9 0 1 0 2.6-6.4" /><path d="M3 4v5h5" /><path d="M12 7.5V12l3 2" /></Icon>
);

export const IconSearch = (p: IconProps) => (
  <Icon {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Icon>
);

export const IconRoute = (p: IconProps) => (
  <Icon {...p}><circle cx="6" cy="19" r="2.5" /><circle cx="18" cy="5" r="2.5" />
    <path d="M8.5 19H14a4 4 0 0 0 0-8H9a4 4 0 0 1 0-8h6.5" /></Icon>
);

export const IconNetwork = (p: IconProps) => (
  <Icon {...p}><rect x="9" y="2.5" width="6" height="5" rx="1" /><rect x="2.5" y="16.5" width="6" height="5" rx="1" />
    <rect x="15.5" y="16.5" width="6" height="5" rx="1" /><path d="M12 7.5v4M5.5 16.5v-2.5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v2.5" /></Icon>
);

export const IconDatabase = (p: IconProps) => (
  <Icon {...p}><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    <path d="M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></Icon>
);

export const IconShield = (p: IconProps) => (
  <Icon {...p}><path d="M12 2.5 4.5 5.5v6c0 4.6 3.2 8.4 7.5 10 4.3-1.6 7.5-5.4 7.5-10v-6z" />
    <path d="m9 12 2 2 4-4" /></Icon>
);

export const IconActivity = (p: IconProps) => (
  <Icon {...p}><path d="M2.5 12h4l2.5-7 5 14 2.5-7h5" /></Icon>
);

export const IconSun = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Icon>
);

export const IconMoon = (p: IconProps) => (
  <Icon {...p}><path d="M20.5 14.2A8.6 8.6 0 0 1 9.8 3.5 8.6 8.6 0 1 0 20.5 14.2z" /></Icon>
);

export const IconMonitor = (p: IconProps) => (
  <Icon {...p}><rect x="2.5" y="3.5" width="19" height="13" rx="2" /><path d="M8.5 20.5h7M12 16.5v4" /></Icon>
);

export const IconLogout = (p: IconProps) => (
  <Icon {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5M21 12H9" /></Icon>
);

export const IconKey = (p: IconProps) => (
  <Icon {...p}><circle cx="7.5" cy="15.5" r="4.5" /><path d="m10.8 12.2 9.7-9.7M17.5 4.5l2 2M14.5 7.5l2 2" /></Icon>
);

export const IconEye = (p: IconProps) => (
  <Icon {...p}><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" /><circle cx="12" cy="12" r="2.75" /></Icon>
);

export const IconEyeOff = (p: IconProps) => (
  <Icon {...p}><path d="M10.6 5.7A9.9 9.9 0 0 1 12 5.5c6.4 0 10 6.5 10 6.5a18 18 0 0 1-2.4 3.3" />
    <path d="M6.3 7.9A18 18 0 0 0 2 12s3.6 6.5 10 6.5c1.4 0 2.6-.3 3.8-.8" /><path d="m3 3 18 18" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /></Icon>
);

export const IconMenu = (p: IconProps) => (
  <Icon {...p}><path d="M3.5 6.5h17M3.5 12h17M3.5 17.5h17" /></Icon>
);

export const IconClose = (p: IconProps) => (
  <Icon {...p}><path d="M6 6l12 12M18 6 6 18" /></Icon>
);

export const IconPlus = (p: IconProps) => (
  <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>
);

export const IconPlay = (p: IconProps) => (
  <Icon {...p}><path d="M7 4.5v15l12-7.5z" /></Icon>
);

export const IconCheck = (p: IconProps) => (
  <Icon {...p}><path d="m4.5 12.5 5 5 10-11" /></Icon>
);

export const IconAlert = (p: IconProps) => (
  <Icon {...p}><path d="M10.3 3.9 2.5 17.2A1.9 1.9 0 0 0 4.2 20h15.6a1.9 1.9 0 0 0 1.7-2.8L13.7 3.9a1.9 1.9 0 0 0-3.4 0z" />
    <path d="M12 9v4M12 16.5h.01" /></Icon>
);

export const IconInfo = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="9.5" /><path d="M12 11v5.5M12 7.5h.01" /></Icon>
);

export const IconDownload = (p: IconProps) => (
  <Icon {...p}><path d="M12 3v12M7 10l5 5 5-5" /><path d="M4 19.5h16" /></Icon>
);

export const IconUpload = (p: IconProps) => (
  <Icon {...p}><path d="M12 15V3M7 8l5-5 5 5" /><path d="M4 19.5h16" /></Icon>
);

export const IconChevronDown = (p: IconProps) => (
  <Icon {...p}><path d="m6 9 6 6 6-6" /></Icon>
);

export const IconArrowRight = (p: IconProps) => (
  <Icon {...p}><path d="M4 12h16M14 6l6 6-6 6" /></Icon>
);

export const IconLock = (p: IconProps) => (
  <Icon {...p}><rect x="4.5" y="10" width="15" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></Icon>
);

export const IconUser = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="8" r="4" /><path d="M4.5 21a7.5 7.5 0 0 1 15 0" /></Icon>
);

export const IconChart = (p: IconProps) => (
  <Icon {...p}><path d="M4 20V4M4 20h16" /><path d="M8 16v-5M12 16V7M16 16v-8M20 16v-3" /></Icon>
);

export const IconClock = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></Icon>
);

export const IconLayers = (p: IconProps) => (
  <Icon {...p}><path d="m12 3 9 5-9 5-9-5z" /><path d="m3 12.5 9 5 9-5M3 17l9 5 9-5" /></Icon>
);
