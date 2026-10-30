# pi review of article/main-article.md

Third-party review of the technical report by the pi agent (`ask-pi --ro`, session `article-review`), 2026-10-27. The review is copied verbatim below, followed by how each finding was handled.

## Review

**Peer review of `article/main-article.md`**

Findings, most severe first:

1. **331 | média** | The article states the verification gate "aprovou as 30 verificações, com um aviso". The generated report says "Verification gate: **29/30 checks passed**" (results/full-2026-10-27/report/report.md:3), and verify-report.json shows one check with `ok: false` (severity `warn`). The article's phrasing contradicts its own source artifact. Fix: write "o portão registrou 29 verificações aprovadas e um aviso (…)". 
2. **486 | média** | The feature-gain percentages ("início do intervalo (21%), capacidade (10%), atributo 5 (10%)…") do not appear in report.md, which instead contains a single-attribute ROC-AUC table with different numbers (e.g., smart_187_raw 0.699 as top attribute, whereas the text puts attribute 197 above 187). The percentages appear to come from LightGBM gain importance (importance.png), which is a different quantity; the paragraph reads as if it were derived from the reported analysis. Fix: state the metric (ganho do LightGBM) and the source, or use the ROC-AUC table.
3. **386 | média** | "cerca de 10% do peso do treino e a 50% do peso do teste" is not present in report.md, cohort-summary.json, or METHODOLOGY.md; it is unverifiable against the cited artifacts. Fix: cite the build artifact that contains it or remove the claim.
4. **283–286 | média** | Tabela 1's third column ("Discos com falha visível no período do conjunto": 12.220 / 1.772 / 1.784) appears neither in cohort-summary.json nor in report.md. The other columns match exactly. Fix: cite the file where this column comes from (e.g., build/cohort summary) or drop the column.
5. **273 | baixa** | "treinar com os pesos completos fez o modelo parar após poucas iterações" is supported for small scale (~30 rounds, METHODOLOGY §4), but at full scale the power-1.0 model ran 237 iterations and ranked equivalently (0.878 vs 0.876, as the article itself reports at line 482). Fix: attribute the "parar após poucas iterações" observation to the small-scale experiment to avoid an internal tension.
6. **532 | baixa** | The AMRAM reference is incomplete for ABNT NBR 6023: "Machine Learning with Applications, 2021" lacks volume, issue, and article number (v. 6, 100712). Fix: complete it or cite as preprint with arXiv ID.
7. **566–568, 572–574 | baixa** | Reference ordering and ABNT convention: KLEIN 2022 precedes KLEIN 2016 and KVAMME 2021 precedes KVAMME 2019; same-author repeated entries should be ordered chronologically and, per ABNT, subsequent entries replaced by underscores (______). Fix: reorder and use underscores.
8. **223 | baixa** | "Fonte: Elaborado pelos autores com base em Beach (2014) e na configuração do projeto (2026)" — "(2026)" is an authorless citation that has no corresponding entry in REFERÊNCIAS. Fix: cite as "(BACKBLAZE, 2026)" or name the project/config explicitly.
9. **Figura 1 (line ~245–250) | baixa** | Figure 1 is an ASCII diagram in a code block, unlike Figures 2–5 (PNG). For the final ABNT-formatted document this needs a real figure; in the markdown source it also won't appear in a rendered LISTA DE ILUSTRAÇÕES consistently. Fix: generate a proper image for Figure 1.
10. **396–403 | baixa** | Tabela 4 omits the confidence intervals reported for false-alarm rates and precision in report.md (e.g., 1,55% [1,35%; 1,70%]; precision 4,38% [3,94%; 5,05%]) while other tables carry them, even though the text (line 409) relies on the interval "excluding 1%". Fix: add intervals to the table or state they are omitted.
11. **382 | baixa** | "menor que a observada por Pinheiro *et al.* (2007)" — the Pinheiro figure the text earlier quotes is ">36%" (silent per all attributes), and the article's 20,6% is indeed lower, but the comparison mixes different silent-failure definitions (Klein's five attributes vs the study's four counters vs Pinheiro's four signals) more than the hedge "indicativa" conveys. Minor; the existing caveat is acceptable but could be sharper.
12. **371–378 | baixa** | Vendor and capacity slice AUCs in Tabela 3 are given without the confidence intervals that report.md provides (e.g., Toshiba 0,792 [0,763; 0,813], WDC 0,827 [0,788; 0,874] — the latter's interval is wide and weakens the "varia de 0,792 a 0,923" interpretation). Fix: include intervals or note the width for WDC.

**Factual verification (items checked against report.md, cohort-summary.json, METHODOLOGY.md, study.toml, pipeline.toml, model JSONs):** all verified correct — panel numbers (646.777.037 / 478.464 / 26.679 / 3.898 SSDs / 710 post-failure), cohort table splits and totals (57.309; 9.500.711), 48.083.205 person-period rows, best iterations (595, 237), all hyperparameters (lr 0,03; 31 folhas; 200/folha; 100; 2.000), all of Tabela 2, 3, 4, 5, 6 values, 62% persistence, 20,6% silent failures, 6,5/33,0/76,5% pessimism, 16,9%, 103 days, 36×, 321 drives, 4,1%, retirement ratios (6,48→1,21; 2,25; 509/5.809), concordance (0,766/0,760), IPCW max difference 0,012, per-drive 0,862, 16 drives warning, 65 features breakdown, 89% rule-budget claim (METHODOLOGY), 2,9% Seagate packed values.

**Citation spot-checks (12):** Murray 2005 (3–10% manufacturers' estimate) ✓; Schroeder & Gibson 2007 (~100k drives, >1%, 2–4%, up to 13%, direct quote verbatim on p. 1) ✓; Pinheiro 2007 (39× within 60 days, >56%, >36%, quote verbatim, p. 1) ✓; Beach 2014 (quote verbatim, five SMART attributes) ✓; Klein 2016 (76,7% / 4,2% / 23,3%) ✓; Xu 2018 (91,64% vs 36,50% at 0,1% FPR, quote verbatim, within pp. 481–494) ✓; Siemroth & Park 2026 (146.943, 31%, right-censored) ✓; Backblaze Q3 2024 (53,0% of 1.361 proactive; dataset lacks failure type) ✓; Backblaze Q3 2025 (16,95% Toshiba MG08ACA16TEY, drive sentinel threshold removal, non-mechanical firmware cause) ✓; Han 2023 (1% FPR default; F1 gains 26,8–53,2%) ✓; Amram 2021 (~50% sensitivity at ~10% false-alarm rate) ✓; Kapoor & Narayanan 2023 (294 papers, 17 fields) ✓. Also Lu 2020 (380k drives, 64 sites, k-fold CV) and Ma 2015 (88% of triple-disk errors via reallocated-sector-driven proactive action) ✓.

**Verdict.** This is an unusually rigorous technical report: the quantitative content is almost perfectly faithful to the pipeline's outputs, the ablation/circularity logic is sound, and conclusions are consistently hedged ("limite superior", "comparação indicativa") rather than causal or overclaimed. Section order, impersonal voice, resumo length (~239 words), decimal commas, italics, and section 5 restrictions all conform to the conventions. The main weaknesses are one wording conflict with the verification-gate artifact, a handful of numbers presented without a traceable source (lines 386, 486, and Tabela 1's third column), and minor ABNT reference-list imperfections. None of these undermines the results; all are fixable in a single editing pass. Recommendation: minor revision.
## Resolution

| # | Outcome |
|---|---|
| 1 | Fixed. The text now says 29 of 30 checks passed and one raised a warning, with no error. |
| 2 | Fixed. The shares are named as LightGBM gain importance from the model metadata, with a note on how they differ from the single-attribute ROC-AUC. |
| 3 | Not changed. The 10% / 50% figure is in `docs/METHODOLOGY.md` §7.3 and the `[evaluation]` comments of `config/study.toml`. |
| 4 | Fixed. The table source now names the cohort summary and the gate report (`failures_present_*`). |
| 5 | Fixed. The early-stopping problem with full weights is attributed to the small-scale tests. |
| 6 | Fixed. The volume could not be checked in the local copy, so the reference cites the saved arXiv version. |
| 7 | Fixed by chronological order. ABNT allows repeating the author name, so no underscores were added. |
| 8 | Fixed. The source names `config/study.toml`. |
| 9 | Fixed after the review: Figure 1 is now an image, `article/figures/figura-1-fluxo.svg`. |
| 10 | Fixed. Table 4 carries the intervals for false alarms and precision. |
| 11 | Fixed. The comparison uses Pinheiro's >56% with four signals and states that the definitions differ. |
| 12 | Fixed. The text gives the vendor intervals and notes the wide WDC interval. |

A second pass in the same session re-checked the revised passages and answered "OK".
