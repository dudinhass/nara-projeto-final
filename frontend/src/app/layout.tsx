import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Emprego Maranhão", description: "Dashboard de admissões, desligamentos e saldo do emprego formal." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="pt-BR"><body>{children}</body></html>;
}
