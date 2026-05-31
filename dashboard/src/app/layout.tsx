import type { Metadata } from "next";
import { Funnel_Display } from "next/font/google";
import "./globals.css";
import { WalletContextProvider } from "@/providers/WalletContextProvider";
import AuthRedirectListener from "@/components/AuthRedirectListener";
import { ToastProvider } from "@/components/ToastProvider";

const funnelDisplay = Funnel_Display({
  variable: "--font-funnel-display",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700", "800"],
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
      className={`${funnelDisplay.variable} h-full antialiased`}
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
