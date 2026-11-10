"""Orquestração da coleta com checkpoint: modos FULL e INCREMENTAL.

Tarefas de uma execução, nesta ordem:

1. ``territorios``: cadastro de municípios do IpeaData (entidade ``Territorios``), validado
   estruturalmente conforme a política territorial. Nenhuma lista externa é consultada;
2. ``serie:<código>``: para cada série, download do snapshot completo (a API
   não filtra no servidor), validação, processamento em lotes, comparação
   com a base local, gravação atômica e verificação;
3. ``consolidacao``: painel município × mês, cadastros e matrizes de cobertura.

Uma tarefa só é marcada como concluída depois que seus arquivos foram
gravados e relidos. Se a execução for interrompida, a próxima chamada do
mesmo modo retoma do ponto em que parou, reaproveitando downloads já
validados.

**FULL** reconstrói cada série a partir do snapshot (as diferenças em
relação à base anterior são registradas antes da substituição).
**INCREMENTAL** consulta ``SERATUALIZACAO``; se a série mudou, baixa o
snapshot e aplica só observações novas e revisões dentro da janela.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from coleta import cobertura, esquema, incremental, territorios
from coleta.armazenamento import carimbo, exportar_csv, limpar_incompletos, salvar_json, sha256_arquivo
from coleta.checkpoint import EM_ANDAMENTO, Checkpoint, agora_utc
from coleta.config import (
    FONTE_IPEADATA,
    FONTE_ORIGINAL_MTE,
    URL_IPEADATA,
    SERIES,
    SERIES_MUNICIPAIS,
    ConfigAPI,
    ConfigColeta,
    Diretorios,
    SerieConfig,
)
from coleta.investigacao import resumir_metadados
from coleta.ipea_client import Download, IpeaAPIError, IpeaClient, IpeaResponseError, LimitadorRequisicoes
from coleta.leitor_odata import DocumentoOData, lotes_de_paginas
from coleta.procedencia import verificar_metadados
from coleta.repositorio import RepositorioDados
from coleta.transformacao import ContextoSerie, EntradaPainel, montar_painel, processar

logger = logging.getLogger(__name__)

TAREFA_TERRITORIOS = "territorios"
TAREFA_CONSOLIDACAO = "consolidacao"


def nome_tarefa(codigo: str) -> str:
    return f"serie:{codigo}"


class ErroColeta(RuntimeError):
    """Falha de integridade detectada pelo próprio pipeline."""


class ClienteFonte(Protocol):
    def __enter__(self) -> ClienteFonte: ...
    def __exit__(self, *args: object) -> None: ...
    def metadados(self, codigo: str) -> dict[str, Any] | None: ...
    def caminho_valores(self, codigo: str) -> str: ...
    def filtro_municipios_uf(self, codigo_uf: str) -> dict[str, str]: ...
    def baixar_para_arquivo(self, caminho: str, destino: Path, params: dict[str, str] | None = None) -> Download: ...


@dataclass
class Plano:
    serie: SerieConfig
    tarefa: str
    acao: str  # "processar" | "sem_alteracao" | "pular"
    modo_serie: str = "full"
    metadados: dict[str, Any] = field(default_factory=dict)
    download: dict[str, Any] | None = None


def fabrica_cliente_padrao(config_api: ConfigAPI) -> Callable[[], IpeaClient]:
    """Clientes independentes (um por thread) que compartilham o limite de taxa."""
    limitador = LimitadorRequisicoes(config_api.intervalo_minimo_segundos)
    return lambda: IpeaClient(config_api, limitador=limitador)


class Pipeline:
    def __init__(
        self,
        config: ConfigColeta,
        diretorios: Diretorios,
        fabrica_cliente: Callable[[], AbstractContextManager[ClienteFonte]],
        series: list[SerieConfig] | None = None,
        reiniciar: bool = False,
        forcar: bool = False,
        max_paginas: int = 1000,
    ) -> None:
        self.config = config
        self.dirs = diretorios
        self.fabrica_cliente = fabrica_cliente
        self.series = series or list(SERIES.values())
        self.reiniciar = reiniciar
        self.forcar = forcar
        self.max_paginas = max_paginas
        self.checkpoint = Checkpoint(diretorios.checkpoints)
        self.repo = RepositorioDados(diretorios)

    @property
    def modo(self) -> str:
        return self.config.modo

    def _rel(self, caminho: Path) -> str:
        return self.repo.rel(caminho)

    # --- Execução ------------------------------------------------------------

    def executar(self) -> dict[str, Any]:
        inicio = time.monotonic()
        removidos = limpar_incompletos(
            [self.dirs.raw_ipeadata, self.dirs.processed, self.dirs.checkpoints, self.dirs.reports]
        )
        removidos += self._limpar_brutos_sem_meta()
        tarefas = [TAREFA_TERRITORIOS, *(nome_tarefa(s.codigo) for s in self.series), TAREFA_CONSOLIDACAO]
        retomada = self.checkpoint.iniciar_execucao(self.modo, tarefas, self.reiniciar)
        self.execucao_id = self.checkpoint.execucao_id
        erro_fatal = None
        try:
            with self.fabrica_cliente() as cliente:
                self.cliente = cliente
                municipios = self._tarefa_territorios()
                planos = self._planejar()
                self._baixar(planos)
                for plano in planos:
                    self._processar(plano, municipios)
                self._tarefa_consolidacao(municipios)
        except territorios.ErroTerritorial as exc:
            erro_fatal = str(exc)
            self.checkpoint.falhar(TAREFA_TERRITORIOS, erro_fatal)
        except BaseException as exc:
            # Interrupção (Ctrl+C) ou erro inesperado: fica registrada e a execução segue retomável.
            self.checkpoint.registrar_interrupcao(f"{type(exc).__name__}: {exc}")
            raise

        resumo = self._resumo(retomada, removidos, round(time.monotonic() - inicio, 1), erro_fatal)
        resumo["status"] = self.checkpoint.finalizar_execucao(resumo)
        self._exportar_execucoes()
        # Um arquivo por tentativa: uma execução retomada gera vários.
        salvar_json(resumo, self.dirs.reports / "execucoes" / f"{self.execucao_id}_{carimbo(agora_utc())}.json")
        if erro_fatal:
            raise territorios.ErroTerritorial(erro_fatal)
        return resumo

    def _limpar_brutos_sem_meta(self) -> list[str]:
        """Um bruto sem ``.meta.json`` não chegou a ser validado: é descartado."""
        removidos = []
        for caminho in self.dirs.raw_ipeadata.rglob("*.json.gz") if self.dirs.raw_ipeadata.exists() else []:
            if not caminho.with_name(caminho.name.replace(".json.gz", ".meta.json")).exists():
                caminho.unlink()
                removidos.append(str(caminho))
                logger.warning("Bruto sem validação removido: %s", caminho, extra={"evento": "bruto_incompleto"})
        return removidos

    # --- Downloads -----------------------------------------------------------

    def _baixar_snapshot(
        self, cliente: ClienteFonte, caminho: str, params: dict[str, str] | None, pasta: Path, prefixo: str
    ) -> dict[str, Any]:
        """Baixa todas as páginas, valida cada uma e grava os metadados de origem."""
        base = f"{prefixo}_{carimbo(agora_utc())}"
        paginas: list[dict[str, Any]] = []
        proximo, parametros, vistos = caminho, params, set()
        while True:
            numero = len(paginas) + 1
            destino = pasta / (f"{base}.json.gz" if numero == 1 else f"{base}_p{numero}.json.gz")
            download = cliente.baixar_para_arquivo(proximo, destino, parametros)
            try:
                info = DocumentoOData(destino).validar()
            except IpeaResponseError:
                destino.unlink(missing_ok=True)
                raise
            meta = {
                "fonte": "IpeaData - API OData v4",
                "url": download.url,
                "status_http": download.status,
                "coletado_em_utc": download.coletado_em,
                "duracao_s": download.duracao_s,
                "bytes": download.bytes,
                "content_length": download.content_length,
                "sha256": download.sha256,
                "pagina": numero,
                "proxima_pagina": info.proxima_pagina,
                "arquivo": self._rel(destino),
            }
            salvar_json(meta, destino.with_name(destino.name.replace(".json.gz", ".meta.json")))
            paginas.append(meta)
            if not info.proxima_pagina:
                break
            if info.proxima_pagina in vistos or numero >= self.max_paginas:
                raise IpeaResponseError(f"Paginação interrompida (laço ou limite) em {info.proxima_pagina}")
            vistos.add(info.proxima_pagina)
            proximo, parametros = info.proxima_pagina, None
        return {
            "coletado_em_utc": paginas[0]["coletado_em_utc"],
            "paginas": len(paginas),
            "arquivos": [p["arquivo"] for p in paginas],
            "sha256": [p["sha256"] for p in paginas],
            "bytes": sum(p["bytes"] for p in paginas),
        }

    def _download_valido(self, download: dict[str, Any] | None) -> bool:
        """Confere se os brutos de uma etapa anterior continuam íntegros."""
        if not download:
            return False
        for arquivo, sha in zip(download["arquivos"], download["sha256"]):
            caminho = self.dirs.raiz / arquivo
            if not caminho.exists() or sha256_arquivo(caminho, descomprimir=True) != sha:
                logger.warning("Bruto ausente ou alterado: %s", caminho, extra={"evento": "bruto_invalido"})
                return False
        return True

    # --- Territórios ---------------------------------------------------------

    def _tarefa_territorios(self) -> pd.DataFrame:
        caminho = self.dirs.consolidado / "municipios.csv"
        if not self.checkpoint.precisa_executar(TAREFA_TERRITORIOS) and caminho.exists():
            return esquema.ler_csv(caminho, esquema.MUNICIPIO)
        self.checkpoint.atualizar(TAREFA_TERRITORIOS, status=EM_ANDAMENTO)
        uf, sigla = self.config.codigo_uf, self.config.uf_sigla

        try:
            snapshot = self._baixar_snapshot(
                self.cliente, "Territorios", self.cliente.filtro_municipios_uf(uf),
                self.dirs.raw_ipeadata / "territorios", f"municipios_uf{uf}",
            )
        except IpeaAPIError as exc:
            raise territorios.ErroTerritorial(f"Cadastro de territórios do IpeaData indisponível: {exc}") from exc
        registros = [r for arq in snapshot["arquivos"] for r in DocumentoOData(self.dirs.raiz / arq).registros()]
        validos, problemas = territorios.validar_cadastro(
            registros, uf, self.config.total_municipios_esperado, self.config.politica_territorial
        )
        municipios = territorios.municipios_dataframe(registros, validos, sigla, uf)
        exportar_csv(municipios, caminho)
        self.repo.registrar_arquivo(caminho, len(municipios), self.execucao_id, TAREFA_TERRITORIOS)
        if len(esquema.ler_csv(caminho, esquema.MUNICIPIO)) != len(municipios):
            raise ErroColeta(f"Releitura de {caminho} não confere")
        self.checkpoint.concluir(
            TAREFA_TERRITORIOS,
            {
                "municipios_validos": len(validos),
                "registros_no_cadastro": len(registros),
                "fonte_do_cadastro": "IpeaData - entidade Territorios",
                "territorios_ipeadata": snapshot,
                "problemas": problemas,
                "politica": self.config.politica_territorial,
            },
        )
        return municipios

    # --- Séries --------------------------------------------------------------

    def _planejar(self) -> list[Plano]:
        planos = []
        for serie in self.series:
            tarefa = nome_tarefa(serie.codigo)
            info = self.checkpoint.tarefa(tarefa)
            if not self.checkpoint.precisa_executar(tarefa):
                planos.append(Plano(serie, tarefa, "pular"))
                continue
            try:
                meta = self.cliente.metadados(serie.codigo)
            except IpeaAPIError as exc:
                self.checkpoint.falhar(tarefa, f"Metadados indisponíveis: {exc}")
                continue
            problemas_meta = verificar_metadados(serie, meta)
            if problemas_meta:
                self.checkpoint.falhar(tarefa, "Procedência não comprovada: " + "; ".join(problemas_meta))
                continue

            ultima = info.get("ultima_conclusao") or {}
            modo_serie = self.modo
            if modo_serie == "incremental" and not (ultima and self.repo.existe(serie)):
                logger.warning(
                    "%s sem base local: carga completa desta série", serie.codigo,
                    extra={"evento": "incremental_sem_base", "tarefa": tarefa},
                )
                modo_serie = "full"
            if (
                modo_serie == "incremental"
                and not self.forcar
                and meta.get("SERATUALIZACAO") == ultima.get("serie_atualizada_em")
            ):
                planos.append(Plano(serie, tarefa, "sem_alteracao", modo_serie, meta))
                continue
            reaproveitado = info.get("download") if info.get("etapa") == "baixada" else None
            if reaproveitado and not self._download_valido(reaproveitado):
                reaproveitado = None
            if reaproveitado:
                logger.info("Reaproveitando download de %s", serie.codigo, extra={"evento": "download_reaproveitado"})
            planos.append(Plano(serie, tarefa, "processar", modo_serie, meta, reaproveitado))
        return planos

    def _baixar(self, planos: list[Plano]) -> None:
        pendentes = [p for p in planos if p.acao == "processar" and p.download is None]

        def baixar(plano: Plano, cliente: ClienteFonte) -> dict[str, Any]:
            return self._baixar_snapshot(
                cliente, cliente.caminho_valores(plano.serie.codigo), None,
                self.dirs.raw_ipeadata / plano.serie.codigo, plano.serie.codigo,
            )

        def registrar(plano: Plano, executar: Callable[[], dict[str, Any]]) -> None:
            try:
                plano.download = executar()
                self.checkpoint.registrar_download(plano.tarefa, plano.download)
            except IpeaAPIError as exc:
                plano.acao = "falhou"
                self.checkpoint.falhar(plano.tarefa, f"Download: {exc}")

        if self.config.max_concorrencia == 1:
            for plano in pendentes:
                registrar(plano, lambda p=plano: baixar(p, self.cliente))
            return

        def em_thread(plano: Plano) -> dict[str, Any]:
            with self.fabrica_cliente() as cliente:
                return baixar(plano, cliente)

        with ThreadPoolExecutor(max_workers=self.config.max_concorrencia) as executor:
            futuros = {executor.submit(em_thread, plano): plano for plano in pendentes}
            for futuro in as_completed(futuros):
                registrar(futuros[futuro], futuro.result)

    def _verificar(self, serie: SerieConfig, esperado: pd.DataFrame) -> None:
        """Relê o que foi gravado e confere chaves e valores."""
        relido = self.repo.ler(serie)
        chave = list(esquema.CHAVE_OBSERVACAO)
        if relido.duplicated(subset=chave).any():
            raise ErroColeta(f"{serie.codigo}: chaves duplicadas após gravação")
        ordenar = lambda df: df[chave + ["valor"]].sort_values(chave).reset_index(drop=True)  # noqa: E731
        if len(relido) != len(esperado) or not ordenar(relido).equals(ordenar(esperado)):
            raise ErroColeta(f"{serie.codigo}: conteúdo relido ({len(relido)}) difere do esperado ({len(esperado)})")

    def _processar(self, plano: Plano, municipios: pd.DataFrame) -> None:
        if plano.acao in ("pular", "falhou"):
            return
        meta_resumo = resumir_metadados(plano.metadados)
        if plano.acao == "sem_alteracao":
            anterior = (self.checkpoint.tarefa(plano.tarefa).get("ultima_conclusao") or {}).get("resultado") or {}
            self.checkpoint.concluir(
                plano.tarefa,
                {
                    "situacao": "sem_alteracoes_na_fonte",
                    "serie_atualizada_em": plano.metadados.get("SERATUALIZACAO"),
                    "observacoes_armazenadas": anterior.get("observacoes_armazenadas"),
                    "arquivos": anterior.get("arquivos"),
                },
            )
            return
        serie, download = plano.serie, plano.download
        assert download is not None
        try:
            ctx = ContextoSerie(
                serie=serie,
                metadados=plano.metadados,
                uf_sigla=self.config.uf_sigla,
                codigo_uf=self.config.codigo_uf,
                municipios_oficiais=dict(zip(municipios["cod_ibge"], municipios["municipio"])),
                coletado_em=download["coletado_em_utc"],
                execucao_id=self.execucao_id,
                arquivo_bruto=download["arquivos"][0],
            )
            paginas = [self.dirs.raiz / arquivo for arquivo in download["arquivos"]]
            resultado = processar(lotes_de_paginas(paginas, self.config.tamanho_lote), ctx)
            nova = resultado.observacoes
            base = self.repo.ler(serie)

            if plano.modo_serie == "full":
                dif = incremental.comparar(base, nova, None)
                final, anos = nova, None
                alteracoes = incremental.registro_alteracoes(dif, True, remover_ausentes=True)
            else:
                dif = incremental.comparar(base, nova, self.config.janela_incremental_meses)
                final, anos = incremental.aplicar(base, nova, dif, self.config.aplicar_revisoes_fora_janela)
                alteracoes = incremental.registro_alteracoes(
                    dif, self.config.aplicar_revisoes_fora_janela, remover_ausentes=False
                )

            arquivos = self.repo.gravar(serie, final, anos, self.execucao_id)
            self._verificar(serie, final)
            relatorios = {}
            if not resultado.rejeitados.empty:
                destino = self.dirs.reports / "rejeitados" / f"{self.execucao_id}_{serie.codigo}.csv"
                relatorios["rejeitados"] = self._rel(exportar_csv(resultado.rejeitados, destino))
            if not base.empty and not alteracoes.empty:
                destino = self.dirs.reports / "alteracoes" / f"{self.execucao_id}_{serie.codigo}.csv"
                relatorios["alteracoes"] = self._rel(exportar_csv(alteracoes, destino))

            estat = resultado.estatisticas
            self.checkpoint.concluir(
                plano.tarefa,
                {
                    "modo_serie": plano.modo_serie,
                    "estatisticas": estat,
                    "diferencas_em_relacao_a_base": dif.contagens() if not base.empty else None,
                    "inicio_janela_incremental": dif.inicio_janela.isoformat() if dif.inicio_janela else None,
                    "observacoes_armazenadas": len(final),
                    "arquivos": arquivos,
                    "relatorios": relatorios,
                },
                referencia={
                    "serie_atualizada_em": plano.metadados.get("SERATUALIZACAO"),
                    "snapshot": download,
                    "disponibilidade": estat["disponibilidade"],
                    "lacunas_sistemicas": estat["lacunas_sistemicas"],
                    "metadados": meta_resumo,
                },
            )
        except (IpeaAPIError, ErroColeta, OSError) as exc:
            self.checkpoint.falhar(plano.tarefa, f"{type(exc).__name__}: {exc}")

    # --- Consolidação --------------------------------------------------------

    def _tarefa_consolidacao(self, municipios: pd.DataFrame) -> None:
        if not self.checkpoint.precisa_executar(TAREFA_CONSOLIDACAO):
            return
        self.checkpoint.atualizar(TAREFA_CONSOLIDACAO, status=EM_ANDAMENTO)
        entradas: dict[str, EntradaPainel] = {}
        lacunas: dict[str, set[date]] = {}
        for serie in SERIES_MUNICIPAIS:
            info = self.checkpoint.tarefa(nome_tarefa(serie.codigo))
            ultima = info.get("ultima_conclusao") or {}
            disp = ultima.get("disponibilidade") or {}
            base = self.repo.ler(serie)
            entradas[serie.indicador] = EntradaPainel(
                serie, base,
                date.fromisoformat(disp["inicio"]) if disp.get("inicio") else None,
                date.fromisoformat(disp["fim"]) if disp.get("fim") else None,
                coleta_ok=not base.empty,
            )
            lacunas[serie.indicador] = {date.fromisoformat(d) for d in ultima.get("lacunas_sistemicas", [])}

        painel = montar_painel(entradas["admissoes"], entradas["desligamentos"], municipios)
        anos = self._anos_de_referencia(painel)
        if not anos:
            self.checkpoint.falhar(TAREFA_CONSOLIDACAO, "Nenhuma série com dados para consolidar")
            return
        mensal = cobertura.matriz_mensal(painel, lacunas)
        info_series = {
            ind: {"serie_codigo": e.serie.codigo, "metodologia": e.serie.metodologia, "fonte": FONTE_IPEADATA}
            for ind, e in entradas.items()
        }
        anual = cobertura.matriz_anual(mensal, municipios, anos, info_series)
        resumo = cobertura.resumo(mensal, anual, municipios)

        arquivos = {
            "painel": exportar_csv(painel, self.dirs.consolidado / "painel_municipal_mensal.csv"),
            "series": exportar_csv(self._tabela_series(), self.dirs.consolidado / "series.csv"),
            "fontes": exportar_csv(self._tabela_fontes(), self.dirs.consolidado / "fontes.csv"),
            "cobertura_anual": exportar_csv(anual, self.dirs.reports / "cobertura_municipio_ano_indicador.csv"),
            "cobertura_mensal": exportar_csv(mensal, self.dirs.reports / "cobertura_municipio_mes_indicador.csv"),
        }
        for nome, caminho in arquivos.items():
            if caminho.is_relative_to(self.dirs.processed):
                self.repo.registrar_arquivo(caminho, len(pd.read_csv(caminho, usecols=[0])), self.execucao_id, TAREFA_CONSOLIDACAO)
        salvar_json({**resumo, "anos_avaliados": [min(anos), max(anos)]}, self.dirs.reports / "cobertura_resumo.json")
        self.checkpoint.concluir(
            TAREFA_CONSOLIDACAO,
            {
                "linhas_painel": len(painel),
                "arquivos": {nome: self._rel(caminho) for nome, caminho in arquivos.items()},
                "anos_avaliados": [min(anos), max(anos)],
            },
        )

    def _anos_de_referencia(self, painel: pd.DataFrame) -> range:
        """Do primeiro ano publicado por qualquer série da família CAGED até o último.

        Anos anteriores à série municipal aparecem na matriz como
        "não disponibilizado pela fonte", o que documenta a limitação.
        """
        anos = set(painel["ano"].dropna().astype(int))
        for serie in self.series:
            disp = (self.checkpoint.tarefa(nome_tarefa(serie.codigo)).get("ultima_conclusao") or {}).get(
                "disponibilidade"
            ) or {}
            for chave in ("inicio", "fim"):
                if disp.get(chave):
                    anos.add(int(disp[chave][:4]))
        return range(min(anos), max(anos) + 1) if anos else range(0)

    def _tabela_series(self) -> pd.DataFrame:
        linhas = []
        for serie in SERIES.values():
            info = self.checkpoint.tarefa(nome_tarefa(serie.codigo))
            ultima = info.get("ultima_conclusao") or {}
            meta = ultima.get("metadados") or {}
            disp = ultima.get("disponibilidade") or {}
            linhas.append(
                {
                    "serie_codigo": serie.codigo,
                    "serie_nome": meta.get("nome"),
                    "indicador": serie.indicador,
                    "metodologia": serie.metodologia,
                    "escopo": serie.escopo,
                    "fonte": FONTE_IPEADATA,
                    "fonte_original": meta.get("fonte_sigla"),
                    "fonte_original_nome": meta.get("fonte_nome"),
                    "base_ipeadata": meta.get("base"),
                    "periodicidade": meta.get("periodicidade"),
                    "unidade": meta.get("unidade"),
                    "situacao_na_fonte": meta.get("situacao"),
                    "serie_atualizada_em": ultima.get("serie_atualizada_em"),
                    "disponibilidade_inicio": disp.get("inicio"),
                    "disponibilidade_fim": disp.get("fim"),
                    "periodos_disponiveis": disp.get("periodos"),
                    "observacoes_armazenadas": (ultima.get("resultado") or {}).get("observacoes_armazenadas"),
                    "ultima_execucao_id": ultima.get("execucao_id"),
                    "ultima_conclusao_utc": ultima.get("concluida_em"),
                    "status_ultima_tentativa": info.get("status"),
                    "erro_ultima_tentativa": info.get("erro"),
                }
            )
        return pd.DataFrame(linhas)

    @staticmethod
    def _tabela_fontes() -> pd.DataFrame:
        """Fontes do projeto. Só o IpeaData é autorizada para obtenção de dados."""
        return pd.DataFrame(
            [
                {"fonte": FONTE_IPEADATA, "papel": "Fonte de obtenção de todas as observações e do cadastro de municípios",
                 "url": URL_IPEADATA, "formato": "OData v4 / JSON", "tipo_fonte": "acesso",
                 "autorizada_para_coleta": True},
                {"fonte": FONTE_ORIGINAL_MTE, "papel": "Origem estatística informada nos metadados das séries; nunca acessada diretamente",
                 "url": "", "formato": "Não acessada", "tipo_fonte": "origem_estatistica",
                 "autorizada_para_coleta": False},
            ]
        )

    # --- Resumo --------------------------------------------------------------

    def _resumo(self, retomada: bool, removidos: list[str], duracao: float, erro_fatal: str | None) -> dict[str, Any]:
        tarefas = {}
        for nome in self.checkpoint.execucao["tarefas"]:
            info = self.checkpoint.tarefa(nome)
            resultado = (info.get("ultima_conclusao") or {}).get("resultado") or {}
            estat = resultado.get("estatisticas") or {}
            tarefas[nome] = {
                "status": info.get("status"),
                "erro": info.get("erro"),
                "registros_lidos": estat.get("registros_lidos"),
                "observacoes": estat.get("observacoes"),
                "rejeitados": estat.get("rejeitados"),
                "duplicatas_exatas_removidas": estat.get("duplicatas_exatas_removidas"),
                "chaves_conflitantes": estat.get("chaves_conflitantes"),
                "diferencas": resultado.get("diferencas_em_relacao_a_base"),
                "situacao": resultado.get("situacao"),
            }
        return {
            "execucao_id": self.execucao_id,
            "modo": self.modo,
            "retomada": retomada,
            "duracao_s": duracao,
            "arquivos_incompletos_removidos": removidos,
            "erro_fatal": erro_fatal,
            "tarefas": tarefas,
        }

    def _exportar_execucoes(self) -> None:
        linhas = [
            {
                "execucao_id": e.get("id"),
                "modo": e.get("modo"),
                "status": e.get("status"),
                "iniciada_em": e.get("iniciada_em"),
                "finalizada_em": e.get("finalizada_em") or e.get("registrado_em"),
                "retomadas": e.get("retomadas"),
                "pendentes": ";".join(e.get("pendentes") or []),
            }
            for e in self.checkpoint.historico()
        ]
        exportar_csv(pd.DataFrame(linhas), self.dirs.consolidado / "execucoes.csv")
