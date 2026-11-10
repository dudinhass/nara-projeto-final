const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000/api/v1";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

export const api = {
  totaisUf: (params: { inicio?: string; fim?: string } = {}) => {
    const query = new URLSearchParams(); if (params.inicio) query.set("inicio", params.inicio); if (params.fim) query.set("fim", params.fim);
    return get<TotalsUf>(`/totais/uf?${query.toString()}`);
  },
  ranking: (params: RankingParams = {}) => {
    const query = new URLSearchParams({ indicador: params.indicador ?? "saldo", limite: String(params.limite ?? 10) });
    if (params.inicio) query.set("inicio", params.inicio); if (params.fim) query.set("fim", params.fim);
    return get<RankingRow[]>(`/ranking?${query.toString()}`);
  },
  municipios: (limite = 217) => get<MunicipiosPage>(`/municipios?limite=${limite}`),
  mensal: (codIbge: string, params: { inicio?: string; fim?: string } = {}) => {
    const query = new URLSearchParams(); if (params.inicio) query.set("inicio", params.inicio); if (params.fim) query.set("fim", params.fim);
    return get<MonthlyRow[]>(`/municipios/${codIbge}/mensal?${query.toString()}`);
  },
};

export type TotalsUf = { inicio: string; fim: string; metodologia: string; admissoes_uf: number; desligamentos_uf: number; saldo_uf: number; meses: number; mensal: MonthlyUfRow[] };
export type MonthlyUfRow = { data_referencia: string; admissoes_uf: number | null; desligamentos_uf: number | null; saldo_uf: number | null; municipios_com_observacao: number | null };
export type MonthlyRow = { data_referencia: string; admissoes: number | null; desligamentos: number | null; saldo: number | null; situacao: string };
export type RankingParams = { indicador?: "admissoes" | "desligamentos" | "saldo"; inicio?: string; fim?: string; limite?: number };
export type RankingRow = { posicao: number; cod_ibge: string; municipio: string; admissoes: number | null; desligamentos: number | null; saldo: number | null; meses_com_saldo: number };
export type Municipality = { cod_ibge: string; nome: string; uf: string; capital: boolean; area_km2: string | null };
export type MunicipiosPage = { items: Municipality[]; next_cursor: string | null; has_more: boolean };
