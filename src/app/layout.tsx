import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Codenames — Four seats, one board",
  description: "Play Codenames with friends or watch bots take a turn. A minimal four-seat game.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#f8f7f3" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
