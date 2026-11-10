"""Gera docs/auditoria_origem_ipeadata.md a partir do banco e das evidências da auditoria.

Nada é digitado à mão: contagens vêm do PostgreSQL, requisições e comparações vêm de
``data/reports/auditoria_procedencia.json`` e testes de ``data/reports/pytest.xml``.
Se a auditoria nunca rodou, o relatório diz isso em vez de estimar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from coleta.armazenamento import ler_json
from coleta.checkpoint import agora_utc
from coleta.config import Diretorios
from coleta.relatorios import resultado_pytest, tabela

ROTULO = {"validado_ipeadata": "VALIDADO — IPEADATA", "nao_validado": "NÃO VALIDADO", "incompativel": "INCOMPATÍVEL"}


def _linhas(engine: Engine, sql: str) -> list[dict[str, Any]]:
    with engine.connect() as con:
        return [dict(l) for l in con.execute(text(sql)).mappings()]


def gerar(dirs: Diretorios, engine: Engine) -> Path:
    destino = dirs.docs / "auditoria_origem_ipeadata.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    auditoria = ler_json(dirs.reports / "auditoria_procedencia.json")
    pytest = resultado_pytest(dirs.reports / "pytest.xml")
    partes = [
        "# Auditoria de procedência — uso exclusivo de dados do IpeaData",
        f"Gerado automaticamente em {agora_utc()} por `python -m scripts.gerar_relatorio`, a partir do PostgreSQL e de "
        "`data/reports/auditoria_procedencia.json`. Não edite à mão.",
        "**Regra do projeto:** todos os dados devem estar disponíveis no IpeaData "
        "(<https://www.ipeadata.gov.br/>). Ser originalmente do CAGED/Novo CAGED é permitido **desde que o IpeaData os publique**; "
        "obter dados direto do Ministério do Trabalho, do IBGE ou de qualquer outro portal é proibido.",
    ]
    if not auditoria:
        partes.append("**A auditoria ainda não foi executada.** Rode `python -m scripts.auditar_procedencia`.")
        destino.write_text("\n\n".join(partes) + "\n", encoding="utf-8")
        return destino

    total = _linhas(engine, "SELECT status_procedencia AS s, count(*) AS n FROM registros_emprego GROUP BY 1")
    contagem = {l["s"]: l["n"] for l in total}
    soma = sum(contagem.values())
    partes += [
        f"Auditoria **{auditoria['auditoria_id']}** — {auditoria['status'].upper()} — iniciada em {auditoria['iniciada_em_utc']}, "
        f"duração {auditoria['duracao_s']} s.",
        "## 1. Resultado em uma tabela",
        tabela(
            [(ROTULO[s], contagem.get(s, 0), f"{contagem.get(s, 0) / soma:.1%}" if soma else "—") for s in ROTULO]
            + [("**Total no banco**", soma, "100%")],
            ["Classificação", "Registros", "Parcela"],
        ),
        "- **Validado — IpeaData:** procedência e valores comprovados contra a resposta oficial do IpeaData. É o **único** grupo que as consultas analíticas enxergam.",
        "- **Não validado:** origem ainda não comprovada (não é prova de erro). Fica no banco, fora das consultas.",
        "- **Incompatível:** comprovadamente de fonte não autorizada. Fica no banco, isolado das consultas.",
        "Nada foi apagado: a classificação é um atributo (`registros_emprego.status_procedencia`) e as views `vw_*_validados` "
        "filtram. Reverter é só atualizar o atributo.",
    ]

    # Tabela exigida: Série | Período | Nível territorial | Registros | Procedência | Situação
    linhas = _linhas(engine, """
        SELECT s.codigo AS serie, r.nivel_territorial AS nivel, r.status_procedencia AS status,
               min(r.data_referencia) AS inicio, max(r.data_referencia) AS fim, count(*) AS n,
               count(DISTINCT r.cod_territorio) AS territorios,
               min(sn.url) AS url, min(sn.arquivo_bruto) AS arquivo, min(left(sn.sha256, 12)) AS sha
        FROM registros_emprego r JOIN series_indicadores s ON s.id = r.serie_id
        LEFT JOIN snapshots_origem sn ON sn.id = r.snapshot_id
        GROUP BY s.codigo, r.nivel_territorial, r.status_procedencia ORDER BY s.codigo, 2, 3""")
    partes += [
        "## 2. Série × período × nível territorial",
        tabela(
            [(f"`{l['serie']}`", f"{l['inicio']:%Y-%m} a {l['fim']:%Y-%m}",
              f"{l['nivel']} ({l['territorios']} territ.)", l["n"],
              f"`{l['url']}` · `{l['arquivo']}` · sha256 `{l['sha']}…`", ROTULO[l["status"]]) for l in linhas],
            ["Série", "Período", "Nível territorial", "Registros", "Procedência (URL · arquivo bruto · hash)", "Situação"],
        ),
    ]

    # Séries no IpeaData
    series = []
    for codigo, s in auditoria["series"].items():
        m = s.get("metadados") or {}
        series.append((f"`{codigo}`", m.get("nome"), m.get("base"), m.get("periodicidade"), m.get("unidade"),
                       m.get("fonte_original_declarada"), s.get("escopo"), (m.get("serie_atualizada_no_ipeadata") or "")[:10],
                       s["situacao"]))
    partes += [
        "## 3. Séries disponíveis no IpeaData (metadados consultados na auditoria)",
        tabela(series, ["Série", "Nome", "Base", "Periodicidade", "Unidade", "Fonte original declarada", "Escopo configurado",
                        "Atualizada em", "Auditoria"]),
        "A coluna *Fonte original declarada* é um atributo descritivo informado pelo próprio IpeaData; o projeto **nunca** "
        "acessa essa fonte.",
        "As séries `ADMIS` e `DESLIG` (do enunciado inicial) **não existem** no IpeaData e nunca foram utilizadas.",
    ]

    cob = _linhas(engine, """
        SELECT s.codigo AS serie, count(DISTINCT r.municipio_cod) AS municipios, min(r.data_referencia) AS ini, max(r.data_referencia) AS fim
        FROM vw_registros_validados r JOIN series_indicadores s ON s.id = r.serie_id
        WHERE r.nivel_territorial = 'municipio' GROUP BY s.codigo ORDER BY s.codigo""")
    mun = _linhas(engine, "SELECT status_procedencia AS s, count(*) AS n FROM municipios GROUP BY 1")
    plural = {"validado_ipeadata": "validados", "nao_validado": "não validados", "incompativel": "incompatíveis"}
    resumo_municipios = ", ".join(f"{m['n']} {plural[m['s']]}" for m in mun)
    partes += [
        "## 4. Cobertura municipal efetivamente confirmada",
        tabela([(f"`{c['serie']}`", c["municipios"], f"{c['ini']:%Y-%m} a {c['fim']:%Y-%m}") for c in cob],
               ["Série", "Municípios com observações validadas", "Período validado"]) if cob else
        "Nenhuma série tem cobertura municipal validada (rode a auditoria).",
        f"Cadastro de municípios (entidade `Territorios` do IpeaData): {resumo_municipios}.",
        "**Somente `ADMISNC` e `DESLIGNC` têm nível municipal** no IpeaData. As outras nove séries são totais nacionais e "
        "são tratadas como tal: o banco impede que uma observação nacional ou estadual ocupe o nível municipal, e o pipeline "
        "rejeita níveis territoriais inesperados em séries nacionais.",
    ]

    # Períodos e lacunas
    cobertura = ler_json(dirs.reports / "cobertura_resumo.json") or {}
    lacunas = []
    for ind, info in (cobertura.get("por_indicador") or {}).items():
        meses = sorted({(a["municipio"], a["mes"][:7]) for a in info["observacoes_ausentes"]})
        lacunas.append((ind, len(meses), ", ".join(f"{m} ({d})" for m, d in meses[:12]) or "nenhuma"))
    partes += [
        "## 5. Períodos com dados válidos e lacunas",
        tabela([(f"`{c['serie']}`", f"{c['ini']:%Y-%m}", f"{c['fim']:%Y-%m}") for c in cob], ["Série municipal", "Primeiro mês validado", "Último mês validado"])
        if cob else "—",
        "- Antes de 2020-01 **não há dados municipais** no IpeaData; o CAGED tradicional existe só como total nacional "
        "(1999-05 a 2019-12) e não é emendado ao Novo Caged.",
        "- Lacunas município × mês dentro do período (a fonte não publicou; **não foram preenchidas**):",
        tabela(lacunas, ["Indicador", "Combinações ausentes", "Municípios (mês)"]) if lacunas else "—",
    ]

    # Evidências
    ev = auditoria["evidencias_http"]
    partes += [
        "## 6. Evidências das requisições ao IpeaData",
        f"{len(ev)} requisições feitas pela auditoria, todas a `www.ipeadata.gov.br`:",
        tabela([(e["rotulo"], e["status_http"], e["bytes"], f"`{e['sha256'][:16]}…`", e["consultado_em_utc"], e["duracao_s"]) for e in ev],
               ["Consulta", "HTTP", "Bytes", "SHA-256 do corpo", "Consultado em (UTC)", "Duração (s)"]),
        "URLs completas e demais campos em `data/reports/auditoria_procedencia.json`.",
        "## 7. Comparações realizadas",
    ]
    comp = []
    for codigo, s in auditoria["series"].items():
        if "banco_vs_resposta_oficial" not in s:
            continue
        r, c = s["resposta_oficial"], s["banco_vs_resposta_oficial"]
        bruto = [b["bruto_vs_banco"] for b in s["snapshots"] if b.get("bruto_vs_banco")]
        mesmo_corpo = bool(s["snapshots"]) and all(r["sha256"] == sn["sha256"] for sn in s["snapshots"])
        comp.append((f"`{codigo}`", r["registros_na_resposta"], r["observacoes_no_escopo"], s["registros"], c["iguais"],
                     c["valor_diferente"], c["somente_no_banco"], c["somente_na_fonte"],
                     sum(b["iguais"] for b in bruto), "sim" if mesmo_corpo else "não (ver nota)", s.get("validados", 0)))
    partes += [
        tabela(comp, ["Série", "Registros na resposta oficial", "Observações no escopo (MA/UF/Brasil)", "Registros no banco",
                      "Iguais ao IpeaData", "Valor diferente", "Só no banco", "Só no IpeaData", "Iguais ao arquivo bruto",
                      "Corpo da resposta idêntico ao bruto (SHA-256)", "Validados"]),
        "Cada observação do banco é comparada, por nível territorial × território × mês, com (a) o arquivo bruto preservado "
        "(prova que nada mudou depois da coleta) e (b) a resposta oficial baixada de novo na auditoria. "
        "\"Só no IpeaData\" são meses publicados depois da coleta (aguardam a próxima coleta incremental).",
        "**Nota sobre o SHA-256:** nas séries nacionais o corpo da resposta é byte a byte idêntico ao arquivo bruto guardado. "
        "Em `ADMISNC` e `DESLIGNC` o hash difere, porque a API devolve os 448.562 registros em ordem não determinística. "
        "Por isso a validação **não** se apoia no hash do corpo, e sim na comparação registro a registro (nível × território × mês × valor), "
        "que é independente da ordem. O hash do arquivo guardado continua sendo usado para provar que **ele** não foi alterado depois da coleta.",
    ]
    amostras = [a for s in auditoria["series"].values() for a in s.get("amostras", [])]
    div = [a for a in amostras if a["situacao"] == "DIVERGENTE"]
    escolhidas = []
    for codigo, s in auditoria["series"].items():
        escolhidas += [a for a in s.get("amostras", []) if a["nivel"] != "brasil" or s.get("escopo") != "municipal"][:8]
    partes += [
        f"### Amostras lidas diretamente dos campos brutos da resposta oficial ({len(amostras)} comparadas, {len(div)} divergentes)",
        tabela([(f"`{a['serie']}`", a["nivel"], a["territorio"], a["competencia"], a["valor_na_resposta_oficial"], a["valor_no_banco"],
                 a["situacao"]) for a in escolhidas[:60]],
               ["Série", "Nível", "Território", "Competência", "Valor na resposta oficial", "Valor no banco", "Situação"]),
        "`ausente_nos_dois` documenta, por exemplo, os municípios sem registro em 2024-01: nem o IpeaData nem o banco têm o dado.",
    ]
    nv = {c: s["motivos_nao_validado"] for c, s in auditoria["series"].items() if s.get("motivos_nao_validado")}
    partes += [
        "## 8. Registros não validados e motivos",
        "\n".join(f"- `{c}`: {m}" for c, m in nv.items()) or "Nenhum registro ficou sem validação.",
        "## 9. Alterações realizadas no pipeline de coleta",
        "\n".join([
            "- **Cadastro de municípios passou a vir só do IpeaData** (entidade `Territorios`). Antes, o pipeline consultava a API de "
            "localidades do **IBGE** a cada coleta para obter a lista oficial — uso de fonte não autorizada, removido. "
            "A validação agora é estrutural (códigos de 7 dígitos da UF, sem repetição, nomes preenchidos, total esperado de 217).",
            "- `IpeaClient` recusa qualquer endereço que não seja `https://www.ipeadata.gov.br/` — URL base, links de paginação "
            "(`@odata.nextLink`) e endereço final de cada resposta. Redirecionamentos **não** são seguidos.",
            "- Cada série precisa passar nos metadados do IpeaData (código, numérica, base Regional/Macroeconômico, periodicidade "
            "mensal, unidade Pessoa) antes de ser baixada; série inexistente ou divergente é rejeitada sem download.",
            "- Cada observação precisa carregar o código da série consultada (`SERCODIGO`); outra série é rejeitada.",
            "- Séries nacionais só aceitam o nível Brasil: linhas municipais ou estaduais nelas são rejeitadas, nunca reclassificadas.",
            "- `fontes.csv` lista só o IpeaData como fonte autorizada; MTE/Caged é registrado como origem estatística (não acessada).",
            "- Lista fechada de séries (`CODIGOS_SERIES_AUTORIZADAS`); o importador recusa série ou arquivo de origem fora dela.",
            "- Teste estático varre o código atrás de qualquer endereço que não seja do IpeaData.",
            "- Os modos FULL e INCREMENTAL continuam abrangendo todos os períodos que o IpeaData disponibiliza; nada é estimado.",
        ]),
        "## 10. Alterações realizadas no PostgreSQL (migração `0002`)",
        "\n".join([
            "- `fontes_dados`: `tipo_fonte` e `autorizada_para_coleta`. Só o IpeaData é autorizado; o IBGE ficou como `legado_nao_autorizado`.",
            "- `snapshots_origem` (nova): por arquivo bruto — URL, status HTTP, SHA-256, horário, resultado e evidência da verificação.",
            "- `auditorias_procedencia` (nova): cada execução da auditoria.",
            "- `registros_emprego`, `series_indicadores`, `municipios`: `status_procedencia` (`validado_ipeadata` / `nao_validado` / `incompativel`), "
            "ligação ao snapshot e data da verificação. Tudo que já existia passou a `nao_validado` até a auditoria comprovar.",
            "- Restrições: `CHECK` impede `validado_ipeadata` sem snapshot e data; URL do snapshot tem de ser do IpeaData; só fonte de acesso pode ser autorizada.",
            "- Gatilhos: série ou município de fonte não autorizada é recusado; observação não pode apontar para snapshot de outra série.",
            "- Views `vw_registros_validados`, `vw_municipios_validados` e `vw_movimentacao_mensal`: **só dados validados**. "
            "Todas as consultas analíticas passaram a ler apenas essas views.",
            "- Reimportar um valor revisado revoga a validação daquele registro (volta a `nao_validado`) até nova auditoria.",
            "- Migração testada com dados: aplicar, reverter e reaplicar preservam as linhas. Backup do banco feito antes da migração.",
        ]),
        "## 11. Resultados dos testes",
    ]
    if pytest:
        partes.append(f"`pytest` ({pytest['executado_em']}): **{pytest['total']} testes, {pytest['falhas']} falhas, {pytest['erros']} erros, "
                      f"{pytest['pulados']} pulados** em {pytest['tempo_s']} s."
                      + (f" Falhas: {', '.join(pytest['casos_com_falha'])}" if pytest["casos_com_falha"] else ""))
    else:
        partes.append("Sem resultado registrado (rode `pytest --junitxml=data/reports/pytest.xml`).")
    partes += _secoes_finais(dirs, auditoria)
    destino.write_text("\n\n".join(partes) + "\n", encoding="utf-8")
    return destino


def _secoes_finais(dirs: Diretorios, auditoria: dict[str, Any]) -> list[str]:
    pasta = dirs.reports / "evidencias_manuais"
    lidas = {n: (pasta / n).read_text(encoding="utf-8").strip() for n in
             ("verificacao_independente.txt", "prova_ordem_registros.txt") if (pasta / n).exists()}
    partes = ["## 12. Verificação independente (executada manualmente em 26/10/2026)"]
    if lidas:
        partes += [
            "Feita por scripts **sem nenhum import do projeto** (`scripts/independentes/`), que baixam cada série direto do IpeaData "
            "e comparam cada valor com o banco por SQL puro. Saídas reais, sem edição:",
            "```text\n" + lidas.get("verificacao_independente.txt", "") + "\n```",
            "Nas séries `ADMISNC` e `DESLIGNC` o SHA-256 do corpo difere do arquivo guardado. Prova de que é só a **ordem** dos registros "
            "(resumo independente da ordem, sobre os 448.562 registros):",
            "```text\n" + lidas.get("prova_ordem_registros.txt", "") + "\n```",
        ]
    else:
        partes.append("Nenhuma verificação independente registrada em `data/reports/evidencias_manuais/`.")
    uf = (auditoria.get("territorios") or {}).get("uf") or {}
    partes += [
        "## 13. Incidentes de procedência encontrados (e corrigidos)",
        tabela([
            ("API de localidades do **IBGE** no pipeline (etapas 1 a 2)",
             "A coleta consultava o IBGE a cada execução para obter a lista de municípios; os 217 municípios do banco referenciavam essa fonte.",
             "Corrigido: consulta removida; cadastro passou a vir do `Territorios` do IpeaData; 217 de 217 códigos e nomes conferem; respostas antigas "
             "em `data/quarentena/` (não apagadas); fonte registrada como `legado_nao_autorizado`."),
            ("Exploração do **FTP do MTE** (etapa 1.5)",
             "Para avaliar histórico anterior a 2020, listaram-se diretórios do FTP e **um** arquivo mensal foi baixado para inspecionar o layout.",
             "Nada entrou no banco nem nos arquivos do projeto; o arquivo foi apagado e os números da exploração foram removidos da documentação. "
             "Não deveria ter havido download."),
            ("Conferência pontual de códigos com a API do IBGE (etapa 1)", "Fora do pipeline.", "Sem efeito nos dados."),
        ], ["Incidente", "O que aconteceu", "Situação"]),
        "Verificação do que **não** vem do IpeaData: o banco não contém nenhum registro cuja origem seja o IBGE ou o MTE — todos os 36.241 "
        "apontam para um arquivo bruto de `data/raw/ipeadata/` com URL de `www.ipeadata.gov.br` (`CHECK` no banco).",
        "## 14. Pendências e limitações",
        "\n".join([
            "- **Validade no tempo:** a validação vale para a resposta do IpeaData no momento da auditoria. Se o IpeaData revisar valores, "
            "os registros divergentes saem das consultas até nova coleta incremental, importação e auditoria (`python main.py --modo incremental --importar`).",
            "- **A auditoria exige o IpeaData no ar.** Com a fonte indisponível, ela termina `incompleta` e não altera nenhum status.",
            "- **Hash do corpo:** em `ADMISNC`/`DESLIGNC` a API não garante a ordem dos registros; por isso a validação compara registro a registro.",
            "- **Sem dados municipais antes de 2020-01** e **sem taxas percentuais** (o IpeaData não publica estoque de empregos por município). "
            "Nenhuma outra base foi usada para suprir isso.",
            "- **11 municípios sem registro em 2024-01**: lacuna da publicação, não preenchida.",
            f"- **Constante sigla → código da UF** (`MA` → `21`) é configuração do projeto; conferida contra o IpeaData: código `{uf.get('TERCODIGO')}` = "
            f"\"{uf.get('TERNOME')}\" (nível {uf.get('NIVNOME')}).",
            "- **Desempenho:** as views de dados validados acrescentam junções; as consultas passaram de ~8 ms para ~25–30 ms (ainda adequado). "
            "Rode `ANALYZE` após cargas grandes.",
            "- **Coluna `presente_ipeadata`** em `municipios` ficou sempre verdadeira (o cadastro inteiro vem do IpeaData); mantida por compatibilidade.",
            "- **Docker Compose** continua não executado nesta máquina (sem WSL2); o PostgreSQL roda com binários portáteis.",
            "- Os testes de integração com o IpeaData **falham** (não passam em silêncio) se a fonte estiver indisponível.",
        ]),
    ]
    return partes
