# ARTICLE.md

How to write a **Relatório Técnico** (FATEC Baixada Santista, Ciência de Dados) in the style of `Modelo de Relatório Técnico CD 2026.docx`. Follow `writing-guide.md` for page formatting. This file covers structure, voice, and wording.

## Hard rules

- Write in **formal pt-BR**. Never use the first person (eu, nós, "fizemos", "acreditamos").
- Use the **impersonal voice**: the passive with *se* ("analisou-se") or the third person ("o estudo apresenta").
- Keep the section order and headings below exactly. Never rename, merge, or reorder them.
- Every choice (dataset, tool, step, metric) gets a **justification**.
- **Never invent** data, results, citations, or references. If something is missing, write `[PREENCHER: ...]`.
- Section 5 adds **no new information and no figures**.
- Italicize foreign terms: *dataset*, *insights*, *outliers*, *dashboard*, *machine learning*.
- Use a decimal comma and `%` with no space: `12,5%`, `R$ 1.250,00`.
- Spell out every abbreviation the first time it appears: "Extração, Transformação e Carga (ETL)".

## Markdown conventions

```markdown
# 1 INTRODUÇÃO                 ← level 1: number + space + CAPS, no trailing dot
## 1.1 OBJETIVO GERAL          ← level 2: CAPS
# REFERÊNCIAS                  ← unnumbered
# APÊNDICE A – QUESTIONÁRIO APLICADO   ← en dash (–), not a hyphen
```

Lists use `a)`. Each item starts lowercase and ends with `;`, and the last one ends with `.`:

```markdown
a) identificar os principais fatores de atraso;
b) comparar o desempenho entre terminais;
c) propor indicadores de monitoramento.
```

## Voice: wrong vs. right

| ❌ Don't | ✅ Do |
|---|---|
| Nós analisamos os dados do porto. | Foram analisados os dados do porto. |
| Neste trabalho eu vou mostrar... | Este relatório apresenta... |
| Usamos Python porque é a melhor linguagem. | Utilizou-se Python em razão da disponibilidade de bibliotecas para tratamento e visualização de dados, como *pandas* e *matplotlib*. |
| Os resultados foram incríveis! | Os resultados indicam redução de [X]% no tempo médio de espera. |
| É muito importante falar sobre isso hoje em dia. | O tema é relevante para a gestão portuária, uma vez que atrasos elevam custos operacionais. |
| Pegamos um dataset na internet. | Selecionou-se o *dataset* disponibilizado pela [FONTE], em razão de sua origem oficial e atualização periódica. |
| Limpamos os dados. | Na etapa de tratamento, removeram-se registros duplicados e valores ausentes nas variáveis [A] e [B]. |
| Concluímos que deu certo. | Conclui-se que o objetivo geral foi atingido, visto que... |
| Talvez, quem sabe, isso possa ajudar. | Recomenda-se a adoção de... |

**Useful verb forms:** apresenta-se, observa-se, verifica-se, constata-se, nota-se, destaca-se, recomenda-se, conclui-se, optou-se por, procedeu-se à, foram aplicadas, foi utilizado.

**Connectives:** além disso, dessa forma, nesse sentido, por conseguinte, em contrapartida, uma vez que, visto que, em razão de, conforme, segundo.

**Avoid:** muito, super, bem, coisa, enfim, basicamente, a gente, "hoje em dia", exclamation marks, rhetorical questions, and emojis.

## Section-by-section templates and examples

The examples use one running case: *delays in ship berthing at the Port of Santos*. All numbers are placeholders.

### RESUMO

A single unindented paragraph of 200–250 words that covers the context, objective, method, results, and conclusion, in that order. Use no citations, no figures, and no abbreviations without their full form.

> O Porto de Santos concentra parcela expressiva da movimentação de cargas do país, e atrasos na atracação de navios geram custos adicionais para armadores e operadores. Este relatório tem como objetivo identificar os fatores associados ao tempo de espera para atracação no período de [ANO] a [ANO]. Para isso, utilizou-se o *dataset* público da Agência Nacional de Transportes Aquaviários (ANTAQ), submetido a etapas de Extração, Transformação e Carga (ETL) em Python. Aplicaram-se análise exploratória e modelos de regressão para estimar a influência de variáveis como tipo de carga, terminal e mês de chegada. Os resultados indicam que [FATOR] explica [X]% da variação do tempo de espera... Conclui-se que...
>
> Palavras-chave: ciência de dados; logística portuária; tempo de espera; regressão.

### 1 INTRODUÇÃO

State the topic, its scope (where, when, what), the relevance for the market and for the tecnólogo's training, and the target audience.

