# Investigação do IpeaData — admissões e desligamentos no Maranhão

**Data da verificação:** 25/10/2026 (coleta às 16:01 UTC)
**API:** `https://www.ipeadata.gov.br/api/odata4/` (OData v4, JSON)
**Documentação consultada:** https://www.ipeadata.gov.br/api/

Os números deste documento saem de `data/processed/investigacao_series.json`
e `data/processed/relatorio_validacao.json`, gerados pelos scripts do projeto.

## 1. Resumo

| Pergunta | Resposta verificada |
|---|---|
| A API está acessível? | Sim. HTTP 200; documento de serviço em ~1 s. |
| `ADMIS` e `DESLIG` existem? | **Não.** `Metadados('ADMIS')` e `Metadados('DESLIG')` devolvem lista vazia. |
| `ADMISNC` e `DESLIGNC` existem? | **Sim.** Base Regional, fonte MTE/Caged, mensal, unidade "Pessoa". |
| Há dados municipais? | **Sim**, nível `Municípios`, 5.571 municípios do Brasil. |
| Há dados para o Maranhão? | **Sim**, os **217** municípios, de **jan/2020 a ago/2026** (80 meses). |
| Qual o código territorial? | `TERCODIGO` com 7 dígitos (padrão de código municipal do IBGE), publicado pelo próprio IpeaData na entidade `Territorios`: 217 municípios do MA. **O cadastro vem só do IpeaData.** |
| São Luís, Imperatriz e Caxias têm registros? | **Sim**, 80 meses cada. |
| Dá para calcular taxas? | **Não** com o IpeaData: não há estoque de empregos formais por município. |

**Conclusão:** o IpeaData é **viável** como fonte principal do dashboard para
contagens mensais de admissões, desligamentos e saldo dos municípios do Maranhão
a partir de 2020, com as limitações da seção 6.

## 2. Endpoints testados

| Endpoint | Resultado |
|---|---|
| `/` (documento de serviço) | 200. Entidades: Paises, Metadados, Temas, Territorios, Valores, ValoresStr |
| `Metadados` | 200. 4.075 séries (~7,7 MB) |
| `Metadados('{codigo}')` | 200. Código inexistente → `value: []` (não é 404) |
| `ValoresSerie(SERCODIGO='{codigo}')` | 200. Série completa (ADMISNC: 448.562 registros, 63,7 MB, ~30 s) |
| `Metadados('{codigo}')/Valores` | 200. Mesmo conteúdo do anterior |
| `Territorios` com `$filter` | 200 |
| `Valores` (raiz, com `$filter`) | **404**, apesar de constar no documento de serviço |

### Suporte a opções OData

| Opção | `Metadados` | `Territorios` | `ValoresSerie` / `.../Valores` |
|---|---|---|---|
| `$filter` com `eq` | ✅ | ✅ | ⚠️ ignorado em silêncio |
| `$filter` com `startswith` | ✅ | ✅ | ⚠️ ignorado em silêncio |
| `$filter` com `contains` | ❌ "query not valid" | não testado | — |
| `$top`, `$skip`, `$orderby` | ✅ | não testado | ⚠️ ignorados em silêncio |
| `$select` | ❌ erro | não testado | — |
| `$count` | ❌ "not supported" | não testado | — |
| `@odata.nextLink` (paginação) | não observado | não observado | não observado |

Consequências na implementação:

- A busca por palavras-chave é feita **localmente** sobre o catálogo completo.
- Não há como baixar só o Maranhão: cada série é baixada **inteira** (todo o Brasil)
  e o recorte é feito no cliente.
- O cliente segue `@odata.nextLink` caso a API passe a paginar.
- Acentos em `$filter` (ex.: `'Municípios'`) precisam ir em UTF-8; com outra
  codificação o filtro retorna vazio sem erro.

## 3. Séries encontradas

A varredura do catálogo (padrões: admiss, demiss, deslig, caged, rais, estoque de
emprego, vínculos, pessoal ocupado) encontrou 12 séries:

