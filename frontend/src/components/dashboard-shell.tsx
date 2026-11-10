import type { ReactNode } from "react";

export function DashboardShell({ children }: { children: ReactNode }) {
  return <div className="container"><aside className="sidebar"><h2>NARA · Emprego</h2><div className="subtitle">DASHBOARD MARANHÃO</div><nav aria-label="Navegação principal"><a className="active" href="/#visao-geral">Visão geral</a><a href="/comparar">Comparar municípios</a><a href="/#ranking">Ranking</a><a href="/#cobertura">Cobertura</a></nav><div className="sidebar-footer">Fonte: IpeaData · Novo Caged</div></aside><main className="main">{children}</main></div>;
}
