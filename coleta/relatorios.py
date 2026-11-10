"""Geração dos relatórios em Markdown a partir dos artefatos da coleta.

Todos os números vêm de arquivos gerados pelo pipeline (checkpoint, matrizes
de cobertura, validação, resultado do pytest em JUnit XML). Se um artefato
não existir, o relatório diz isso em vez de estimar.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from coleta import esquema
from coleta.armazenamento import ler_json, ler_jsonl
from coleta.checkpoint import agora_utc
from coleta.config import SERIES, SERIES_MUNICIPAIS, Diretorios


def tabela(linhas: Iterable[Sequence[Any]], cabecalho: Sequence[str]) -> str:
    def celula(valor: Any) -> str:
        if valor is None or (isinstance(valor, float) and pd.isna(valor)):
            return "—"
        if isinstance(valor, int) and not isinstance(valor, bool):
            return f"{valor:,}".replace(",", ".")
        return str(valor).replace("|", "\\|")

    corpo = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    corpo += ["| " + " | ".join(celula(v) for v in linha) + " |" for linha in linhas]
    return "\n".join(corpo)


def resultado_pytest(caminho: Path) -> dict[str, Any] | None:
    if not caminho.exists():
        return None
    raiz = ET.parse(caminho).getroot()
    suites = [raiz] if raiz.tag == "testsuite" else list(raiz.iter("testsuite"))
    soma = lambda campo: sum(int(s.get(campo, 0)) for s in suites)  # noqa: E731
    falhas = [
        f"{caso.get('classname')}::{caso.get('name')}"
        for caso in raiz.iter("testcase")
        if caso.find("failure") is not None or caso.find("error") is not None
    ]
    return {
        "total": soma("tests"), "falhas": soma("failures"), "erros": soma("errors"), "pulados": soma("skipped"),
        "tempo_s": round(sum(float(s.get("time", 0)) for s in suites), 1),
        "executado_em": suites[0].get("timestamp") if suites else None, "casos_com_falha": falhas,
    }


class GeradorRelatorios:
    def __init__(self, dirs: Diretorios) -> None:
        self.dirs = dirs
        self.estado = ler_json(dirs.checkpoints / "estado.json", {"tarefas": {}, "execucao_em_andamento": None})
        self.execucoes = ler_jsonl(dirs.checkpoints / "execucoes.jsonl")
        self.cobertura = ler_json(dirs.reports / "cobertura_resumo.json")
        self.validacao = ler_json(dirs.reports / "validacao.json")
        caminho_anual = dirs.reports / "cobertura_municipio_ano_indicador.csv"
        self.anual = pd.read_csv(caminho_anual, dtype={"codigo_ibge": str}) if caminho_anual.exists() else None
        self.pytest = resultado_pytest(dirs.reports / "pytest.xml")

    def _ultima(self, codigo: str) -> dict[str, Any]:
        return (self.estado["tarefas"].get(f"serie:{codigo}") or {}).get("ultima_conclusao") or {}

    def _estatisticas(self, codigo: str) -> dict[str, Any]:
        """Estatísticas da última carga que processou a série (ignora "sem alterações")."""
        for execucao in reversed(self.execucoes):
            info = ((execucao.get("resumo") or {}).get("tarefas") or {}).get(f"serie:{codigo}") or {}
            if info.get("registros_lidos") is not None:
                return info
        return {}

    # --- Cobertura histórica ---------------------------------------------------

    def cobertura_historica(self) -> str:
        agora = agora_utc()
        if not self.cobertura or self.anual is None:
            return f"# Cobertura histórica\n\nGerado em {agora}. **Sem dados**: execute a coleta antes.\n"
        territorio = (self.estado["tarefas"].get("territorios") or {}).get("ultima_conclusao") or {}
        res_terr = territorio.get("resultado") or {}
        partes = [
            "# Cobertura histórica — admissões e desligamentos nos municípios do Maranhão",
            f"Gerado automaticamente em {agora} por `python -m scripts.gerar_relatorio` a partir de "
            "`data/checkpoints/`, `data/reports/` e `data/processed/`. Não edite à mão.",
            "## Fontes efetivamente utilizadas",
            tabela(
                [
                    ("IpeaData (API OData v4)", "Única fonte de obtenção: observações e cadastro de municípios",
                     "https://www.ipeadata.gov.br/api/odata4/"),
                    ("MTE/Caged", "Origem estatística informada nos metadados; **nunca acessada diretamente**", "—"),
                ],
                ["Fonte", "Papel", "Referência"],
            ),
            "Regra do projeto: todos os dados vêm do IpeaData. Nenhuma outra fonte é consultada pelo pipeline; a "
            "comprovação registro a registro está em [auditoria_origem_ipeadata.md](auditoria_origem_ipeadata.md).",
        ]
        partes += self._secao_series()
        partes += self._secao_totais()
        partes += self._secao_cobertura(res_terr)
        partes += self._secao_erros()
        return "\n\n".join(partes) + "\n"

    def _secao_series(self) -> list[str]:
        linhas = []
        for serie in SERIES.values():
            ultima = self._ultima(serie.codigo)
            meta = ultima.get("metadados") or {}
            disp = ultima.get("disponibilidade") or {}
            linhas.append((
                serie.codigo, serie.indicador, serie.metodologia,
                "Municípios, UF e Brasil" if serie.escopo == "municipal" else "Somente Brasil",
                meta.get("periodicidade"), meta.get("unidade"),
                (disp.get("inicio") or "")[:7] or None, (disp.get("fim") or "")[:7] or None,
                disp.get("periodos"), meta.get("situacao"),
            ))
        return [
            "## Séries e indicadores",
            tabela(linhas, ["Série", "Indicador", "Metodologia", "Cobertura territorial", "Periodicidade",
                            "Unidade", "Primeiro mês", "Último mês", "Meses", "Situação na fonte"]),
            "Somente `ADMISNC` e `DESLIGNC` têm nível municipal; são elas que formam o painel dos 217 municípios. "
            "As demais são totais nacionais, guardadas em `data/processed/referencia_nacional/` só como "
            "referência e **nunca** convertidas em dado municipal. CAGED tradicional e Novo Caged não são "
            "emendados: o primeiro termina em 2019-12 e o segundo começa em 2020-01.",
        ]

    def _secao_totais(self) -> list[str]:
        linhas, total = [], {"lidos": 0, "validos": 0, "rejeitados": 0, "duplicatas": 0, "conflitos": 0, "armazenadas": 0}
        for serie in SERIES.values():
            estat = self._estatisticas(serie.codigo)
            ultima = self._ultima(serie.codigo)
            rejeitados = sum((estat.get("rejeitados") or {}).values()) if estat else None
            armazenadas = (ultima.get("resultado") or {}).get("observacoes_armazenadas")
            linha = (serie.codigo, estat.get("registros_lidos"), estat.get("observacoes"), rejeitados,
                     estat.get("duplicatas_exatas_removidas"), estat.get("chaves_conflitantes"), armazenadas)
            linhas.append(linha)
            for chave, valor in zip(total, linha[1:]):
                total[chave] += valor or 0
        linhas.append(("**Total**", *total.values()))
        return [
            "## Registros coletados",
            "\"Lidos\" são todos os registros da resposta da API (o Brasil inteiro, pois o servidor não filtra). "
            "\"Válidos\" são as observações aceitas para o Maranhão (municípios, total da UF e Brasil) ou, nas "
            "séries nacionais, para o Brasil. Registros de outras UFs, regiões e áreas metropolitanas são "
            "excluídos do escopo e não contam como rejeitados.",
            tabela(linhas, ["Série", "Lidos", "Válidos", "Rejeitados", "Duplicatas exatas", "Chaves conflitantes",
                            "Armazenadas"]),
        ]

    def _secao_cobertura(self, res_terr: dict[str, Any]) -> list[str]:
        cob = self.cobertura
        partes = [
            "## Cobertura territorial",
            f"- Cadastro de municípios (entidade `Territorios` do IpeaData): **{res_terr.get('municipios_validos', '—')}** "
            f"municípios válidos de {res_terr.get('registros_no_cadastro', '—')} registros; "
            f"problemas na validação estrutural: {res_terr.get('problemas') or 'nenhum'}.",
        ]
        linhas_terr, linhas_tempo, ausencias = [], [], []
        for indicador, info in cob["por_indicador"].items():
            linhas_terr.append((indicador, info["municipios_com_dados"], len(info["municipios_sem_dados"]),
                                ", ".join(info["municipios_sem_dados"]) or "nenhum"))
            linhas_tempo.append((indicador, info["primeiro_mes"], info["ultimo_mes"], str(info["primeiro_ano"]),
                                 str(info["ultimo_ano"]), info["anos_com_dados"]))
            ausencias += [(indicador, a["codigo_ibge"], a["municipio"], a["mes"][:7],
                           "sim" if a["lacuna_sistemica_fonte"] else "não") for a in info["observacoes_ausentes"]]
        partes += [
            tabela(linhas_terr, ["Indicador", "Municípios com dados", "Municípios sem dados", "Quais"]),
            "## Cobertura temporal",
            tabela(linhas_tempo, ["Indicador", "Primeiro mês", "Último mês", "Primeiro ano", "Último ano", "Anos com dados"]),
            f"A matriz anual avalia {cob['anos_avaliados'][0]}–{cob['anos_avaliados'][1]}: do primeiro ano publicado por "
            "qualquer série da família CAGED no IpeaData (CAGED tradicional, só nacional) até o último ano disponível. "
            "Os anos anteriores à série municipal aparecem como `nao_disponibilizado_pela_fonte`.",
            "### Situação por município × ano × indicador",
        ]
        situacoes = sorted(set(self.anual["status_cobertura"]))
        contagem = self.anual.groupby(["indicador", "status_cobertura"]).size().unstack(fill_value=0)
        partes.append(tabela(
            [(ind, *(int(contagem.loc[ind].get(s, 0)) for s in situacoes)) for ind in contagem.index],
            ["Indicador", *situacoes],
        ))
        anos = self.anual[self.anual["meses_esperados"] > 0].groupby(["ano", "indicador"]).agg(
            esperados=("meses_esperados", "max"),
            municipios_completos=("status_cobertura", lambda s: int((s == "completo").sum())),
            municipios_incompletos=("status_cobertura", lambda s: int((s == "incompleto").sum())),
            municipios_sem_registros=("status_cobertura", lambda s: int((s == "sem_registros").sum())),
        ).reset_index()
        partes += [
            "### Anos com disponibilidade municipal",
            tabela(anos.astype({"ano": str}).itertuples(index=False), ["Ano", "Indicador", "Meses esperados", "Municípios completos",
                                                  "Municípios incompletos", "Municípios sem registros"]),
            "## Lacunas temporais",
            "Combinações município × mês dentro da disponibilidade da série, sem observação publicada. "
            "Não foram preenchidas. \"Lacuna sistêmica\" indica um mês em que a fonte publicou menos municípios "
            "(no país inteiro) que nos meses vizinhos, ou seja, uma falha da publicação e não do município.",
            tabela(ausencias, ["Indicador", "Código IBGE", "Município", "Mês", "Lacuna sistêmica da fonte"])
            if ausencias else "Nenhuma.",
        ]
        for serie in SERIES_MUNICIPAIS:
            lacunas = self._ultima(serie.codigo).get("lacunas_sistemicas") or []
            partes.append(f"- `{serie.codigo}`: meses com lacuna sistêmica na fonte: {', '.join(lacunas) or 'nenhum'}.")
        partes += [
            "Arquivos detalhados: `data/reports/cobertura_municipio_ano_indicador.csv` (município × ano × indicador) e "
            "`data/reports/cobertura_municipio_mes_indicador.csv` (município × mês × indicador, com o status de cada mês).",
        ]
        return partes

    def _secao_erros(self) -> list[str]:
        falhas = [
            (e.get("id"), e.get("status"), nome, ((e.get("resumo") or {}).get("tarefas") or {}).get(nome, {}).get("erro"))
            for e in self.execucoes
            for nome in (e.get("pendentes") or [])
        ] + [
            (e.get("id"), e.get("status"), "(execução inteira)", e.get("erro"))
            for e in self.execucoes
            if e.get("status") == "interrompida"
        ]
        tarefas = self.estado.get("tarefas", {})
        pendentes = [(n, t.get("status"), t.get("erro")) for n, t in tarefas.items() if t.get("status") != "concluida"]
        andamento = self.estado.get("execucao_em_andamento")
        historico = [
            (e.get("id"), e.get("modo"), e.get("status"), e.get("retomadas", 0), e.get("finalizada_em") or e.get("registrado_em"))
            for e in self.execucoes
        ]
        return [
            "## Execuções de coleta",
            "Cada linha é uma tentativa registrada. \"Retomadas\" conta quantas vezes a execução foi retomada a "
            "partir do checkpoint após uma interrupção, inclusive quedas abruptas do processo, que não deixam registro próprio.",
            tabela(historico, ["Execução", "Modo", "Status", "Retomadas", "Registrada em"]) if historico else "Nenhuma.",
            "## Erros de coleta",
            tabela(falhas, ["Execução", "Status", "Tarefa", "Erro"]) if falhas else
            "Nenhuma falha registrada.",
            "## Pendências",
            (f"Execução **{andamento['id']}** ainda em andamento/incompleta. Tarefas pendentes:\n\n"
             + tabela(pendentes, ["Tarefa", "Status", "Erro"])) if andamento else
            "Nenhuma pendência de coleta: a última execução concluiu todas as tarefas.",
            "Limitações da fonte (não são pendências de coleta): não há dados municipais antes de 2020-01 no "
            "IpeaData; não há estoque de empregos por município (taxas não calculáveis); as séries municipais são "
            "\"sem ajuste\".",
        ]

    # --- Validação da etapa 1 ----------------------------------------------------

    def relatorio_validacao(self) -> str:
        agora = agora_utc()
        partes = [
            "# Relatório de validação — Etapa 1",
            f"Gerado automaticamente em {agora} por `python -m scripts.gerar_relatorio`. Não edite à mão.",
        ]
        v = self.validacao
        if not v:
            partes.append("**Validação não executada.** Rode `python -m scripts.validar_dados`.")
        else:
            partes += [
                f"## Resultado: **{v['situacao'].upper()}**",
                "\n".join(f"- [CRÍTICO] {p}" for p in v["problemas_criticos"]) or "Nenhum problema crítico.",
                "## Integridade dos arquivos",
                f"{v['integridade_arquivos']['arquivos_verificados']} arquivos processados conferidos por SHA-256 "
                f"(manifesto `data/processed/manifesto.json`). Ausentes: {len(v['integridade_arquivos']['ausentes'])}; "
                f"alterados: {len(v['integridade_arquivos']['sha256_divergente'])}.",
                "## Verificações por série",
                tabela(
                    [
                        (c, i["campos"]["observacoes"], f"{i['campos']['periodo'][0]} a {i['campos']['periodo'][1]}",
                         i["duplicados"]["linhas_duplicadas"], i["campos"]["valores_nulos"], i["campos"]["valores_negativos"],
                         i["campos"]["datas_fora_do_primeiro_dia"],
                         "ok" if i["brutos"].get("verificado") and not i["brutos"].get("divergentes") else "não verificado",
                         (i.get("territorios") or {}).get("registros_de_outra_uf"),
                         len((i.get("territorios") or {}).get("codigos_fora_do_cadastro_ipeadata", [])) if i.get("territorios") else None)
                        for c, i in v["series"].items()
                    ],
                    ["Série", "Observações", "Período", "Duplicadas", "Nulos", "Negativos", "Datas inválidas",
                     "SHA-256 dos brutos", "Outra UF", "Fora da lista oficial"],
                ),
                "## Consistência entre níveis e séries",
                "Diferenças aqui são **documentadas, não corrigidas**: refletem a forma como a fonte publica.",
                self._tabela_consistencia(v["consistencia"]),
                "## Painel município × mês",
                f"{v['painel']['linhas']} linhas (esperadas {v['painel']['linhas_esperadas']}); duplicadas: "
                f"{v['painel']['duplicados']}. Situação das admissões: {v['painel']['situacao_admissoes']}. "
                f"Situação dos desligamentos: {v['painel']['situacao_desligamentos']}.",
                "## Indicadores calculáveis",
                tabela([(k, val) for k, val in v["indicadores"].items()], ["Indicador", "Calculável / observação"]),
            ]
        partes.append("## Testes automatizados")
        if self.pytest:
            t = self.pytest
            partes.append(
                f"Resultado de `pytest` lido de `data/reports/pytest.xml` (executado em {t['executado_em']}): "
                f"**{t['total']} testes, {t['falhas']} falhas, {t['erros']} erros, {t['pulados']} pulados** "
                f"em {t['tempo_s']} s."
                + (f"\n\nCasos com falha: {', '.join(t['casos_com_falha'])}" if t["casos_com_falha"] else "")
            )
        else:
            partes.append("Sem resultado registrado. Rode `pytest --junitxml=data/reports/pytest.xml`.")
        return "\n\n".join(partes) + "\n"

    @staticmethod
    def _tabela_consistencia(consistencia: dict[str, Any]) -> str:
        linhas = []
        for grupo, itens in consistencia.items():
            if not isinstance(itens, dict):
                continue
            for nome, comp in itens.items():
                if isinstance(comp, dict) and "meses_comparados" in comp:
                    linhas.append((f"{grupo} / {nome}", comp["meses_comparados"], comp["meses_divergentes"],
                                   comp["maior_diferenca_absoluta"], comp["diferenca_media_percentual"]))
        sobre = consistencia.get("caged_tradicional_vs_novo_caged")
        texto = tabela(linhas, ["Comparação", "Meses comparados", "Meses divergentes", "Maior diferença absoluta",
                                "Diferença média (%)"])
        if sobre:
            texto += (f"\n\nCAGED tradicional ({sobre['tradicional'][0]} a {sobre['tradicional'][1]}) e Novo Caged "
                      f"({sobre['novo_caged'][0]} a {sobre['novo_caged'][1]}): {sobre['meses_sobrepostos']} meses "
                      f"sobrepostos. Meses faltantes no CAGED tradicional: "
                      + "; ".join(f"`{c}`: {', '.join(m) or 'nenhum'}" for c, m in sobre["meses_faltantes_tradicional"].items())
                      + ".")
        return texto

    # --- Modelo de dados (preparação para PostgreSQL) ---------------------------------

    @staticmethod
    def modelo_dados() -> str:
        def colunas(definicao: tuple[esquema.Coluna, ...]) -> str:
            return tabela(
                [(f"`{c.nome}`", c.tipo_pandas, c.tipo_postgres, "sim" if c.anulavel else "não", c.descricao)
                 for c in definicao],
                ["Coluna", "Tipo (pandas)", "Tipo PostgreSQL sugerido", "Anulável", "Descrição"],
            )

        chave = ", ".join(f"`{c}`" for c in esquema.CHAVE_OBSERVACAO)
        return "\n\n".join([
            "# Modelo dos arquivos processados (origem da carga no PostgreSQL)",
            "Gerado a partir de `coleta/esquema.py` por `python -m scripts.gerar_relatorio`. Descreve os arquivos de "
            "`data/processed`, que são a entrada do importador. O banco implementado na etapa 2 está em "
            "[modelagem_banco.md](modelagem_banco.md).",
            "## Entidades recomendadas",
            tabela(
                [
                    ("municipio", "`data/processed/consolidado/municipios.csv`", "`cod_ibge`",
                     "Cadastro de municípios do IpeaData (entidade Territorios)"),
                    ("fonte_dados", "`data/processed/consolidado/fontes.csv`", "`fonte`", "IpeaData (acesso) e MTE/Caged (origem estatística, não acessada)"),
                    ("serie", "`data/processed/consolidado/series.csv`", "`serie_codigo`",
                     "Metadados, metodologia, disponibilidade e última carga de cada série"),
                    ("observacao", "`data/processed/<indicador>/ipeadata/<SERIE>/ano=AAAA.csv`", chave,
                     "Fato: uma linha por série × território × mês (municípios do MA)"),
                    ("observacao (agregados)", "`data/processed/agregados/ipeadata/<SERIE>.csv` e "
                     "`data/processed/referencia_nacional/ipeadata/<SERIE>.csv`", chave,
                     "Mesma estrutura; nível estado/brasil. Nunca misturado com o nível municipal"),
                    ("execucao_coleta", "`data/processed/consolidado/execucoes.csv` e `data/checkpoints/execucoes.jsonl`",
                     "`execucao_id`", "Rastreabilidade: quando, em que modo e com que resultado"),
                ],
                ["Entidade", "Arquivo de origem", "Chave natural", "Conteúdo"],
            ),
            "Relacionamentos: `observacao.serie_codigo` → `serie`; `observacao.cod_ibge` → `municipio` (quando "
            "`nivel_territorial = 'municipio'`); `observacao.execucao_id` → `execucao_coleta`; `serie.fonte` → `fonte_dados`.",
            "## Observação (tabela de fatos)",
            f"Chave natural: ({chave}). `serie_codigo` já identifica indicador e metodologia; nível e código territorial "
            "evitam colisão entre município, UF e Brasil no mesmo mês. Recomenda-se `UNIQUE` sobre essas colunas.",
            colunas(esquema.OBSERVACAO),
            "## Município",
            colunas(esquema.MUNICIPIO),
            "## Painel município × mês (visão derivada)",
            "`data/processed/consolidado/painel_municipal_mensal.csv` é derivado das observações (grade completa com "
            "situação de cada mês e saldo). Na etapa 2 pode ser uma *view* em vez de uma tabela.",
            colunas(esquema.PAINEL),
            "Situações possíveis (`status_*`):",
            tabela([(f"`{k}`", v) for k, v in esquema.STATUS_OBSERVACAO.items()], ["Situação", "Significado"]),
            "## Regras para a carga",
            "\n".join([
                "- **Formato:** CSV UTF-8, separador vírgula, cabeçalho, datas `AAAA-MM-DD`, sem índice. Compatível com "
                "`COPY ... WITH (FORMAT csv, HEADER true)`.",
                "- **Texto vazio** significa \"não se aplica\" (ex.: `cod_ibge` do Brasil); **número vazio** significa "
                "\"não publicado\". Nunca carregar vazio como zero.",
                "- **Lotes:** uma partição por série e ano (~2,6 mil linhas por série/ano no nível municipal).",
                "- **Deduplicação:** `INSERT ... ON CONFLICT (chave natural) DO UPDATE` somente quando `valor` mudou; os "
                "arquivos já não têm chaves repetidas (validado por `scripts.validar_dados`).",
                "- **Atualização:** recarregar apenas as partições listadas no `manifesto.json` com `execucao_id` "
                "posterior à última carga no banco.",
                "- **Integridade:** conferir o SHA-256 de cada arquivo contra `data/processed/manifesto.json` antes da carga.",
                "- **Proveniência:** manter `arquivo_bruto`, `coletado_em_utc`, `serie_atualizada_em` e `execucao_id` na "
                "tabela de fatos.",
                "- **Metodologias:** nunca somar ou emendar observações de `metodologia` diferente.",
            ]),
        ]) + "\n"

    def gerar(self) -> dict[str, Path]:
        destinos = {
            "cobertura_historica": self.dirs.docs / "cobertura_historica.md",
            "relatorio_validacao": self.dirs.docs / "relatorio_validacao_etapa1.md",
            "modelo_dados": self.dirs.docs / "modelo_dados.md",
        }
        self.dirs.docs.mkdir(parents=True, exist_ok=True)
        destinos["cobertura_historica"].write_text(self.cobertura_historica(), encoding="utf-8")
        destinos["relatorio_validacao"].write_text(self.relatorio_validacao(), encoding="utf-8")
        destinos["modelo_dados"].write_text(self.modelo_dados(), encoding="utf-8")
        return destinos