> A eficiência portuária constitui fator determinante para a competitividade do comércio exterior brasileiro. Nesse contexto, o tempo de espera para atracação representa um dos principais indicadores de desempenho operacional.
>
> Este relatório delimita-se à análise das atracações realizadas no Porto de Santos entre [ANO] e [ANO]. A relevância do estudo reside na possibilidade de subsidiar decisões de planejamento com base em dados, competência central na formação do tecnólogo em Ciência de Dados. O público-alvo compreende gestores portuários, operadores de terminais e órgãos reguladores.

### 1.1 OBJETIVO GERAL

Write one sentence that starts with an infinitive and names a concrete, real problem.

> ✅ Identificar os fatores que influenciam o tempo de espera para atracação de navios no Porto de Santos, a partir de dados públicos da ANTAQ.
>
> ❌ Estudar a logística portuária. *(too vague, with no problem and no object)*
>
> ❌ Mostrar como a ciência de dados é importante. *(not a problem, and not measurable)*

### 1.2 OBJETIVOS ESPECÍFICOS

Write 3–5 items, each starting with an infinitive verb (identificar, analisar, comparar, mensurar, propor, desenvolver). Together they should add up to the general objective.

> Descrever os objetivos específicos que serão registrados no relatório:
>
> a) caracterizar o perfil das atracações por terminal e tipo de carga;
> b) mensurar o tempo médio de espera por período;
> c) identificar, por meio de regressão, as variáveis de maior influência;
> d) propor indicadores para monitoramento contínuo.

### 2 CONTEXTUALIZAÇÃO DO CENÁRIO

This is the core of the report. Describe the problem scenario, then give a short theoretical basis with citations. A qualified reader should be able to follow it without outside sources.

> O Porto de Santos é o maior complexo portuário da América Latina [PREENCHER: fonte]. Segundo [AUTOR] ([ANO], p. [N]), o tempo de espera para atracação corresponde ao "[CITAÇÃO DIRETA CURTA]".
>
> Na área de Ciência de Dados, a análise de séries temporais e os modelos de regressão permitem identificar padrões e relações entre variáveis operacionais (AUTOR, ANO). Dessa forma, torna-se possível...

### 3 PROCEDIMENTOS METODOLÓGICOS

Open with one sentence that frames how the work was carried out.

> Para a pesquisa, adotou-se abordagem quantitativa, de caráter descritivo e exploratório, fundamentada em dados secundários.

### 3.1 APRESENTAÇÃO DO *DATASET* / CRIAÇÃO DE *DATASET*

Choose **one** of the two paths. Justify the choice by reliability, credibility, and applicability, and explain the variables.

**Path A (existing dataset):**

> Selecionou-se o *dataset* Estatístico Aquaviário da ANTAQ, em razão de sua origem oficial (confiabilidade), da ampla utilização em estudos do setor (credibilidade) e da cobertura das variáveis necessárias ao objetivo proposto (aplicabilidade). O conjunto contém [N] registros e [N] variáveis, das quais se destacam:
>
> a) **data_chegada**: data e hora de chegada do navio à barra;
> b) **data_atracacao**: data e hora de atracação no berço;
> c) **tipo_carga**: classificação da carga (granel sólido, granel líquido, contêiner, carga geral);
> d) **terminal**: identificação do terminal de destino.

**Path B (created dataset):**

> Optou-se pela criação de *dataset* próprio, uma vez que as bases públicas disponíveis não contemplam [VARIÁVEL]. Os dados foram coletados por meio de questionário aplicado a [N] operadores entre [MÊS] e [MÊS] de [ANO] (APÊNDICE A).

### 3.2 DETALHAMENTO DAS ETAPAS DE TRATAMENTO DE DADOS E FERRAMENTAS

List the steps in order, and say which tool was used for each and why.

> O tratamento dos dados seguiu as etapas de ETL descritas a seguir:
>
> a) **extração**: download dos arquivos CSV do portal da ANTAQ e leitura com a biblioteca *pandas*;
> b) **transformação**: remoção de [N] registros duplicados, exclusão de valores ausentes em **data_atracacao** e criação da variável **tempo_espera**, em horas;
> c) **carga**: armazenamento da base tratada em banco de dados PostgreSQL, a fim de permitir consultas reprodutíveis.
>
> Para a modelagem, utilizou-se a biblioteca *scikit-learn*, em razão de sua documentação consolidada e da disponibilidade de métricas de avaliação.

### 4 RESULTADOS DA ANÁLISE E RECOMENDAÇÕES

Introduce each figure or table in the text before it appears. Interpret the data; don't just restate it. End with recommendations written as short calls to action.

> A Tabela 1 apresenta o tempo médio de espera por tipo de carga.
>
> **Tabela 1 – Tempo médio de espera por tipo de carga ([ANO])**
>
> | Tipo de carga | Atracações | Espera média (h) |
> |---|---|---|
> | Granel sólido | [N] | [X] |
> | Contêiner | [N] | [X] |
>
> Fonte: Elaborado pelos autores com base em ANTAQ ([ANO]).
>
> Observa-se que o granel sólido apresenta tempo médio de espera [X] vezes superior ao de contêineres. Esse comportamento pode ser atribuído à sazonalidade da safra agrícola, visto que o pico de espera coincide com os meses de [MÊS] a [MÊS].

