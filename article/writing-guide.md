# Writing Guide: Relatório Técnico (FATEC Baixada Santista, Ciência de Dados, 2026)

Source: `Modelo de Relatório Técnico CD 2026.docx`. Standard: **ABNT NBR 10719** (technical/scientific report). The template also says "10179" in places; that's a typo.

## 1. Formatting rules

| Item | Rule |
|---|---|
| Paper | A4 |
| Margins | Top 3 cm, left 3 cm, bottom 2 cm, right 2 cm |
| Font | Arial 12 for the body; 10 for author lines and page numbers |
| Line spacing | Single throughout (NBR 10719 §5.1) |
| Body paragraphs | Justified, 1.25 cm first-line indent, not bold |
| Heading level 1 (`1 INTRODUÇÃO`) | Bold, ALL CAPS, left-aligned, no indent, starts a new page |
| Heading level 2 (`1.1 OBJETIVO GERAL`) | ALL CAPS, not bold, left-aligned, no indent |
| Unnumbered headings (REFERÊNCIAS, APÊNDICE, ANEXO) | Bold, caps, centered |
| Pre-text headings (RESUMO, LISTAS…) | Bold, caps, centered, unnumbered |
| Numbering | Arabic numerals with no trailing dot (`1`, `1.1`). Lists use `a)`, `b)`, `c)` |
| Page numbers | Top right, size 10. Counted from the cover but shown only from the Introdução onward (page 7) |
| Header | Institutional logos (CPS/FATEC) |
| Foreign terms | Italic (*dataset*) |
| References | Left-aligned, no indent, ABNT style (AUTHOR IN CAPS. Title. City, year.) |
| Citations | Author-date with page: `ABNT 10719 (2011, p. 3)`, short quotes "in quotation marks" |

## 2. Structure (fixed order)

**Pre-text**
1. **Capa / Folha de rosto**: centered, caps. CENTRO ESTADUAL DE EDUCAÇÃO TECNOLÓGICA PAULA SOUZA → FACULDADE DE TECNOLOGIA DA BAIXADA SANTISTA → CURSO SUPERIOR DE TECNOLOGIA EM CIÊNCIA DE DADOS → RELATÓRIO TÉCNICO → TÍTULO: Subtítulo → authors as `Nome (Titulação, Instituição) email@fatec.sp.gov.br` → SANTOS → MÊS/ANO
2. AGRADECIMENTOS (optional)
3. **RESUMO**: one paragraph of 200–250 words with no indent, followed by `Palavras-chave:` with terms separated by `;` and ending in a period (hanging indent)
4. LISTA DE ILUSTRAÇÕES, LISTA DE TABELAS, LISTA DE ABREVIATURAS E SIGLAS
5. SUMÁRIO

**Text**
| # | Section | What it must contain |
|---|---|---|
| 1 | INTRODUÇÃO | Topic, scope, and objectives. Context and relevance for the tecnólogo's training and for the market. Define the target audience |
| 1.1 | OBJETIVO GERAL | One concrete, real problem tied to the research object. It guides the whole analysis |
| 1.2 | OBJETIVOS ESPECÍFICOS | List items `a)`, `b)`, `c)`, each starting with an infinitive verb |
| 2 | CONTEXTUALIZAÇÃO DO CENÁRIO | The core of the work. Describe the problem scenario plus a short theoretical, historical, or conceptual basis (area, object, sample, problem). Give enough for a qualified reader to follow |
| 3 | PROCEDIMENTOS METODOLÓGICOS | How the work was done |
| 3.1 | APRESENTAÇÃO DO *DATASET* / CRIAÇÃO DE *DATASET* | Justify the choice (reliability, credibility, applicability) and explain the indicators and variables. **Or** justify why you built the dataset yourself |
| 3.2 | DETALHAMENTO DAS ETAPAS DE TRATAMENTO DE DADOS E FERRAMENTAS | Steps (e.g. ETL) and tools in detail. **Or** describe a new procedure you created |
| 4 | RESULTADOS DA ANÁLISE E RECOMENDAÇÕES | Detailed analysis, the most viable solution, and insights for decision-makers in the sectors behind the sample. Recommendations are short, action-oriented statements for the future |
| 5 | CONSIDERAÇÕES FINAIS E LIMITAÇÕES DO ESTUDO | Conclusions only, with **no new information and no illustrations**. Go back to the general and specific objectives and confirm they were met. Limitations come from scope, client, technology, audience, or sample |

**Post-text**
- REFERÊNCIAS (ABNT)
- APÊNDICE A – Título: the authors' own material (user manual, quick-start guide, blank copy of your own questionnaire)
- ANEXO A – Título: third-party material (for example, someone else's questionnaire)

Sections marked "OU" in the template are alternatives: pick one path (existing dataset or created dataset, standard ETL or a new procedure, solution or insights).

## 3. Voice and style

- **Impersonal and formal academic Portuguese (pt-BR).** No first person. Use the passive with *se* ("são descritas", "pode-se apresentar", "não se apresentam") or the third person ("o relatório apresenta").
- **Objective and declarative.** Short, factual sentences with no rhetorical flourish or opinion that the data doesn't support.
- **Systematic.** Each chapter does one job. Context comes before method, method before results, results before conclusions. Don't mix them.
- **Justify, don't just describe.** Every choice (dataset, tool, step) needs a reason: reliability, credibility, applicability.
- **Concrete.** The problem must be real and specific. Results should lead to decisions.
- **Audience:** a qualified reader in the field. Be complete but not exhaustive, and keep theory "sucinta".
- **Supporting claims:** cite sources author-date (ABNT) and give the page for direct quotes.
- **Field vocabulary:** *dataset*, ETL, indicadores, variáveis, amostra, insights, tomada de decisão.

## 4. Things in the template to fix, not copy

- "NBR 10179" should be **NBR 10719**. The dates also disagree (2011 in the text, 2015 in the reference).
- The Resumo mentions "Logística" and "ARENA", which are left over from another course's template. Replace them with Ciência de Dados content.
- "deLogística" is missing a space, "detalhamento da etapas" should be "das etapas", and "expetativas" should be "expectativas".
- The Palavras-chave line mixes `;` and `.`, so standardize on `;`.
