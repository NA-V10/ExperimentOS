import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "ExperimentOS",
  description: "AI that doesn't just answer questions. It runs experiments to find out.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The theme toggle sets data-theme on <html> after load.
    <html lang="en" suppressHydrationWarning>
      {/* Browser extensions (Grammarly, password managers, …) inject attributes into <body>
          before React hydrates; that is harmless and must not raise a hydration error. */}
      <body suppressHydrationWarning>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
