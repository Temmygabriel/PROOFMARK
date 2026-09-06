import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Providers } from "./providers";
import "./globals.css";

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist-src",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono-src",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Proofmark — Trust Infrastructure for AI Agents",
  description:
    "Every AI agent job, verified on-chain. Buyers get covered if delivery " +
    "fails. Platforms become trusted. Underwriters earn yield. Powered by " +
    "GenLayer validator consensus.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${geist.variable} ${geistMono.variable}`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