| Série | Fonte | Periodicidade | Cobertura | Período disponível | Situação |
|---|---|---|---|---|---|
| `ADMISNC` — Empregados - admissões - Novo Caged sem ajuste | MTE/Caged (base Regional) | Mensal | Brasil, 5 regiões, 27 UFs, 9 áreas metropolitanas, **5.571 municípios** (217 do MA) | 2020-01 a 2026-08 | **Usada no projeto.** Status não informado pela base Regional; atualizada em 05/10/2026 |
| `DESLIGNC` — Empregados - demissões - Novo Caged sem ajuste | MTE/Caged (base Regional) | Mensal | Igual a `ADMISNC` | 2020-01 a 2026-08 | **Usada no projeto.** Atualizada em 05/10/2026 |
| `CAGED12_ADMISN12` — admissões - sem ajuste - novo Caged | Min. Economia/SEPRT/Novo Caged | Mensal | Somente Brasil | 2020-01 a 2026-08 | Ativa. Usada só como referência cruzada |
| `CAGED12_DESLIGN12` — demissões - sem ajuste - novo Caged | idem | Mensal | Somente Brasil | 2020-01 a 2026-08 | Ativa. Referência cruzada |
| `CAGED12_SALDON12` — saldo - sem ajuste - novo Caged | idem | Mensal | Somente Brasil | 2020-01 a 2026-08 | Ativa. Referência cruzada |
| `CAGED12_ADMISNAJU12` — admissões - com ajuste - novo Caged | idem | Mensal | Somente Brasil | 2020-01 a 2026-08 | Ativa |
| `CAGED12_DESLIGNAJU12` — demissões - com ajuste - novo Caged | idem | Mensal | Somente Brasil | 2020-01 a 2026-08 | Ativa |
| `CAGED12_SALDONAJU12` — saldo - com ajuste - novo Caged | idem | Mensal | Somente Brasil | 2020-01 a 2026-08 | Ativa |
| `CAGED12_ADMIS` — admissões (CAGED antigo) | MTE/Caged | Mensal | Somente Brasil | 1999-05 a 2019-12 (248 meses) | **Inativa** |
| `CAGED12_DESLIG` — demissões (CAGED antigo) | MTE/Caged | Mensal | Somente Brasil | 1999-05 a 2019-12 (247 registros: falta 1 mês) | **Inativa** |
| `CAGED12_SALDO12` — saldo (CAGED antigo) | MTE/Caged | Mensal | Somente Brasil | 1999-05 a 2019-12 | **Inativa** |
| `EMPIN` — Pessoal ocupado - indústria | IBGE | Quinquenal | Municípios e outros níveis (136 municípios do MA) | 1907 a 1995 | **Inativa**; não serve ao projeto |

Todas as séries listadas têm registros reais. Nenhuma série de **estoque de
empregos formais** (RAIS/Caged) foi encontrada no catálogo.

## 4. Validação dos dados do Maranhão

Painel coletado: `data/processed/caged_municipios_ma_mensal.csv` — 17.349 linhas
(município × mês).

| Verificação | Resultado |
|---|---|
| Municípios com dados | 217 de 217 |
| Período | 2020-01-01 a 2026-08-01 (80 meses) |
| Combinações município × mês | 17.349 de 17.360 esperadas |
| Combinações ausentes | **11**, todas em **jan/2024**: Bacuri, Belágua, Brejo de Areia, Cajapió, Central do Maranhão, Conceição do Lago-Açu, Duque Bacelar, Marajá do Sena, Milagres do Maranhão, Paulino Neves, Porto Rico do Maranhão (mesmas lacunas em admissões e desligamentos) |
| Valores nulos nos registros existentes | 0 |
| Duplicados (`cod_ibge`, `data`) | 0 (também 0 na série inteira, por nível/território/data) |
| Valores negativos | 0 |
| Zeros explícitos | 3.046 linhas com admissões = 0; 2.953 com desligamentos = 0 |

