import type { Metadata } from "next";
import { Host_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { WalletContextProvider } from "@/providers/WalletContextProvider";
import AuthRedirectListener from "@/components/AuthRedirectListener";
import { ToastProvider } from "@/components/ToastProvider";

const hostGrotesk = Host_Grotesk({
  variable: "--font-host-grotesk",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Etornie | Modern IP Custody Platform",
  description: "Modern intellectual property custody. Built for the next era of assets.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${hostGrotesk.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <WalletContextProvider>
          <ToastProvider>
            <AuthRedirectListener />
            {children}
          </ToastProvider>
        </WalletContextProvider>
      </body>
    </html>
  );
}
