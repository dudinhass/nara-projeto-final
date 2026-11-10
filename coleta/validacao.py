"""Validações de qualidade sobre a base já persistida.

Separa problemas **críticos** (impedem o uso da base: arquivo corrompido,
chave duplicada, município fora da lista oficial, registro de outra UF) de
**observações** metodológicas (diferenças entre níveis ou entre séries que
são esperadas e precisam ser documentadas, não corrigidas).
"""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from coleta import esquema
from coleta.armazenamento import sha256_arquivo
from coleta.config import SERIES, SERIES_MUNICIPAIS, Diretorios, SerieConfig
from coleta.repositorio import RepositorioDados


def verificar_duplicados(df: pd.DataFrame, chaves: Iterable[str]) -> dict[str, Any]:
    chaves = list(chaves)
    duplicados = df[df.duplicated(subset=chaves, keep=False)]
    return {"chaves": chaves, "linhas_duplicadas": int(len(duplicados)), "exemplos": _registros(duplicados.head(10))}


def comparar_totais(
    detalhado: pd.DataFrame, agregado: pd.DataFrame, coluna: str = "valor", tolerancia: float = 0.0
) -> dict[str, Any] | None:
    """Compara, mês a mês, a soma do nível detalhado com o total agregado.

    Devolve ``None`` quando um dos lados não tem dados (não verificável).
    """
    if detalhado.empty or agregado.empty:
        return None
    soma = detalhado.groupby("data_referencia")[coluna].sum(min_count=1).rename("soma_detalhado")
    total = agregado.groupby("data_referencia")[coluna].sum(min_count=1).rename("valor_agregado")
    comparacao = pd.concat([soma, total], axis=1).dropna()
    comparacao["diferenca"] = comparacao["soma_detalhado"] - comparacao["valor_agregado"]
    divergentes = comparacao[comparacao["diferenca"].abs() > tolerancia]
    relativa = (comparacao["diferenca"] / comparacao["valor_agregado"].where(comparacao["valor_agregado"] != 0)) * 100
    return {
        "meses_comparados": int(len(comparacao)),
        "meses_divergentes": int(len(divergentes)),
        "maior_diferenca_absoluta": _numero(comparacao["diferenca"].abs().max()),
        "diferenca_media": _numero(comparacao["diferenca"].mean()),
        "diferenca_media_percentual": _numero(relativa.mean()),
        "exemplos_divergencia": _registros(divergentes.reset_index().head(5)),
    }


def verificar_territorios(obs: pd.DataFrame, oficiais: set[str], codigo_uf: str) -> dict[str, Any]:
    municipais = obs[obs["nivel_territorial"] == "municipio"]
    return {
        "observacoes_municipais": int(len(municipais)),
        "registros_de_outra_uf": int((~municipais["cod_ibge"].str.startswith(codigo_uf)).sum()),
        "codigos_fora_do_cadastro_ipeadata": sorted(set(municipais["cod_ibge"]) - oficiais),
        "codigos_malformados": int((~municipais["cod_ibge"].str.fullmatch(r"\d{7}")).sum()),
        "niveis_presentes": obs["nivel_territorial"].value_counts().to_dict(),
    }


def verificar_campos(obs: pd.DataFrame, serie_codigo: str, contagem: bool, raiz: Any) -> dict[str, Any]:
    """Valores, datas e campos de origem/metodologia de uma série."""
    obrigatorios = ["fonte", "fonte_original", "serie_codigo", "indicador", "metodologia", "periodicidade",
                    "unidade", "coletado_em_utc", "execucao_id", "arquivo_bruto"]
    brutos = set(obs["arquivo_bruto"])
    return {
        "observacoes": int(len(obs)),
        "valores_nulos": int(obs["valor"].isna().sum()),
        "valores_negativos": int((obs["valor"] < 0).sum()) if contagem else None,
        "datas_fora_do_primeiro_dia": int((obs["data_referencia"].dt.day != 1).sum()),
        "campos_de_origem_vazios": {c: int((obs[c] == "").sum()) for c in obrigatorios if (obs[c] == "").any()},
        "serie_codigo_divergente": int((obs["serie_codigo"] != serie_codigo).sum()),
        "arquivos_brutos_referenciados": len(brutos),
        "arquivos_brutos_inexistentes": sorted(b for b in brutos if b and not (raiz / b).exists()),
        "periodo": [
            obs["data_referencia"].min().date().isoformat() if len(obs) else None,
            obs["data_referencia"].max().date().isoformat() if len(obs) else None,
        ],
    }


def verificar_brutos(snapshot: dict[str, Any] | None, raiz: Any) -> dict[str, Any]:
    """Confere o SHA-256 dos brutos que deram origem à última carga."""
    if not snapshot:
        return {"verificado": False}
    divergentes = [
        arquivo for arquivo, sha in zip(snapshot["arquivos"], snapshot["sha256"])
        if not (raiz / arquivo).exists() or sha256_arquivo(raiz / arquivo, descomprimir=True) != sha
    ]
    return {"verificado": True, "arquivos": snapshot["arquivos"], "divergentes": divergentes}


