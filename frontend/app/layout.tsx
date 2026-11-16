import type {Metadata} from "next";
import type {ReactNode} from "react";
import "reactflow/dist/style.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Swarm: a clearer view of your code",
  description: "Focused repository reviews with findings grounded in source and actionable fixes.",
};

export default function RootLayout({children}: Readonly<{children: ReactNode}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