As lacunas de jan/2024 **não foram preenchidas**. Na etapa 1.5 verificou-se que
são **uma lacuna da própria publicação**, e não algo específico do Maranhão: em
jan/2024 a série traz 5.463 municípios no país inteiro, contra 5.570 em dez/2023 e
fev/2024; e o número de zeros explícitos cai para 155 (397 em dez/2023, 240 em
fev/2024). É um forte indício de que a fonte deixou de publicar zeros naquele mês,
mas **não é uma confirmação**. Por isso as lacunas continuam como "observação
ausente", marcadas como "lacuna sistêmica da fonte" nos relatórios de cobertura.

### Municípios de teste (último mês disponível, ago/2026)

| Município | Código IBGE | Meses | Admissões | Desligamentos | Saldo |
|---|---|---|---|---|---|
| São Luís | 2111300 | 80 | 10.967 | 9.996 | 971 |
| Imperatriz | 2105302 | 80 | 2.493 | 2.687 | −194 |
| Caxias | 2103000 | 80 | 298 | 299 | −1 |

### Consistência entre níveis territoriais (80 meses)

| Comparação | Admissões | Desligamentos |
|---|---|---|
| Soma dos 217 municípios × total do estado (MA) | **0 meses divergentes** | **0 meses divergentes** |
| Brasil (base Regional) × série nacional `CAGED12_*N12` | 2 meses divergem, máx. 3 pessoas | 0 divergências |
| Soma das 27 UFs × total Brasil | 80 meses divergem; Brasil > soma em média 0,60% (máx. 47.761) | 80 meses; média 0,67% (máx. 60.936) |
| Saldo nacional calculado (adm − desl) × saldo publicado | 0 divergências | — |

A diferença UF × Brasil é sempre positiva (o Brasil é maior). O padrão é compatível
com movimentações sem UF identificada, mas **essa causa não foi confirmada** na
documentação. Para o dashboard, o total estadual e a soma dos municípios coincidem
exatamente, então a divergência não afeta análises do Maranhão.

## 5. Indicadores

| Indicador | Calculável? | Observação |
|---|---|---|
| Total de admissões | Sim | Contagem absoluta de pessoas |
| Total de desligamentos | Sim | Contagem absoluta de pessoas |
| Saldo (admissões − desligamentos) | Sim | Confere com o saldo publicado no nível nacional |
| Evolução mensal | Sim | 80 meses |
| Evolução anual | Sim | 2020–2025 completos; 2026 parcial (jan–ago). Somar meses só onde houver dados e sinalizar a lacuna de jan/2024 |
| Comparação entre municípios | Sim | 217 municípios |
| Ranking de municípios | Sim | Por contagem absoluta. Municípios grandes dominam; não é um ranking de desempenho relativo |
| Taxas percentuais (admissão, desligamento, rotatividade, variação do emprego) | **Não** | Exigem estoque de empregos formais por município, que o IpeaData não oferece |

Admissões, desligamentos e saldo são **quantidades absolutas**, não taxas. Uma
taxa precisa de um denominador metodologicamente adequado (estoque de vínculos
formais no início do período). Variação percentual de admissões entre meses é
possível, mas mede variação do fluxo, não taxa de emprego.

## 6. Limitações

1. **Só a partir de 2020.** As séries municipais existem apenas para o Novo Caged
   (jan/2020 em diante). O CAGED antigo no IpeaData (`CAGED12_ADMIS`, etc.) é só
   nacional e está inativo (até dez/2019).
2. **CAGED antigo × Novo Caged não devem ser combinados.** O Novo Caged usa também o
   eSocial e o Empregador Web e abrange mais categorias (temporários, avulsos, agentes
   públicos, cedidos, dirigentes sindicais, conforme o `SERCOMENTARIO` da série). A
   mudança de fonte e de cobertura cria uma quebra estrutural em jan/2020; emendar as
   séries produziria um salto artificial.