def avaliar_indicadores(painel: pd.DataFrame, denominador_disponivel: bool = False) -> dict[str, Any]:
    tem_adm = bool(painel["admissoes"].notna().any())
    tem_desl = bool(painel["desligamentos"].notna().any())
    ambos = tem_adm and tem_desl
    municipios = painel["cod_ibge"].nunique()
    return {
        "total_admissoes": tem_adm,
        "total_desligamentos": tem_desl,
        "saldo_empregos": ambos,
        "evolucao_mensal": ambos and painel["data_referencia"].nunique() > 1,
        "evolucao_anual": ambos and painel["ano"].nunique() > 1,
        "comparacao_municipios": ambos and municipios > 1,
        "ranking_municipios": ambos and municipios > 1,
        "taxas_percentuais": denominador_disponivel,
        "observacao_taxas": (
            "Calculáveis com o denominador informado."
            if denominador_disponivel
            else "Não calculáveis: o IpeaData não oferece estoque de empregos formais por município "
            "compatível com o Novo Caged. Os totais são contagens absolutas e não devem ser "
            "apresentados como taxas."
        ),
    }


def validar_base(
    dirs: Diretorios,
    estado_checkpoint: dict[str, Any],
    codigo_uf: str,
    esperadas: Iterable[SerieConfig] | None = None,
) -> dict[str, Any]:
    """Executa todas as verificações e classifica o resultado.

    Toda série esperada (padrão: todas as configuradas) precisa ter dados.
    """
    repo = RepositorioDados(dirs)
    municipios = esquema.ler_csv(dirs.consolidado / "municipios.csv", esquema.MUNICIPIO)
    oficiais = set(municipios["cod_ibge"])
    tarefas = estado_checkpoint.get("tarefas", {})
    criticos: list[str] = []

    integridade = repo.verificar_manifesto()
    if integridade["ausentes"] or integridade["sha256_divergente"]:
        criticos.append("Arquivos processados ausentes ou alterados desde a gravação")

    series: dict[str, Any] = {}
    bases: dict[str, pd.DataFrame] = {}
    for serie in esperadas or SERIES.values():
        obs = repo.ler(serie)
        bases[serie.codigo] = obs
        ultima = (tarefas.get(f"serie:{serie.codigo}") or {}).get("ultima_conclusao") or {}
        info: dict[str, Any] = {
            "metodologia": serie.metodologia,
            "escopo": serie.escopo,
            "campos": verificar_campos(obs, serie.codigo, serie.indicador != "saldo", dirs.raiz),
            "duplicados": verificar_duplicados(obs, esquema.CHAVE_OBSERVACAO),
            "brutos": verificar_brutos(ultima.get("snapshot"), dirs.raiz),
        }
        if serie.escopo == "municipal":
            info["territorios"] = verificar_territorios(obs, oficiais, codigo_uf)
            terr = info["territorios"]
            if terr["registros_de_outra_uf"] or terr["codigos_fora_do_cadastro_ipeadata"] or terr["codigos_malformados"]:
                criticos.append(f"{serie.codigo}: observações fora do território validado")
        if info["duplicados"]["linhas_duplicadas"]:
            criticos.append(f"{serie.codigo}: chaves naturais duplicadas")
        if info["campos"]["valores_nulos"] or info["campos"]["valores_negativos"]:
            criticos.append(f"{serie.codigo}: valores nulos ou negativos armazenados")
        if info["campos"]["arquivos_brutos_inexistentes"] or info["brutos"].get("divergentes"):
            criticos.append(f"{serie.codigo}: rastreabilidade quebrada (bruto ausente ou alterado)")
        if obs.empty:
            criticos.append(f"{serie.codigo}: série sem observações armazenadas")
        series[serie.codigo] = info

    consistencia = _consistencia(bases, codigo_uf)
    painel = esquema.ler_csv(dirs.consolidado / "painel_municipal_mensal.csv", esquema.PAINEL)
    meses = painel["data_referencia"].nunique()
    painel_info = {
        "linhas": int(len(painel)),
        "linhas_esperadas": int(len(municipios) * meses),
        "duplicados": verificar_duplicados(painel, esquema.CHAVE_PAINEL)["linhas_duplicadas"],
        "situacao_admissoes": painel["status_admissoes"].value_counts().to_dict(),
        "situacao_desligamentos": painel["status_desligamentos"].value_counts().to_dict(),
        "saldo_sem_ambos_os_valores": int(
            (painel["saldo"].notna() & (painel["admissoes"].isna() | painel["desligamentos"].isna())).sum()
        ),
    }
    if painel_info["linhas"] != painel_info["linhas_esperadas"] or painel_info["duplicados"]:
        criticos.append("Painel municipal com grade incompleta ou duplicada")
    if painel_info["saldo_sem_ambos_os_valores"]:
        criticos.append("Saldo calculado sem admissões e desligamentos")

    return {
        "situacao": "aprovada" if not criticos else "reprovada",
        "problemas_criticos": criticos,
        "municipios": {"total": int(len(municipios)), "presentes_no_ipeadata": int(municipios["presente_ipeadata"].sum())},
        "integridade_arquivos": integridade,
        "series": series,
        "consistencia": consistencia,
        "painel": painel_info,
        "indicadores": avaliar_indicadores(painel),
    }


