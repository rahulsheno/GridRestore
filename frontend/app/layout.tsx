import type { Metadata } from "next";
export const metadata: Metadata = { title: "GridRestore", description: "Resource-constrained power restoration planner" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body style={{margin:0,fontFamily:"Inter,system-ui,sans-serif",background:"#f4f6f8",color:"#14202b"}}>{children}</body></html>;
}