3. **Séries "sem ajuste".** `ADMISNC`/`DESLIGNC` são "sem ajuste". No nível nacional,
   a série "com ajuste" fica em média 3,0% acima nas admissões (7,25% em 2020; ~1,1%
   de 2023 a 2026) e é idêntica só no mês mais recente. Isso indica que o "ajuste"
   incorpora declarações entregues depois do prazo. Os números municipais tendem,
   portanto, a ficar abaixo dos totais "com ajuste" divulgados pelo MTE. Não existe
   versão municipal "com ajuste" no IpeaData.
4. **Revisões.** Como meses anteriores são revisados, cada coleta é uma fotografia;
   por isso o horário da coleta e o SHA-256 ficam registrados.
5. **Sem filtro no servidor.** Cada atualização baixa ~64 MB por série (~30 s).
6. **11 lacunas em jan/2024** em municípios pequenos, parte de uma lacuna nacional da publicação (seção 4).
7. **Sem denominador** para taxas (seção 5).
8. **Base Regional sem `SERSTATUS`**: a situação (ativa/inativa) das séries
   municipais não é informada; a data de atualização (05/10/2026) indica manutenção.

## 7. Fontes fora do IpeaData (descartadas por regra)

**Regra obrigatória do projeto:** todos os dados devem estar disponíveis no IpeaData. É permitido usar séries cuja
origem estatística seja o CAGED/Novo CAGED **quando o IpeaData as publica**; é proibido obter dados direto do Ministério
do Trabalho, do IBGE ou de qualquer outro portal. A comprovação, registro a registro, está em
[auditoria_origem_ipeadata.md](auditoria_origem_ipeadata.md).

Consequências já aplicadas:

- Não há dados municipais antes de 2020-01 no projeto: o IpeaData só os publica a partir do Novo Caged. O período anterior
  consta como "não disponibilizado pela fonte"; **nada é complementado com outra base**.
- Não há estoque de empregos por município no IpeaData, então **taxas percentuais não são calculadas**.
- O cadastro de municípios vem da entidade `Territorios` do IpeaData (não de lista externa).

### Registro de incidentes de procedência (transparência)

Durante o desenvolvimento, três usos de fontes fora do IpeaData ocorreram. Foram identificados na auditoria e corrigidos:

| Incidente | Etapa | O que aconteceu | Situação |
|---|---|---|---|
| API de localidades do **IBGE** no pipeline | 1 a 2 | A coleta consultava o IBGE a cada execução para obter a lista de municípios. Os 217 municípios do banco referenciavam essa fonte. | **Corrigido.** Consulta removida; cadastro passou a vir do `Territorios` do IpeaData; respostas antigas movidas para `data/quarentena/` (não apagadas); fonte registrada como `legado_nao_autorizado`. Os nomes e códigos conferem com o IpeaData (217 de 217). |
| Exploração do **FTP do MTE** | 1.5 | Para avaliar a viabilidade de histórico anterior a 2020, listaram-se diretórios do FTP público do MTE e **um** arquivo mensal foi baixado para inspecionar o layout e agregado, numa análise exploratória em pasta temporária. | Nada entrou no banco nem nos arquivos do projeto; o arquivo foi apagado e os números dessa exploração foram **removidos** deste documento. Não deveria ter havido download. |
| Comparação de códigos com a API do **IBGE** | 1 | Conferência pontual dos códigos municipais, fora do pipeline. | Sem efeito nos dados; a conferência equivalente agora usa só o IpeaData. |

## 8. Reprodução

```powershell
python -m scripts.testar_requisicao   # conectividade e metadados
python -m scripts.investigar_ipea     # tabela da seção 3
python -m scripts.coletar_historico   # base histórica completa (modo FULL)
python -m scripts.validar_dados       # seções 4 e 5
python -m scripts.gerar_relatorio     # docs/cobertura_historica.md e relatorio_validacao_etapa1.md
```