def _consistencia(bases: dict[str, pd.DataFrame], codigo_uf: str) -> dict[str, Any]:
    """Diferenças esperadas entre níveis e séries: documentadas, não corrigidas."""
    resultado: dict[str, Any] = {}
    nacional = lambda codigo: bases.get(codigo, pd.DataFrame())  # noqa: E731
    pares_nacionais = {"ADMISNC": "CAGED12_ADMISN12", "DESLIGNC": "CAGED12_DESLIGN12"}
    for serie in SERIES_MUNICIPAIS:
        obs = bases.get(serie.codigo, pd.DataFrame())
        if obs.empty:
            continue
        municipios = obs[obs["nivel_territorial"] == "municipio"]
        estado = obs[(obs["nivel_territorial"] == "estado") & (obs["cod_ibge"] == codigo_uf)]
        brasil = obs[obs["nivel_territorial"] == "brasil"]
        resultado[serie.codigo] = {
            "soma_municipios_vs_total_uf": comparar_totais(municipios, estado),
            "brasil_base_regional_vs_serie_nacional": comparar_totais(brasil, nacional(pares_nacionais[serie.codigo])),
        }

    def saldo_publicado(adm: str, desl: str, saldo: str) -> dict[str, Any] | None:
        a, d, s = nacional(adm), nacional(desl), nacional(saldo)
        if a.empty or d.empty or s.empty:
            return None
        calculado = a[["data_referencia", "valor"]].merge(d[["data_referencia", "valor"]], on="data_referencia")
        calculado["valor"] = calculado["valor_x"] - calculado["valor_y"]
        return comparar_totais(calculado, s)

    resultado["saldo_calculado_vs_publicado"] = {
        "novo_caged_sem_ajuste": saldo_publicado("CAGED12_ADMISN12", "CAGED12_DESLIGN12", "CAGED12_SALDON12"),
        "novo_caged_com_ajuste": saldo_publicado("CAGED12_ADMISNAJU12", "CAGED12_DESLIGNAJU12", "CAGED12_SALDONAJU12"),
        "caged_tradicional": saldo_publicado("CAGED12_ADMIS", "CAGED12_DESLIG", "CAGED12_SALDO12"),
    }
    resultado["com_ajuste_vs_sem_ajuste_nacional"] = {
        ind: comparar_totais(nacional(com), nacional(sem))
        for ind, com, sem in (
            ("admissoes", "CAGED12_ADMISNAJU12", "CAGED12_ADMISN12"),
            ("desligamentos", "CAGED12_DESLIGNAJU12", "CAGED12_DESLIGN12"),
        )
    }
    tradicional, novo = nacional("CAGED12_ADMIS"), nacional("CAGED12_ADMISN12")
    if not tradicional.empty and not novo.empty:
        sobreposicao = set(tradicional["data_referencia"]) & set(novo["data_referencia"])
        resultado["caged_tradicional_vs_novo_caged"] = {
            "tradicional": [tradicional["data_referencia"].min().date().isoformat(),
                            tradicional["data_referencia"].max().date().isoformat()],
            "novo_caged": [novo["data_referencia"].min().date().isoformat(), novo["data_referencia"].max().date().isoformat()],
            "meses_sobrepostos": len(sobreposicao),
            "meses_faltantes_tradicional": {
                codigo: _meses_faltantes(nacional(codigo))
                for codigo in ("CAGED12_ADMIS", "CAGED12_DESLIG", "CAGED12_SALDO12")
                if not nacional(codigo).empty
            },
        }
    return resultado


def _meses_faltantes(df: pd.DataFrame) -> list[str]:
    meses = pd.date_range(df["data_referencia"].min(), df["data_referencia"].max(), freq="MS")
    return [m.date().isoformat() for m in meses.difference(pd.DatetimeIndex(df["data_referencia"]))]


def _numero(valor: Any) -> float | None:
    return None if pd.isna(valor) else round(float(valor), 4)


def _registros(df: pd.DataFrame) -> list[dict[str, Any]]:
    df = df.copy()
    for coluna in df.select_dtypes(include="datetime").columns:
        df[coluna] = df[coluna].dt.strftime("%Y-%m-%d")
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")
