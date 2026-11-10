"""Importação dos arquivos processados da coleta para o PostgreSQL.

Fluxo por execução:

1. Pré-condições: nenhuma coleta em andamento, validação da etapa 1 não reprovada,
   e nenhuma outra importação rodando (trava ``pg_advisory_lock``).
2. Cadastros (fontes, 217 municípios, séries) por upsert.
3. Para cada arquivo de observações do ``manifesto.json`` (o SHA-256 do arquivo
   em disco precisa bater com o manifesto), **uma transação**:
   leitura em lotes → validação → ``COPY`` para uma tabela temporária →
   detecção de chaves repetidas → registro de revisões (valor anterior) →
   ``INSERT ... ON CONFLICT DO UPDATE`` (só quando o valor muda) → observações
   do banco ausentes no arquivo (registradas, nunca apagadas) → registro do
   arquivo em ``arquivos_importados`` → contadores da execução.

FULL processa todos os arquivos; INCREMENTAL só os que não constam em
``arquivos_importados`` com o mesmo SHA-256. Em ambos, reprocessar não muda
nada (upsert idempotente). Uma falha desfaz só o arquivo em curso; os já
confirmados ficam, e a próxima execução incremental continua de onde parou.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Connection, Engine, insert, text, update

from banco import procedencia, repositorios
from banco.modelos import ExecucaoImportacao, InconsistenciaDados
from coleta import esquema
from coleta.armazenamento import ler_json, salvar_json, sha256_arquivo
from coleta.config import CODIGOS_SERIES_AUTORIZADAS, FONTE_IPEADATA, Diretorios

logger = logging.getLogger(__name__)

TRAVA_IMPORTACAO = 731_202_026  # identificador arbitrário da advisory lock
INDICADORES_CONTAGEM = ("admissoes", "desligamentos")
PREFIXO_BRUTOS_IPEADATA = "data/raw/ipeadata/"
# Origens de arquivos do manifesto que não são séries (cadastros e consolidados).
ORIGENS_NAO_SERIE = frozenset({"territorios", "consolidacao"})
COLUNAS_STAGING = (
    "serie_id", "nivel_territorial", "cod_territorio", "municipio_cod", "uf", "data_referencia", "ano", "mes",
    "valor", "cod_territorio_original", "arquivo_bruto", "arquivo_processado", "coletado_em",
    "serie_atualizada_em", "execucao_coleta_id",
)
CHAVE = ("serie_id", "nivel_territorial", "cod_territorio", "data_referencia")


class ErroImportacao(RuntimeError):
    """Pré-condição não atendida; nada foi importado."""


@dataclass
class ContextoValidacao:
    series: dict[str, dict[str, Any]]
    municipios: set[str]
    cod_uf: str
    arquivo: str
    serie_esperada: str


@dataclass
class ResultadoArquivo:
    caminho: str
    serie: str
    lidos: int = 0
    validos: int = 0
    inseridos: int = 0
    atualizados: int = 0
    inalterados: int = 0
    rejeitados: int = 0
    ausentes_na_origem: int = 0
    revisoes: int = 0
    motivos: Counter[str] = field(default_factory=Counter)


@dataclass
class ResumoImportacao:
    importacao_id: int
    tipo: str
    status: str
    totais: dict[str, int]
    arquivos: list[dict[str, Any]]
    ignorados: list[dict[str, str]]
    registros_no_banco: dict[str, int]
    duracao_s: float
    avisos: list[str]


# --- Validação (pura, testável sem banco) --------------------------------------------

def validar_lote(df: pd.DataFrame, ctx: ContextoValidacao) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Separa linhas válidas (já no formato da staging) das rejeitadas, com motivo.

    Cada linha recebe o **primeiro** motivo aplicável. Nada é corrigido: valor
    ausente é rejeitado, nunca convertido em zero.
    """
    motivo = pd.Series(pd.NA, index=df.index, dtype="string")

    def marcar(condicao: pd.Series, nome: str) -> None:
        motivo[motivo.isna() & condicao.fillna(True).astype(bool)] = nome

    info = df["serie_codigo"].map(ctx.series)
    conhecida = info.notna()
    marcar(~conhecida, "serie_desconhecida")
    marcar(df["serie_codigo"] != ctx.serie_esperada, "serie_fora_do_arquivo")
    # Regra do projeto: só observações do IpeaData, com o bruto preservado na pasta do IpeaData.
    marcar(df["fonte"] != FONTE_IPEADATA, "fonte_nao_autorizada")
    marcar(~df["arquivo_bruto"].str.startswith(PREFIXO_BRUTOS_IPEADATA), "origem_fora_do_ipeadata")
    metodologia = info.map(lambda i: i["metodologia"] if isinstance(i, dict) else None)
    fonte = info.map(lambda i: i["fonte"] if isinstance(i, dict) else None)
    indicador = info.map(lambda i: i["indicador"] if isinstance(i, dict) else None)
    marcar(conhecida & (df["metodologia"] != metodologia), "metodologia_divergente")
    marcar(conhecida & (df["fonte"] != fonte), "fonte_divergente")
    nivel = df["nivel_territorial"]
    marcar(~nivel.isin(["municipio", "estado", "brasil"]), "nivel_invalido")
    marcar((nivel == "municipio") & ~df["cod_ibge"].isin(ctx.municipios), "municipio_fora_do_cadastro")
    marcar((nivel == "estado") & (df["cod_ibge"] != ctx.cod_uf), "uf_divergente")
    data = df["data_referencia"]
    marcar(data.isna() | (data.dt.day != 1), "data_invalida")
    marcar((df["ano"] != data.dt.year) | (df["mes"].notna() & (df["mes"] != data.dt.month)), "ano_mes_incoerentes")
    marcar(df["valor"].isna(), "valor_ausente")
    marcar(indicador.isin(INDICADORES_CONTAGEM) & (df["valor"] < 0), "valor_negativo_em_contagem")
    marcar((df["arquivo_bruto"] == "") | (df["coletado_em_utc"] == "") | (df["execucao_id"] == ""), "origem_ausente")

    rejeitadas = df[motivo.notna()]
    rejeicoes = [
        {
            "tipo": "registro_rejeitado:" + m,
            "identificacao_registro": f"{r['serie_codigo']}|{r['nivel_territorial']}|{r['cod_ibge']}|"
                                      f"{r['data_referencia'].date() if pd.notna(r['data_referencia']) else ''}",
            "descricao": f"Registro rejeitado na importação ({m})",
            "dados": {k: (None if pd.isna(v) else str(v)) for k, v in r.items()},
            "arquivo": ctx.arquivo,
        }
        for m, (_, r) in zip(motivo[motivo.notna()], rejeitadas.iterrows())
    ]

    v = df[motivo.isna()]
    cod_territorio = v["cod_ibge"].where(v["nivel_territorial"] != "brasil", "BR")
    validos = pd.DataFrame({
        "serie_id": v["serie_codigo"].map(lambda c: ctx.series[c]["id"]).astype("Int64"),
        "nivel_territorial": v["nivel_territorial"],
        "cod_territorio": cod_territorio,
        "municipio_cod": v["cod_ibge"].where(v["nivel_territorial"] == "municipio"),
        "uf": v["uf"].where(v["uf"] != ""),
        "data_referencia": v["data_referencia"].dt.date,
        "ano": v["ano"],
        "mes": v["mes"],
        "valor": v["valor"],
        "cod_territorio_original": v["cod_territorio_original"].where(v["cod_territorio_original"] != ""),
        "arquivo_bruto": v["arquivo_bruto"],
        "arquivo_processado": ctx.arquivo,
        "coletado_em": v["coletado_em_utc"],
        "serie_atualizada_em": v["serie_atualizada_em"].where(v["serie_atualizada_em"] != ""),
        "execucao_coleta_id": v["execucao_id"],
    })
    return validos, rejeicoes