| ❌ Description only | ✅ Interpretation |
|---|---|
| O gráfico mostra que março tem o valor mais alto. | Verifica-se pico de espera em março, período que coincide com o escoamento da safra de soja, o que indica restrição de capacidade nos terminais de granel. |

**Recommendations:**

> Com base nos resultados, recomenda-se:
>
> a) ampliar a janela de agendamento de atracações nos meses de safra;
> b) implementar *dashboard* de monitoramento do tempo de espera por terminal;
> c) integrar dados meteorológicos às análises futuras.

### 5 CONSIDERAÇÕES FINAIS E LIMITAÇÕES DO ESTUDO

Go back to the general objective and each specific objective, confirm each one, and then state the limitations. Introduce no new data, numbers, figures, or citations.

> Este relatório teve como objetivo identificar os fatores que influenciam o tempo de espera para atracação no Porto de Santos. Constata-se que o objetivo geral foi atingido, uma vez que a análise permitiu identificar [FATOR] como variável de maior influência.
>
> Quanto aos objetivos específicos, a caracterização do perfil das atracações (objetivo a) e a mensuração do tempo médio de espera (objetivo b) foram apresentadas no capítulo 4...
>
> Como limitações, destacam-se a ausência de dados meteorológicos na base utilizada e o recorte temporal restrito a [N] anos, o que impede a generalização dos resultados para outros períodos.

❌ "Além disso, uma nova análise mostrou que..." *(this is new information, so it belongs in section 4)*

## Citations (ABNT, author-date)

| Situation | Example |
|---|---|
| Author named in the sentence | Segundo Silva (2023, p. 45), ... |
| Author in parentheses | ... reduz custos operacionais (SILVA, 2023). |
| Two authors | (SILVA; SOUZA, 2022) |
| Three or more | (SILVA *et al.*, 2021) |
| Institution | (ASSOCIAÇÃO BRASILEIRA DE NORMAS TÉCNICAS, 2011) or ABNT (2011) |
| Short direct quote (≤ 3 lines) | Put it in "aspas" in the paragraph and **give the page** |
| Long quote (> 3 lines) | Separate block, 4 cm indent, font 10, no quotes, with page |

## References (ABNT NBR 6023)

List them alphabetically, left-aligned, single-spaced, with a blank line between entries. The title goes in **bold**.

```markdown
ASSOCIAÇÃO BRASILEIRA DE NORMAS TÉCNICAS. **NBR 10719**: informação e documentação: relatório técnico e/ou científico: apresentação. Rio de Janeiro: ABNT, 2015.

SOBRENOME, Nome. **Título do livro**: subtítulo. 2. ed. Cidade: Editora, 2020.

SOBRENOME, Nome; SOBRENOME, Nome. Título do artigo. **Nome da Revista**, Cidade, v. 10, n. 2, p. 15-30, 2022.

AGÊNCIA NACIONAL DE TRANSPORTES AQUAVIÁRIOS. **Estatístico Aquaviário**. Brasília: ANTAQ, 2025. Disponível em: <URL>. Acesso em: 27 out. 2026.
```

## Figures and tables

- Put the caption **above** the item: `Figura 1 – Título`, `Gráfico 1 – Título`, `Tabela 1 – Título`. Use an en dash and number them in order.
- Put the source **below** the item: `Fonte: Elaborado pelos autores (2026).` or `Fonte: ANTAQ (2025).`
- Mention every item in the text before it appears ("conforme a Figura 2", "a Tabela 1 apresenta").
- Never place a figure or table in section 5.

## Appendix vs. annex

- **APÊNDICE** is material written by the authors: a user manual, a quick-start guide, or a blank copy of the authors' own questionnaire.
- **ANEXO** is material from third parties, such as another author's questionnaire or a regulation.

## Final checklist

- [ ] There is no first person anywhere.
- [ ] The Resumo is 200–250 words, with keywords separated by `;`.
- [ ] The general objective names a concrete problem, and the specific objectives start with infinitives.
- [ ] The dataset choice is justified by reliability, credibility, and applicability.
- [ ] Every ETL step names its tool and the reason for it.
- [ ] Results interpret the data, and the recommendations are calls to action.
- [ ] Section 5 revisits every objective, adds nothing new, and has no figures.
- [ ] Every citation appears in the REFERÊNCIAS, and every reference is cited.
- [ ] Abbreviations are spelled out on first use, and foreign terms are in italics.
- [ ] No `[PREENCHER]` placeholders are left in the final version, or they are reported to the user.
