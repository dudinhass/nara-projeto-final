"""Auditoria de procedência: comprova, contra o IpeaData, de onde vêm os registros do banco.

Para cada série configurada, a auditoria:

1. confere a **série**: a fonte de obtenção é autorizada e os metadados publicados agora pelo
   IpeaData (``Metadados('X')``) correspondem ao cadastro (código, nome, base, periodicidade, unidade);
2. confere cada **arquivo bruto** (snapshot) que originou observações: existe, o SHA-256 confere, e a
   URL é do IpeaData **e consulta exatamente aquela série**;
3. compara o banco com o **arquivo bruto** preservado (nada foi alterado depois da coleta);
4. baixa de novo a resposta oficial (``ValoresSerie``) e compara **cada observação** do banco com
   ela (mesmo nível territorial, território, mês e valor);
5. confere por amostra, lendo os campos brutos da resposta, sem passar pelo código de normalização.

Só é ``validado_ipeadata`` a observação aprovada em 1 a 4. Se uma verificação não puder ser feita
(IpeaData fora do ar), a série fica **sem alteração** e a auditoria termina ``incompleta``:
nunca se declara validado o que não foi comprovado. Nada é apagado; os status só mudam.
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from sqlalchemy import Engine, text

from coleta.armazenamento import salvar_json, sha256_arquivo
from coleta.checkpoint import agora_utc
from coleta.config import MUNICIPIOS_TESTE, SERIES, Diretorios
from coleta.ipea_client import IpeaAPIError
from coleta.leitor_odata import DocumentoOData, lotes_de_paginas
from coleta.procedencia import (
    codigo_na_url,
    comparar_metadados,
    host_autorizado,
    url_corresponde_a_serie,
    url_territorios_valida,
    verificar_metadados,
)
from coleta.transformacao import ContextoSerie, processar

logger = logging.getLogger(__name__)

VALIDADO, NAO_VALIDADO, INCOMPATIVEL = "validado_ipeadata", "nao_validado", "incompativel"
NIVEIS_BRUTOS = {"Municípios": "municipio", "Estados": "estado", "Brasil": "brasil", "": "brasil"}


class ClienteIpea(Protocol):
    def resposta_metadados(self, codigo: str) -> Any: ...
    def resposta_territorios(self, codigo_uf: str) -> Any: ...
    def resposta_estado(self, codigo_uf: str) -> Any: ...
    def caminho_valores(self, codigo: str) -> str: ...
    def baixar_para_arquivo(self, caminho: str, destino: Path, params: dict[str, str] | None = None) -> Any: ...


# --- Comparações puras (testáveis sem rede nem banco) ------------------------------------

def chaves_de_observacoes(obs: pd.DataFrame) -> pd.DataFrame:
    """Observações normalizadas pelo pipeline -> (nivel, cod, data, valor), no mesmo formato do banco."""
    if obs.empty:
        return pd.DataFrame({"nivel": [], "cod": [], "data": [], "valor": []})
    cod = obs["cod_ibge"].where(obs["nivel_territorial"] != "brasil", "BR")
    return pd.DataFrame({
        "nivel": obs["nivel_territorial"].astype(str), "cod": cod.astype(str),
        "data": obs["data_referencia"].dt.date, "valor": obs["valor"].astype("int64"),
    })


@dataclass
class Comparacao:
    ids_iguais: set[int]
    valor_diferente: list[dict[str, Any]]
    somente_banco: list[dict[str, Any]]
    somente_fonte: int
    exemplos_somente_fonte: list[dict[str, Any]]

    def resumo(self) -> dict[str, Any]:
        return {"iguais": len(self.ids_iguais), "valor_diferente": len(self.valor_diferente),
                "somente_no_banco": len(self.somente_banco), "somente_na_fonte": self.somente_fonte}


def comparar_observacoes(banco: pd.DataFrame, fonte: pd.DataFrame) -> Comparacao:
    """``banco`` tem id, nivel, cod, data, valor; ``fonte`` tem nivel, cod, data, valor."""
    chave = ["nivel", "cod", "data"]
    m = banco[["id", *chave, "valor"]].merge(fonte[[*chave, "valor"]], on=chave, how="outer",
                                              suffixes=("_banco", "_fonte"), indicator=True)
    ambos = m[m["_merge"] == "both"]
    iguais = ambos[ambos["valor_banco"] == ambos["valor_fonte"]]
    diferentes = ambos[ambos["valor_banco"] != ambos["valor_fonte"]]
    so_banco, so_fonte = m[m["_merge"] == "left_only"], m[m["_merge"] == "right_only"]

    def amostra(d: pd.DataFrame, colunas: list[str]) -> list[dict[str, Any]]:
        """Até 10 exemplos legíveis; o merge externo converte inteiros em float, então volta-se a Int64."""
        d = d.head(10).copy()
        for c in colunas:
            if c == "id" or c.startswith("valor"):
                d[c] = d[c].astype("Int64")
        return d[colunas].astype(str).to_dict("records")

    return Comparacao(
        ids_iguais=set(iguais["id"].astype(int)),
        valor_diferente=amostra(diferentes, ["id", *chave, "valor_banco", "valor_fonte"]) if len(diferentes) else [],
        somente_banco=[{"id": int(i)} for i in so_banco["id"]],
        somente_fonte=len(so_fonte),
        exemplos_somente_fonte=amostra(so_fonte, [*chave, "valor_fonte"]) if len(so_fonte) else [],
    )


def chave_do_banco(nivel_bruto: str | None, territorio: str | None) -> tuple[str, str] | None:
    """Mapeia (NIVNOME, TERCODIGO) da resposta bruta para (nivel, cod) do banco; ``None`` se fora do escopo."""
    nivel = NIVEIS_BRUTOS.get((nivel_bruto or "").strip())
    if nivel is None:
        return None
    return nivel, ("BR" if nivel == "brasil" else str(territorio or "").strip())


def datas_de_amostra(inicio: date, fim: date) -> list[date]:
    meio = date(inicio.year + (fim.year - inicio.year) // 2, 6, 1)
    return sorted({inicio, min(max(meio, inicio), fim), fim})


# --- Auditoria ---------------------------------------------------------------------------

def _evidencia_resposta(resposta: Any, rotulo: str) -> dict[str, Any]:
    import hashlib

    return {"rotulo": rotulo, "url": resposta.url, "status_http": resposta.status,
            "bytes": len(resposta.conteudo), "sha256": hashlib.sha256(resposta.conteudo).hexdigest(),
            "consultado_em_utc": resposta.coletado_em, "duracao_s": resposta.duracao_s}


def _evidencia_download(d: Any, rotulo: str) -> dict[str, Any]:
    return {"rotulo": rotulo, "url": d.url, "status_http": d.status, "bytes": d.bytes, "sha256": d.sha256,
            "consultado_em_utc": d.coletado_em, "duracao_s": d.duracao_s}


class Auditor:
    def __init__(
        self, engine: Engine, dirs: Diretorios, cliente: ClienteIpea, cod_uf: str = "21", uf_sigla: str = "MA",
        tamanho_lote: int = 50_000, series: list[str] | None = None,
    ) -> None:
        self.engine, self.dirs, self.cliente = engine, dirs, cliente
        self.cod_uf, self.uf_sigla, self.tamanho_lote = cod_uf, uf_sigla, tamanho_lote
        self.series = series or list(SERIES)
        self.evidencias: list[dict[str, Any]] = []
        self.auditoria_id = 0

    # SQL auxiliar --------------------------------------------------------------------
    def _linhas(self, sql: str, **p: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as con:
            return [dict(l) for l in con.execute(text(sql), p).mappings()]

    def executar(self) -> dict[str, Any]:
        inicio = time.monotonic()
        with self.engine.begin() as con:
            self.auditoria_id = con.execute(text(
                "INSERT INTO auditorias_procedencia (status) VALUES ('em_andamento') RETURNING id")).scalar_one()
        resultado: dict[str, Any] = {"auditoria_id": self.auditoria_id, "iniciada_em_utc": agora_utc(), "series": {}}
        try:
            resultado["territorios"] = self._auditar_territorios()
            for codigo in self.series:
                resultado["series"][codigo] = self._auditar_serie(codigo)
        except BaseException as exc:
            self._finalizar(resultado, "falhou", inicio, f"{type(exc).__name__}: {exc}")
            raise
        incompletas = [c for c, r in resultado["series"].items() if r["situacao"] == "nao_concluida"]
        if resultado["territorios"]["situacao"] == "nao_concluida":
            incompletas.append("territorios")
        self._finalizar(resultado, "incompleta" if incompletas else "concluida", inicio)
        return resultado

    def _finalizar(self, resultado: dict[str, Any], status: str, inicio: float, erro: str | None = None) -> None:
        resultado.update(status=status, duracao_s=round(time.monotonic() - inicio, 1), evidencias_http=self.evidencias,
                         finalizada_em_utc=agora_utc(), erro=erro)
        resumo = {"series": {c: {k: v for k, v in r.items() if k in ("situacao", "registros", "validados", "nao_validados",
                                                                     "incompativeis")} for c, r in resultado["series"].items()},
                  "territorios": (resultado.get("territorios") or {}).get("situacao"), "erro": erro}
        import json

        with self.engine.begin() as con:
            con.execute(text("UPDATE auditorias_procedencia SET status = :s, finalizada_em = now(), "
                             "resumo = CAST(:r AS jsonb) WHERE id = :i"),
                        {"s": status, "r": json.dumps(resumo, default=str), "i": self.auditoria_id})
        salvar_json(resultado, self.dirs.reports / "auditoria_procedencia.json")

    # Territórios ------------------------------------------------------------------------
    def _auditar_territorios(self) -> dict[str, Any]:
        info: dict[str, Any] = {"situacao": "concluida", "problemas": []}
        try:
            resposta = self.cliente.resposta_territorios(self.cod_uf)
            estado = self.cliente.resposta_estado(self.cod_uf)
        except IpeaAPIError as exc:
            return {"situacao": "nao_concluida", "problemas": [f"IpeaData indisponível: {exc}"]}
        self.evidencias.append(_evidencia_resposta(resposta, "Territorios - municípios da UF"))
        self.evidencias.append(_evidencia_resposta(estado, "Territorios - UF"))
        info["uf"] = estado.valores[0] if estado.valores else None
        vivo = {str(r["TERCODIGO"]): r for r in resposta.valores}
        banco = {m["cod_ibge"]: m for m in self._linhas(
            "SELECT cod_ibge, nome, capital, area_km2, snapshot_id FROM municipios WHERE uf = :uf", uf=self.uf_sigla)}

        def igual(m: dict[str, Any], v: dict[str, Any]) -> bool:
            area_ok = (m["area_km2"] is None and v.get("TERAREA") is None) or (
                m["area_km2"] is not None and v.get("TERAREA") is not None
                and round(float(v["TERAREA"]), 2) == float(m["area_km2"]))
            return m["nome"] == v.get("TERNOME") and m["capital"] == v.get("TERCAPITAL") and area_ok

        iguais = {c for c, m in banco.items() if c in vivo and igual(m, vivo[c])}
        info.update(municipios_no_banco=len(banco), municipios_no_ipeadata=len(vivo), iguais=len(iguais),
                    ausentes_no_ipeadata=sorted(set(banco) - set(vivo)), somente_no_ipeadata=sorted(set(vivo) - set(banco)),
                    divergentes=sorted(c for c in banco if c in vivo and c not in iguais)[:20])

        # Snapshots do cadastro: o arquivo bruto precisa existir, conferir o hash e ter URL do IpeaData.
        # Cada município é então comparado com o bruto E com a resposta atual; um município que mudou
        # não reprova os demais.
        snaps = self._linhas("SELECT id, arquivo_bruto, arquivos, url, sha256 FROM snapshots_origem WHERE tipo = 'territorios'")
        ok_snap: set[int] = set()
        no_bruto: dict[int, set[str]] = {}
        for sn in snaps:
            problemas = self._problemas_arquivo(sn, url_valida=url_territorios_valida(sn["url"]))
            if problemas:
                info["problemas"].extend(f"snapshot {sn['id']}: {p}" for p in problemas)
                continue
            ok_snap.add(sn["id"])
            guardado = {str(r["TERCODIGO"]): r for r in DocumentoOData(self.dirs.raiz / sn["arquivo_bruto"]).registros()}
            no_bruto[sn["id"]] = {c for c, m in banco.items() if m["snapshot_id"] == sn["id"] and c in guardado
                                  and igual(m, guardado[c])}
        validados = sorted(c for c in iguais if banco[c]["snapshot_id"] in ok_snap
                           and c in no_bruto.get(banco[c]["snapshot_id"], set()))
        with self.engine.begin() as con:
            con.execute(text("UPDATE snapshots_origem SET status_procedencia = CASE WHEN id = ANY(:ok) THEN 'validado_ipeadata' "
                             "ELSE 'nao_validado' END, verificado_em = now(), auditoria_id = :a WHERE tipo = 'territorios'"),
                        {"ok": sorted(ok_snap), "a": self.auditoria_id})
            con.execute(text("UPDATE municipios SET status_procedencia = CASE WHEN cod_ibge = ANY(:ok) THEN 'validado_ipeadata' "
                             "ELSE 'nao_validado' END, procedencia_verificada_em = now() WHERE uf = :uf"),
                        {"ok": validados, "uf": self.uf_sigla})
        info.update(validados=len(validados), nao_validados=len(banco) - len(validados), snapshots_ok=len(ok_snap))
        return info

    def _problemas_arquivo(self, sn: dict[str, Any], url_valida: bool) -> list[str]:
        problemas = []
        if not url_valida:
            problemas.append(f"URL não corresponde ao esperado do IpeaData: {sn['url']}")
        caminho = self.dirs.raiz / sn["arquivo_bruto"]
        if not caminho.exists():
            problemas.append("arquivo bruto ausente")
        elif sha256_arquivo(caminho, descomprimir=True) != sn["sha256"]:
            problemas.append("SHA-256 do arquivo bruto difere do registrado na coleta")
        return problemas

    # Séries ----------------------------------------------------------------------------
    def _auditar_serie(self, codigo: str) -> dict[str, Any]:
        cfg = SERIES[codigo]
        linhas = self._linhas(
            "SELECT s.id, s.nome, s.periodicidade, s.unidade, s.base_ipeadata, s.serie_atualizada_em, f.autorizada_para_coleta "
            "FROM series_indicadores s JOIN fontes_dados f ON f.id = s.fonte_id WHERE s.codigo = :c", c=codigo)
        if not linhas:
            return {"situacao": "ausente_no_banco", "registros": 0, "problemas": ["série não cadastrada no banco"]}
        s = linhas[0]
        info: dict[str, Any] = {"situacao": "concluida", "problemas": [], "escopo": cfg.escopo, "metodologia": cfg.metodologia}

        # 1) Série e metadados no IpeaData ----------------------------------------------
        try:
            meta_resp = self.cliente.resposta_metadados(codigo)
        except IpeaAPIError as exc:
            return {**info, "situacao": "nao_concluida", "problemas": [f"metadados indisponíveis: {exc}"]}
        self.evidencias.append(_evidencia_resposta(meta_resp, f"Metadados('{codigo}')"))
        meta = meta_resp.valores[0] if meta_resp.valores else None
        problemas_meta = verificar_metadados(cfg, meta)
        if meta and codigo_na_url(meta_resp.url, "metadados") != codigo:
            problemas_meta.append("URL de metadados não corresponde à série")
        diferencas = comparar_metadados(s, meta) if meta else {}
        serie_ok = bool(s["autorizada_para_coleta"]) and not problemas_meta and not diferencas
        info["metadados"] = {
            "url": meta_resp.url, "problemas": problemas_meta, "diferencas_banco_vs_ipeadata": diferencas,
            "serie_atualizada_no_ipeadata": (meta or {}).get("SERATUALIZACAO"),
            "fonte_original_declarada": (meta or {}).get("FNTSIGLA"), "base": (meta or {}).get("BASNOME"),
            "periodicidade": (meta or {}).get("PERNOME"), "unidade": (meta or {}).get("UNINOME"),
            "nome": (meta or {}).get("SERNOME"),
        }
        info["fonte_autorizada"] = bool(s["autorizada_para_coleta"])

        # 2) Registros do banco e snapshots -----------------------------------------------
        banco = pd.DataFrame(self._linhas(
            "SELECT id, nivel_territorial AS nivel, cod_territorio AS cod, data_referencia AS data, valor, snapshot_id "
            "FROM registros_emprego WHERE serie_id = :s", s=s["id"]))
        info["registros"] = len(banco)
        snaps = self._linhas("SELECT id, arquivo_bruto, arquivos, url, sha256 FROM snapshots_origem "
                             "WHERE tipo = 'serie' AND serie_codigo = :c", c=codigo)
        municipios = {m["cod_ibge"]: m["nome"] for m in self._linhas("SELECT cod_ibge, nome FROM municipios")}

        def contexto(arquivo: str) -> ContextoSerie:
            return ContextoSerie(cfg, meta or {}, self.uf_sigla, self.cod_uf, municipios, "", "auditoria", arquivo)

        # 3) Resposta oficial ao vivo ------------------------------------------------------
        with tempfile.TemporaryDirectory(prefix="auditoria_ipea_") as tmp:
            destino = Path(tmp) / f"{codigo}.json.gz"
            try:
                download = self.cliente.baixar_para_arquivo(self.cliente.caminho_valores(codigo), destino)
            except IpeaAPIError as exc:
                return {**info, "situacao": "nao_concluida", "problemas": [f"resposta oficial indisponível: {exc}"]}
            self.evidencias.append(_evidencia_download(download, f"ValoresSerie('{codigo}')"))
            documento = DocumentoOData(destino)
            documento.validar()
            vivo = processar(lotes_de_paginas([destino], self.tamanho_lote), contexto(download.url))
            vivo_chaves = chaves_de_observacoes(vivo.observacoes)
            amostras = self._amostras(codigo, destino, banco, vivo_chaves)
            info["resposta_oficial"] = {
                "url": download.url, "status_http": download.status, "sha256": download.sha256, "bytes": download.bytes,
                "registros_na_resposta": vivo.estatisticas["registros_lidos"],
                "por_nivel": vivo.estatisticas["por_nivel_original"], "observacoes_no_escopo": len(vivo_chaves),
                "rejeitados": vivo.estatisticas["rejeitados"], "disponibilidade": vivo.estatisticas["disponibilidade"],
            }
        contra_vivo = comparar_observacoes(banco, vivo_chaves) if len(banco) else comparar_observacoes(
            pd.DataFrame({"id": [], "nivel": [], "cod": [], "data": [], "valor": []}), vivo_chaves)
        info["banco_vs_resposta_oficial"] = contra_vivo.resumo()
        info["exemplos_valor_diferente"] = contra_vivo.valor_diferente
        info["exemplos_somente_na_fonte"] = contra_vivo.exemplos_somente_fonte
        info["amostras"] = amostras

        # 4) Arquivos brutos preservados × banco -----------------------------------------------
        ok_raw: set[int] = set()
        estado_snap: dict[int, dict[str, Any]] = {}
        for sn in snaps:
            vinculados = banco[banco["snapshot_id"] == sn["id"]] if len(banco) else banco
            problemas = self._problemas_arquivo(sn, url_valida=url_corresponde_a_serie(sn["url"], codigo))
            # Incompatível = comprovadamente fora do IpeaData (host não autorizado). URL do IpeaData que
            # aponta para outra série é só "não validado": a origem é autorizada, a correspondência não.
            incompat = not host_autorizado(sn["url"])
            comp = None
            if not problemas and len(vinculados):
                arquivos = [self.dirs.raiz / a for a in (sn["arquivos"] or [sn["arquivo_bruto"]])]
                bruto = processar(lotes_de_paginas(arquivos, self.tamanho_lote), contexto(sn["arquivo_bruto"]))
                comp = comparar_observacoes(vinculados, chaves_de_observacoes(bruto.observacoes))
                ok_raw |= comp.ids_iguais
            estado_snap[sn["id"]] = {
                "arquivo_bruto": sn["arquivo_bruto"], "url": sn["url"], "sha256": sn["sha256"], "problemas": problemas,
                "ok": not problemas and serie_ok, "incompativel": incompat,
                "registros_vinculados": len(vinculados), "bruto_vs_banco": comp.resumo() if comp else None,
            }
        info["snapshots"] = list(estado_snap.values())

        # 5) Classificação ----------------------------------------------------------------------
        ids_validos, ids_incompat, motivos = self._classificar(
            banco, estado_snap, ok_raw, contra_vivo.ids_iguais, serie_ok, bool(s["autorizada_para_coleta"]))
        info.update(validados=len(ids_validos), incompativeis=len(ids_incompat),
                    nao_validados=len(banco) - len(ids_validos) - len(ids_incompat), motivos_nao_validado=motivos)
        self._gravar_serie(s["id"], meta, meta_resp.url, serie_ok, bool(s["autorizada_para_coleta"]), banco,
                           estado_snap, ids_validos, ids_incompat, info)
        return info

    @staticmethod
    def _classificar(
        banco: pd.DataFrame, snaps: dict[int, dict[str, Any]], ok_raw: set[int], ok_vivo: set[int],
        serie_ok: bool, fonte_autorizada: bool,
    ) -> tuple[set[int], set[int], dict[str, int]]:
        validos: set[int] = set()
        incompat: set[int] = set()
        motivos: dict[str, int] = {}

        def contar(m: str) -> None:
            motivos[m] = motivos.get(m, 0) + 1

        for r in banco[["id", "snapshot_id"]].itertuples(index=False):
            rid, sid = int(r.id), (None if pd.isna(r.snapshot_id) else int(r.snapshot_id))
            sn = snaps.get(sid) if sid is not None else None
            if not fonte_autorizada or (sn and sn["incompativel"]):
                incompat.add(rid)
            elif sn is None:
                contar("sem_arquivo_bruto_de_origem")
            elif not sn["ok"] or not serie_ok:
                contar("origem_ou_metadados_nao_comprovados")
            elif rid not in ok_raw:
                contar("diverge_do_arquivo_bruto")
            elif rid not in ok_vivo:
                contar("ausente_ou_diferente_na_resposta_oficial_atual")
            else:
                validos.add(rid)
        return validos, incompat, motivos

    def _amostras(self, codigo: str, arquivo: Path, banco: pd.DataFrame, vivo_chaves: pd.DataFrame) -> list[dict[str, Any]]:
        """Compara o valor bruto da resposta oficial com o banco para observações escolhidas."""
        if banco.empty:
            return []
        datas = datas_de_amostra(banco["data"].min(), banco["data"].max())
        pedidas: list[tuple[str, str, date]] = []
        if SERIES[codigo].escopo == "municipal":
            codigos = sorted(set(banco.loc[banco["nivel"] == "municipio", "cod"]))
            espalhados = [codigos[len(codigos) * k // 4] for k in range(4)] if codigos else []
            escolha = [*MUNICIPIOS_TESTE, *espalhados]
            for cod in dict.fromkeys(escolha):
                pedidas += [("municipio", cod, d) for d in datas]
            pedidas += [("estado", self.cod_uf, d) for d in datas] + [("brasil", "BR", d) for d in datas]
            pedidas.append(("municipio", "2101301", date(2024, 1, 1)))  # município sem registro em jan/2024
        else:
            pedidas += [("brasil", "BR", d) for d in datas]
        procuradas = {(n, c, d) for n, c, d in pedidas}
        brutos: dict[tuple[str, str, date], Any] = {}
        for r in DocumentoOData(arquivo).registros():
            chave = chave_do_banco(r.get("NIVNOME"), r.get("TERCODIGO"))
            data = str(r.get("VALDATA") or "")[:10]
            if chave and data:
                k = (chave[0], chave[1], date.fromisoformat(data))
                if k in procuradas:
                    brutos[k] = r.get("VALVALOR")
        no_banco = {(r.nivel, r.cod, r.data): r.valor for r in banco.itertuples(index=False)}
        resultado = []
        for k in pedidas:
            bruto, db = brutos.get(k), no_banco.get(k)
            presente_vivo, presente_db = k in brutos, k in no_banco
            resultado.append({
                "serie": codigo, "nivel": k[0], "territorio": k[1], "competencia": k[2].isoformat(),
                "valor_na_resposta_oficial": bruto, "valor_no_banco": None if db is None else int(db),
                "situacao": ("igual" if presente_vivo and presente_db and float(bruto) == float(db)
                             else "ausente_nos_dois" if not presente_vivo and not presente_db
                             else "DIVERGENTE"),
            })
        return resultado

    def _gravar_serie(
        self, serie_id: int, meta: dict[str, Any] | None, url_meta: str, serie_ok: bool, fonte_ok: bool,
        banco: pd.DataFrame, snaps: dict[int, dict[str, Any]], validos: set[int], incompat: set[int], info: dict[str, Any],
    ) -> None:
        import json

        with self.engine.begin() as con:
            con.execute(text("""
                UPDATE series_indicadores SET status_procedencia = :st, procedencia_verificada_em = now(),
                    url_metadados = :url, metadados_ipeadata = CAST(:meta AS jsonb) WHERE id = :id"""),
                {"st": VALIDADO if serie_ok else (INCOMPATIVEL if not fonte_ok else NAO_VALIDADO), "url": url_meta,
                 "meta": json.dumps(meta, ensure_ascii=False, default=str) if meta else None, "id": serie_id})
            for sid, sn in snaps.items():
                con.execute(text("""
                    UPDATE snapshots_origem SET status_procedencia = :st, verificado_em = now(), auditoria_id = :a,
                        evidencia = CAST(:ev AS jsonb) WHERE id = :id"""),
                    {"st": VALIDADO if sn["ok"] else (INCOMPATIVEL if sn["incompativel"] else NAO_VALIDADO),
                     "a": self.auditoria_id, "id": sid, "ev": json.dumps(sn, default=str)})
            todos = set(int(i) for i in banco["id"]) if len(banco) else set()
            for status, ids in ((VALIDADO, validos), (INCOMPATIVEL, incompat), (NAO_VALIDADO, todos - validos - incompat)):
                if ids:
                    con.execute(text("""
                        UPDATE registros_emprego SET status_procedencia = :st, procedencia_verificada_em = now(),
                            auditoria_id = :a WHERE id = ANY(:ids)"""),
                        {"st": status, "a": self.auditoria_id, "ids": sorted(ids)})