def escopo_do_arquivo(caminho: str) -> tuple[str, str, int | None]:
    """(série, tipo de arquivo, ano) a partir do layout de data/processed."""
    partes = Path(caminho).parts
    if partes[-1].startswith("ano="):
        return partes[-2], "particao_municipal", int(partes[-1][4:8])
    tipo = "agregados" if "agregados" in partes else "referencia_nacional"
    return Path(caminho).stem, tipo, None


# --- Importador --------------------------------------------------------------------

class Importador:
    def __init__(self, engine: Engine, dirs: Diretorios, tipo: str, tamanho_lote: int = 5_000,
                 cod_uf: str = "21", total_municipios: int | None = 217) -> None:
        tipo = tipo.upper()
        if tipo not in ("FULL", "INCREMENTAL"):
            raise ValueError("tipo deve ser FULL ou INCREMENTAL")
        self.engine, self.dirs, self.tipo = engine, dirs, tipo
        self.tamanho_lote, self.cod_uf, self.total_municipios = tamanho_lote, cod_uf, total_municipios
        self.avisos: list[str] = []
        self._arquivos_do_checkpoint: dict[str, list[str]] = {}

    # Pré-condições ------------------------------------------------------------

    def _verificar_coleta(self) -> dict[str, Any]:
        estado = ler_json(self.dirs.checkpoints / "estado.json", {})
        andamento = estado.get("execucao_em_andamento")
        if andamento:
            raise ErroImportacao(
                f"A coleta {andamento['id']} está em andamento/incompleta; conclua-a antes de importar "
                "(os arquivos processados podem estar sendo atualizados)."
            )
        validacao = ler_json(self.dirs.reports / "validacao.json")
        if validacao is None:
            self.avisos.append("data/reports/validacao.json ausente: rode python -m scripts.validar_dados")
        elif validacao.get("situacao") == "reprovada":
            raise ErroImportacao(f"A validação da coleta está reprovada: {validacao.get('problemas_criticos')}")
        manifesto = ler_json(self.dirs.processed / "manifesto.json")
        if not manifesto:
            raise ErroImportacao("data/processed/manifesto.json não encontrado: execute a coleta antes.")
        return {"estado": estado, "manifesto": manifesto}

    # Execução -----------------------------------------------------------------

    def executar(self) -> ResumoImportacao:
        inicio = time.monotonic()
        previo = self._verificar_coleta()
        with self.engine.connect() as trava:
            if not trava.execute(text("SELECT pg_try_advisory_lock(:t)"), {"t": TRAVA_IMPORTACAO}).scalar():
                raise ErroImportacao("Outra importação está em andamento neste banco.")
            try:
                return self._executar_com_trava(previo, inicio)
            finally:
                trava.execute(text("SELECT pg_advisory_unlock(:t)"), {"t": TRAVA_IMPORTACAO})
                trava.commit()

    def _executar_com_trava(self, previo: dict[str, Any], inicio: float) -> ResumoImportacao:
        ultima_coleta = self._ultima_coleta(previo["estado"])
        with self.engine.begin() as con:
            interrompidas = con.execute(
                update(ExecucaoImportacao)
                .where(ExecucaoImportacao.status == "em_andamento")
                .values(status="interrompida", finalizado_em=text("now()"),
                        mensagem_erro="Execução encerrada sem finalizar (processo interrompido).")
            ).rowcount
            importacao_id = con.execute(
                insert(ExecucaoImportacao).values(
                    tipo=self.tipo, status="em_andamento", fonte=FONTE_IPEADATA, execucao_coleta_id=ultima_coleta,
                ).returning(ExecucaoImportacao.id)
            ).scalar_one()
        if interrompidas:
            self.avisos.append(f"{interrompidas} importação(ões) anterior(es) marcada(s) como interrompida(s)")
        logger.info("Importação %s (%s) iniciada", importacao_id, self.tipo,
                    extra={"evento": "importacao_iniciada", "importacao_id": importacao_id})
        self.importacao_id = importacao_id

        resultados: list[ResultadoArquivo] = []
        ignorados: list[dict[str, str]] = []
        try:
            series, municipios = self._cadastros(previo["estado"])
            arquivos = self._selecionar_arquivos(previo["manifesto"], ignorados)
            for caminho, info in arquivos:
                resultados.append(self._importar_arquivo(caminho, info, series, municipios))
            status = self._finalizar(resultados, ignorados)
        except BaseException as exc:
            with self.engine.begin() as con:
                con.execute(
                    update(ExecucaoImportacao).where(ExecucaoImportacao.id == importacao_id).values(
                        status="falhou" if isinstance(exc, Exception) else "interrompida",
                        finalizado_em=text("now()"), mensagem_erro=f"{type(exc).__name__}: {exc}"[:2000],
                    )
                )
            logger.error("Importação %s falhou: %s", importacao_id, exc, extra={"evento": "importacao_falhou"})
            raise

        with self.engine.connect() as con:
            no_banco = repositorios.contagem_registros(con)
        resumo = ResumoImportacao(
            importacao_id, self.tipo, status, self._totais(resultados, ignorados),
            [self._resumo_arquivo(r) for r in resultados], ignorados, no_banco,
            round(time.monotonic() - inicio, 2), self.avisos,
        )
        salvar_json(resumo.__dict__, self.dirs.reports / "importacoes" / f"importacao_{importacao_id:05d}.json")
        return resumo

    @staticmethod
    def _ultima_coleta(estado: dict[str, Any]) -> str | None:
        conclusoes = [
            (t.get("ultima_conclusao") or {}).get("execucao_id")
            for t in estado.get("tarefas", {}).values() if t.get("ultima_conclusao")
        ]
        return max(conclusoes) if conclusoes else None

    def _cadastros(self, estado: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
        consolidado = self.dirs.consolidado
        fontes = pd.read_csv(consolidado / "fontes.csv", dtype=str, keep_default_na=False)
        municipios = esquema.ler_csv(consolidado / "municipios.csv", esquema.MUNICIPIO)
        series = pd.read_csv(consolidado / "series.csv", dtype=str, keep_default_na=False)
        nao_autorizadas = sorted(set(series["serie_codigo"]) - CODIGOS_SERIES_AUTORIZADAS)
        if nao_autorizadas:
            raise ErroImportacao(f"Séries não autorizadas no consolidado (não existem na configuração): {nao_autorizadas}")
        ultima = ((estado.get("tarefas", {}).get("territorios") or {}).get("ultima_conclusao") or {})
        snap_terr = procedencia.snapshot_territorios(estado)
        with self.engine.begin() as con:
            ids = repositorios.upsert_fontes(con, fontes)
            snapshot_id = coletado = None
            if snap_terr:
                arquivos = snap_terr["arquivos"]
                snapshot_id = procedencia.registrar_snapshot(
                    con, self.dirs, arquivos[0], "territorios", None, ultima.get("execucao_id"), arquivos=arquivos
                )
                coletado = snap_terr.get("coletado_em_utc")
            repositorios.upsert_municipios(con, municipios, ids[FONTE_IPEADATA], coletado, self.total_municipios,
                                           snapshot_id)
            mapa = repositorios.upsert_series(con, series, ids)
            procedencia.vincular_snapshots(con)
        self._arquivos_do_checkpoint = {
            codigo: (((estado.get("tarefas", {}).get(f"serie:{codigo}") or {}).get("ultima_conclusao") or {})
                     .get("snapshot") or {}).get("arquivos", [])
            for codigo in mapa
        }
        return mapa, set(municipios["cod_ibge"])

    def _selecionar_arquivos(self, manifesto: dict[str, Any], ignorados: list[dict[str, str]]) -> list[tuple[str, dict]]:
        with self.engine.connect() as con:
            ja = repositorios.arquivos_ja_importados(con)
        selecionados = []
        for caminho, info in sorted(manifesto["arquivos"].items()):
            origem = info.get("origem")
            if origem in ORIGENS_NAO_SERIE:
                continue  # cadastros e consolidados: tratados à parte
            if origem not in CODIGOS_SERIES_AUTORIZADAS:
                ignorados.append({"arquivo": caminho, "motivo": "origem_nao_autorizada"})
                continue
            completo = self.dirs.raiz / caminho
            if not completo.exists():
                ignorados.append({"arquivo": caminho, "motivo": "arquivo_ausente"})
                continue
            if sha256_arquivo(completo) != info["sha256"]:
                ignorados.append({"arquivo": caminho, "motivo": "arquivo_alterado_apos_coleta"})
                continue
            if self.tipo == "INCREMENTAL" and (caminho, info["sha256"]) in ja:
                ignorados.append({"arquivo": caminho, "motivo": "ja_importado"})
                continue
            selecionados.append((caminho, info))
        problemas = [i for i in ignorados if i["motivo"] != "ja_importado"]
        if problemas:
            with self.engine.begin() as con:
                self._registrar_inconsistencias(con, [
                    {"tipo": f"arquivo:{p['motivo']}", "arquivo": p["arquivo"],
                     "descricao": "Arquivo do manifesto não importado (integridade)"} for p in problemas
                ])
        return selecionados

    def _registrar_inconsistencias(self, con: Connection, itens: list[dict[str, Any]]) -> None:
        if itens:
            con.execute(insert(InconsistenciaDados), [
                {"importacao_id": self.importacao_id, "fonte": FONTE_IPEADATA, "arquivo": None,
                 "identificacao_registro": None, "dados": None, **i} for i in itens
            ])

    def _importar_arquivo(
        self, caminho: str, info: dict[str, Any], series: dict[str, dict[str, Any]], municipios: set[str]
    ) -> ResultadoArquivo:
        serie, tipo_arquivo, ano = escopo_do_arquivo(caminho)
        resultado = ResultadoArquivo(caminho, serie)
        ctx = ContextoValidacao(series, municipios, self.cod_uf, caminho, serie)
        with self.engine.begin() as con:
            con.execute(text(
                "CREATE TEMP TABLE stg (LIKE registros_emprego INCLUDING DEFAULTS) ON COMMIT DROP"
            ))
            con.execute(text("ALTER TABLE stg DROP COLUMN id, DROP COLUMN importacao_id, "
                             "DROP COLUMN atualizado_por_importacao_id, DROP COLUMN criado_em, DROP COLUMN atualizado_em, "
                             "DROP COLUMN snapshot_id, DROP COLUMN status_procedencia, "
                             "DROP COLUMN procedencia_verificada_em, DROP COLUMN auditoria_id"))
            cursor = con.connection.driver_connection.cursor()
            for lote in esquema.ler_csv_em_lotes(self.dirs.raiz / caminho, esquema.OBSERVACAO, self.tamanho_lote):
                resultado.lidos += len(lote)
                validos, rejeicoes = validar_lote(lote, ctx)
                self._registrar_inconsistencias(con, rejeicoes)
                resultado.rejeitados += len(rejeicoes)
                resultado.motivos.update(r["tipo"] for r in rejeicoes)
                with cursor.copy(f"COPY stg ({', '.join(COLUNAS_STAGING)}) FROM STDIN") as copia:
                    for linha in validos.itertuples(index=False, name=None):
                        copia.write_row([None if pd.isna(v) else v for v in linha])
            # Tabelas temporárias não passam pelo autovacuum: sem estatísticas, o planejador
            # estima mal as junções com registros_emprego (laços aninhados em vez de hash join).
            con.execute(text("ANALYZE stg"))
            self._registrar_snapshots_do_arquivo(con, serie, series)
            self._descartar_chaves_repetidas(con, resultado)
            resultado.validos = con.execute(text("SELECT count(*) FROM stg")).scalar_one()
            self._registrar_ausentes(con, resultado, series[serie]["id"] if serie in series else None, tipo_arquivo, ano)
            resultado.revisoes = con.execute(text("""
                INSERT INTO revisoes_registros (registro_id, importacao_id, valor_anterior, valor_novo,
                    arquivo_bruto_anterior, coletado_em_anterior, execucao_coleta_anterior, arquivo_bruto_novo)
                SELECT r.id, :imp, r.valor, s.valor, r.arquivo_bruto, r.coletado_em, r.execucao_coleta_id, s.arquivo_bruto
                FROM stg s JOIN registros_emprego r USING (serie_id, nivel_territorial, cod_territorio, data_referencia)
                WHERE r.valor <> s.valor
            """), {"imp": self.importacao_id}).rowcount
            inseridos = con.execute(text(f"""
                INSERT INTO registros_emprego ({', '.join(COLUNAS_STAGING)}, importacao_id, atualizado_por_importacao_id)
                SELECT {', '.join(COLUNAS_STAGING)}, :imp, :imp FROM stg
                ON CONFLICT ON CONSTRAINT uq_registros_emprego_chave_natural DO UPDATE SET
                    valor = EXCLUDED.valor, uf = EXCLUDED.uf, arquivo_bruto = EXCLUDED.arquivo_bruto,
                    arquivo_processado = EXCLUDED.arquivo_processado, coletado_em = EXCLUDED.coletado_em,
                    serie_atualizada_em = EXCLUDED.serie_atualizada_em, execucao_coleta_id = EXCLUDED.execucao_coleta_id,
                    cod_territorio_original = EXCLUDED.cod_territorio_original,
                    atualizado_por_importacao_id = EXCLUDED.atualizado_por_importacao_id, atualizado_em = now(),
                    -- Valor revisado: a validação anterior não vale para o novo valor.
                    snapshot_id = NULL, status_procedencia = 'nao_validado', procedencia_verificada_em = NULL,
                    auditoria_id = NULL
                WHERE registros_emprego.valor IS DISTINCT FROM EXCLUDED.valor
                RETURNING (xmax = 0) AS inserido
            """), {"imp": self.importacao_id}).scalars().all()
            resultado.inseridos = sum(1 for i in inseridos if i)
            resultado.atualizados = len(inseridos) - resultado.inseridos
            resultado.inalterados = resultado.validos - len(inseridos)
            if serie in series:
                procedencia.vincular_snapshots(con, series[serie]["id"])
                repositorios.registrar_arquivo(con, caminho, info["sha256"], series[serie]["id"], resultado.lidos,
                                               self.importacao_id)
            self._acumular(con, resultado)
        logger.info(
            "%s: lidos=%d válidos=%d inseridos=%d atualizados=%d inalterados=%d rejeitados=%d",
            caminho, resultado.lidos, resultado.validos, resultado.inseridos, resultado.atualizados,
            resultado.inalterados, resultado.rejeitados, extra={"evento": "arquivo_importado", "arquivo": caminho},
        )
        return resultado

    def _registrar_snapshots_do_arquivo(self, con: Connection, serie: str, series: dict[str, dict[str, Any]]) -> None:
        """Registra a resposta do IpeaData (URL, hash, horário) de cada arquivo bruto citado no arquivo."""
        if serie not in series:
            return
        grupos = con.execute(text(
            "SELECT arquivo_bruto, max(execucao_coleta_id), max(serie_atualizada_em) FROM stg GROUP BY arquivo_bruto"
        )).all()
        for arquivo, execucao, atualizada in grupos:
            paginas = self._arquivos_do_checkpoint.get(serie) or []
            procedencia.registrar_snapshot(
                con, self.dirs, arquivo, "serie", serie, execucao,
                atualizada.isoformat() if atualizada else None,
                arquivos=paginas if arquivo in paginas else None,
            )

    def _descartar_chaves_repetidas(self, con: Connection, resultado: ResultadoArquivo) -> None:
        """Chave natural repetida no arquivo: não há como escolher um valor; todas saem."""
        repetidas = con.execute(text(f"""
            DELETE FROM stg WHERE ({', '.join(CHAVE)}) IN (
                SELECT {', '.join(CHAVE)} FROM stg GROUP BY {', '.join(CHAVE)} HAVING count(*) > 1
            ) RETURNING serie_id, nivel_territorial, cod_territorio, data_referencia, valor
        """)).all()
        if repetidas:
            resultado.rejeitados += len(repetidas)
            resultado.motivos["registro_rejeitado:chave_repetida_no_arquivo"] += len(repetidas)
            self._registrar_inconsistencias(con, [
                {"tipo": "registro_rejeitado:chave_repetida_no_arquivo", "arquivo": resultado.caminho,
                 "identificacao_registro": f"{r[0]}|{r[1]}|{r[2]}|{r[3]}",
                 "descricao": "Chave natural repetida no arquivo processado", "dados": {"valor": r[4]}}
                for r in repetidas
            ])

    def _registrar_ausentes(self, con: Connection, resultado: ResultadoArquivo, serie_id: int | None,
                            tipo_arquivo: str, ano: int | None) -> None:
        """Observações do banco, no escopo deste arquivo, que o arquivo não traz mais."""
        if serie_id is None:
            return
        filtro = {"particao_municipal": "AND r.nivel_territorial = 'municipio' AND r.ano = :ano",
                  "agregados": "AND r.nivel_territorial <> 'municipio'", "referencia_nacional": ""}[tipo_arquivo]
        ausentes = con.execute(text(f"""
            SELECT r.id, r.nivel_territorial, r.cod_territorio, r.data_referencia, r.valor
            FROM registros_emprego r
            WHERE r.serie_id = :serie {filtro}
              AND NOT EXISTS (SELECT 1 FROM stg s WHERE s.serie_id = r.serie_id
                  AND s.nivel_territorial = r.nivel_territorial AND s.cod_territorio = r.cod_territorio
                  AND s.data_referencia = r.data_referencia)
        """), {"serie": serie_id, "ano": ano}).all()
        resultado.ausentes_na_origem = len(ausentes)
        self._registrar_inconsistencias(con, [
            {"tipo": "ausente_na_origem", "arquivo": resultado.caminho,
             "identificacao_registro": f"registro_id={r[0]}|{r[1]}|{r[2]}|{r[3]}",
             "descricao": "Observação existe no banco mas não no arquivo processado; mantida (não apagada).",
             "dados": {"valor": r[4]}} for r in ausentes
        ])

    def _acumular(self, con: Connection, r: ResultadoArquivo) -> None:
        e = ExecucaoImportacao
        con.execute(update(e).where(e.id == self.importacao_id).values(
            registros_lidos=e.registros_lidos + r.lidos, registros_validos=e.registros_validos + r.validos,
            registros_inseridos=e.registros_inseridos + r.inseridos,
            registros_atualizados=e.registros_atualizados + r.atualizados,
            registros_inalterados=e.registros_inalterados + r.inalterados,
            registros_rejeitados=e.registros_rejeitados + r.rejeitados,
            registros_ausentes_na_origem=e.registros_ausentes_na_origem + r.ausentes_na_origem,
            arquivos_processados=e.arquivos_processados + 1,
        ))

    def _finalizar(self, resultados: list[ResultadoArquivo], ignorados: list[dict[str, str]]) -> str:
        totais = self._totais(resultados, ignorados)
        problemas = totais["rejeitados"] or totais["ausentes_na_origem"] or totais["arquivos_com_problema"]
        status = "concluida_com_rejeicoes" if problemas else "concluida"
        with self.engine.begin() as con:
            con.execute(update(ExecucaoImportacao).where(ExecucaoImportacao.id == self.importacao_id).values(
                status=status, finalizado_em=text("now()"), arquivos_ignorados=len(ignorados),
                detalhes={"arquivos": [self._resumo_arquivo(r) for r in resultados], "ignorados": ignorados,
                          "avisos": self.avisos},
            ))
        logger.info("Importação %s: %s", self.importacao_id, status, extra={"evento": "importacao_finalizada"})
        return status

    @staticmethod
    def _totais(resultados: list[ResultadoArquivo], ignorados: list[dict[str, str]]) -> dict[str, int]:
        campos = ("lidos", "validos", "inseridos", "atualizados", "inalterados", "rejeitados", "ausentes_na_origem", "revisoes")
        totais = {c: sum(getattr(r, c) for r in resultados) for c in campos}
        totais["arquivos_processados"] = len(resultados)
        totais["arquivos_ignorados"] = len(ignorados)
        totais["arquivos_com_problema"] = sum(1 for i in ignorados if i["motivo"] != "ja_importado")
        return totais

    @staticmethod
    def _resumo_arquivo(r: ResultadoArquivo) -> dict[str, Any]:
        return {k: (dict(v) if isinstance(v, Counter) else v) for k, v in r.__dict__.items()}
