"""Gera docs/relatorio_etapa2.md a partir dos artefatos reais da etapa 2.

Fontes: data/reports/verificacao_banco.json, reconciliacao_postgresql.json,
importacoes/*.json e pytest.xml. O estado do Docker é detectado na hora.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from coleta.armazenamento import ler_json
from coleta.checkpoint import agora_utc
from coleta.config import Diretorios
from coleta.relatorios import resultado_pytest, tabela


def estado_docker() -> str:
    if not shutil.which("docker"):
        return "Docker não instalado."
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Docker instalado, mas não respondeu ({exc})."
    if r.returncode == 0 and r.stdout.strip():
        return f"Docker Engine {r.stdout.strip()} disponível."
    return "Docker instalado, mas o daemon não está ativo: " + (r.stderr.strip().splitlines() or ["sem detalhes"])[-1][:200]


def _importacoes(dirs: Diretorios) -> list[dict[str, Any]]:
    pasta = dirs.reports / "importacoes"
    return [ler_json(p) for p in sorted(pasta.glob("importacao_*.json"))] if pasta.exists() else []


def gerar(dirs: Diretorios) -> Path:
    v = ler_json(dirs.reports / "verificacao_banco.json")
    r = ler_json(dirs.reports / "reconciliacao_postgresql.json")
    importacoes = _importacoes(dirs)
    pytest = resultado_pytest(dirs.reports / "pytest.xml")
    partes = [
        "# Relatório da Etapa 2 — PostgreSQL",
        f"Gerado automaticamente em {agora_utc()} por `python -m scripts.gerar_relatorio` a partir de "
        "`data/reports/` (verificação, reconciliação, importações e testes). Não edite à mão.",
    ]
    if not v:
        partes.append("**Sem verificação registrada.** Rode `python -m scripts.verificar_banco`.")
        destino = dirs.docs / "relatorio_etapa2.md"
        destino.write_text("\n\n".join(partes) + "\n", encoding="utf-8")
        return destino

    m = v["migracao"]
    partes += [
        "## Ambiente",
        tabela([
            ("Servidor", v["conexao"]["versao"].split(",")[0]),
            ("Banco / usuário", f"{v['conexao']['banco']} / {v['conexao']['usuario']}"),
            ("Fuso do servidor", v["conexao"]["timezone"]),
            ("Migração Alembic", f"{m['revisao_atual']} (head: {m['revisao_head']}) — {'atualizada' if m['atualizada'] else 'DESATUALIZADA'}"),
            ("Docker (detectado agora)", estado_docker()),
        ], ["Item", "Valor"]),
        "## Objetos do banco",
        tabela([(t, n) for t, n in v["tabelas"].items()], ["Tabela", "Linhas"]),
        f"Restrições: {', '.join(f'{k}={n}' for k, n in v['restricoes'].items())}. Índices: {len(v['indices'])}. "
        f"Views: {', '.join(v['views'])}.",
        tabela([(t["tabela"], t["total"], t["indices"]) for t in v["tamanhos"]], ["Tabela", "Tamanho total", "Índices"]),
    ]

    partes.append("## Importações executadas")
    partes.append(tabela(
        [(i["id"], i["tipo"], i["status"], i["registros_lidos"], i["registros_validos"], i["registros_inseridos"],
          i["registros_atualizados"], i["registros_inalterados"], i["registros_rejeitados"], i["registros_ausentes_na_origem"],
          i["arquivos_processados"], i["arquivos_ignorados"]) for i in v["importacoes"]],
        ["ID", "Tipo", "Status", "Lidos", "Válidos", "Inseridos", "Atualizados", "Inalterados", "Rejeitados",
         "Ausentes na origem", "Arquivos proc.", "Arquivos ign."],
    ))
    full = next((i for i in importacoes if i["tipo"] == "FULL"), None)
    if full:
        t = full["totais"]
        partes.append(
            f"Carga histórica (importação {full['importacao_id']}, FULL, {full['duracao_s']} s): lidos {t['lidos']}, "
            f"válidos {t['validos']}, inseridos {t['inseridos']}, atualizados {t['atualizados']}, rejeitados {t['rejeitados']}. "
            f"Registros no banco após a carga: {sum(full['registros_no_banco'].values())}."
        )
    i = v["integridade"]
    partes += [
        f"Integridade: chaves naturais duplicadas = {i['chaves_naturais_duplicadas']}; municípios cadastrados = "
        f"{i['municipios_cadastrados']}; séries sem observações = {i['series_sem_observacao'] or 'nenhuma'}; "
        f"inconsistências registradas = {v['inconsistencias_por_tipo'] or 'nenhuma'}; revisões registradas = {v['revisoes_registradas']}.",
        "## Cobertura histórica por fonte, metodologia e indicador",
        tabela([(c["serie"], c["indicador"], c["metodologia"], c["escopo_territorial"], c["nivel_territorial"],
                 c["primeira_competencia"], c["ultima_competencia"], c["observacoes"], c["territorios"]) for c in v["cobertura"]],
               ["Série", "Indicador", "Metodologia", "Escopo", "Nível", "Primeira", "Última", "Observações", "Territórios"]),
        "Os 217 municípios estão cadastrados. Há dados municipais **somente a partir de 2020-01** (Novo Caged no IpeaData); "
        "o CAGED tradicional existe apenas como total nacional (1999-05 a 2019-12) e não é emendado ao Novo Caged.",
    ]

    if r:
        tt = r["totais"]
        partes += [
            f"## Reconciliação (arquivos processados → PostgreSQL): **{r['situacao'].upper()}**",
            tabela([
                ("Linhas", tt["linhas_origem"], tt["linhas_banco"]),
                ("Soma dos valores", tt["soma_origem"], tt["soma_banco"]),
                ("Municípios cadastrados", r["municipios"]["cadastro_origem"], r["municipios"]["cadastro_banco"]),
            ], ["Medida", "Origem", "Banco"]),
            f"Grupos série × ano comparados por contagem, soma e MD5 do conteúdo: {tt['grupos_serie_ano']} "
            f"(divergentes: {tt['grupos_divergentes']}). Chaves duplicadas no banco: {tt['chaves_duplicadas_no_banco']}.",
            tabela([(s["serie"], s["linhas_origem"], s["linhas_banco"], s["inicio"], s["fim"], s["grupos_divergentes"])
                    for s in r["por_serie"]], ["Série", "Linhas origem", "Linhas banco", "Início", "Fim", "Grupos divergentes"]),
            tabela([(str(a["ano"]), a["linhas_origem"], a["linhas_banco"]) for a in r["por_ano"]], ["Ano", "Linhas origem", "Linhas banco"]),
        ]
        for codigo, c in r["contagem_por_municipio"].items():
            dist = ", ".join(f"{qtd} municípios com {n} meses" for n, qtd in c["distribuicao_observacoes_por_municipio"].items())
            partes.append(f"- `{codigo}`: {c['municipios_com_observacoes_banco']} municípios com observações ({dist}). "
                          "Os 11 municípios com 79 meses correspondem à lacuna da fonte em 2024-01 (documentada na etapa 1.5).")
        for d in r["divergencias"]:
            partes.append(f"- Divergência {d['serie']}/{d['ano']}: só origem {d['somente_na_origem']}, só banco "
                          f"{d['somente_no_banco']}, valores diferentes {d['valores_diferentes']}.")

    exemplos = v.get("exemplos")
    if exemplos:
        ano = exemplos["ano_de_referencia"]
        tu = exemplos["totais_uf"]
        partes += [
            f"## Resultados das consultas (metodologia Novo Caged - sem ajuste; ano completo mais recente: {ano})",
            f"Última competência disponível: {exemplos['ultima_competencia']}.",
            f"Totais do Maranhão em {ano}: admissões {tu['admissoes_uf']}, desligamentos {tu['desligamentos_uf']}, "
            f"saldo {tu['saldo_uf']} (total oficial da UF); soma dos municípios: admissões {tu['admissoes_soma_municipios']}, "
            f"desligamentos {tu['desligamentos_soma_municipios']}.",
            "### Maiores saldos",
            tabela([(l["posicao"], l["municipio"], l["admissoes"], l["desligamentos"], l["saldo"]) for l in exemplos["ranking_saldo_maiores"]],
                   ["Posição", "Município", "Admissões", "Desligamentos", "Saldo"]),
            "### Menores saldos",
            tabela([(l["posicao"], l["municipio"], l["admissoes"], l["desligamentos"], l["saldo"]) for l in exemplos["ranking_saldo_menores"]],
                   ["Posição", "Município", "Admissões", "Desligamentos", "Saldo"]),
            "### Evolução anual do Maranhão (total oficial da UF)",
            tabela([(str(a["ano"]), a["admissoes"], a["desligamentos"], a["saldo"], a["meses_com_saldo"], "sim" if a["ano_completo"] else "não")
                    for a in exemplos["evolucao_anual_uf"]], ["Ano", "Admissões", "Desligamentos", "Saldo", "Meses", "Ano completo"]),
            f"Indicadores do período {ano}: {exemplos['indicadores_periodo']['municipios_saldo_positivo']} municípios com saldo "
            f"positivo, {exemplos['indicadores_periodo']['municipios_saldo_negativo']} negativo e "
            f"{exemplos['indicadores_periodo']['municipios_saldo_zero']} zero.",
        ]

    partes += [
        "## Desempenho (EXPLAIN ANALYZE)",
        tabela([(d["consulta"], d["tempo_execucao_ms"], ", ".join(d["indices_usados"]) or "—",
                 ", ".join(d["varreduras_sequenciais"]) or "—") for d in v.get("desempenho", [])],
               ["Consulta", "Tempo (ms)", "Índices usados", "Varredura sequencial em"]),
        "A tabela de fatos é sempre acessada por índice; varreduras sequenciais ocorrem só nas dimensões pequenas "
        "(séries e municípios), onde são a escolha correta. Com tempos dessa ordem e "
        f"{v['tabelas']['registros_emprego']} observações, **não há necessidade técnica** de materialized views nem de "
        "particionamento (que só compensa a partir de dezenas de milhões de linhas). Planos completos em "
        "`data/reports/verificacao_banco.json`.",
        "## Testes automatizados",
    ]
    if pytest:
        partes.append(f"`pytest` ({pytest['executado_em']}): **{pytest['total']} testes, {pytest['falhas']} falhas, "
                      f"{pytest['erros']} erros, {pytest['pulados']} pulados** em {pytest['tempo_s']} s."
                      + (f" Falhas: {', '.join(pytest['casos_com_falha'])}" if pytest["casos_com_falha"] else ""))
    else:
        partes.append("Sem resultado registrado (rode `pytest --junitxml=data/reports/pytest.xml`).")
    destino = dirs.docs / "relatorio_etapa2.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n\n".join(partes) + "\n", encoding="utf-8")
    return destino
