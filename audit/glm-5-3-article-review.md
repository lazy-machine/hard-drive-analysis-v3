# GLM-5.3 review of article/main-article.md

Reviews by `openrouter/z-ai/glm-5.3` (Pi, thinking high), run as read-only delegates on 2026-11-09. Each round is summarized finding by finding, with how it was handled. The findings are condensed from the reviewer's text.

## Round 1: 8/10

Reviewed the draft of commit `2bce5f0`. Sub-scores: factual fidelity 9.5, method and statistics 8, literature 8, template and ABNT 9, writing 9, focus 9.5.

| # | Severity | Finding | Outcome |
|---|---|---|---|
| 1 | major | "Mesmos hiperparâmetros, com uma exceção" is false: `pipeline.toml` sets a different early-stopping patience per model. | Fixed, with a correction. The run the article quotes (2026-10-26/27) used a patience of 100 for every model (`pipeline.toml` at `644ef26`). The per-model values came later (`2213198`) and were used by the reproduction run, with the same best iterations. The text after Quadro 2 now says both. |
| 2 | major | The 10% to 90% interval is promised in 3.2 and never evaluated; its coverage is 25.9%. | Fixed. Section 4.4 reports the 25.9% and says why it is not a calibration measure: it is conditional on failure, so a calibrated model would not reach 80% on it. |
| 3 | minor | The reason for retirement is attributed to Siemroth and Park. | Fixed. The clause was removed. |
| 4 | minor | Amram et al. cited as a preprint. | Fixed. The reference is the published version. |
| 5 | minor | "Todas as métricas estimam os valores da população real" overstates what the weights do for ROC-AUC. | Fixed. Section 3.2 b. |
| 6 | minor | F1 not expanded. | Fixed. Expanded in 2.3 and added to the abbreviation list. |
| 7 | minor | Lu et al. p. 158 and Han et al. 1% not verified. | Verified on the papers. Lu et al. state the 5-fold cross-validation on printed page 158. Han et al. fix the average false positive rate at 1% for the Backblaze datasets, computed per day; the sentence in 2.3 now says so. |
| 8 | minor | Validation drives are censored at the same cutoff as train drives. | Fixed. |
| 9 | nit | Bins are half-open. | Fixed. The bins are written as 0 to 6, 7 to 13, and so on. |
| 10 | nit | The 62% is a ratio of point estimates. | Fixed. |
| 11 | nit | Double negative in the SHA-256 sentence. | Fixed. |
| 12 | nit | Untranslated quotations; informal source for the encoding. | Fixed. Quotations translated or paraphrased; the source is now the smartmontools documentation. |
| 13 | nit | One row of Quadro 2 covers two models. | Fixed. |

## Round 2: 8.5/10

The first attempt at this round failed with an upstream provider error and produced no review; this is the rerun, on the text with the other reviewer's round-2 fixes applied. Sub-scores: factual fidelity 8.5, method and statistics 9, literature 9.5, template and ABNT 9.5, writing 9, focus 9.5. All 13 round-1 findings were judged resolved.

| # | Severity | Finding | Outcome |
|---|---|---|---|
| 1 | major | "Reproduziu todas as métricas com diferença inferior a 5 × 10⁻⁷" is false: 12 values of the two `metrics.json` files differ by more, up to 3.6 × 10⁻⁵. | Fixed, and confirmed by comparing the two files. The article says 4 × 10⁻⁵. The same claim was corrected in `results/README.md` and `docs/ISSUES.md` #1. |
| 2 | minor | The 30-day interval for exponent 1.0 against 0.5 was printed as [0,000; 0,006] although it contains zero. | Fixed. The text gives [−0,0004; 0,0059] and says it includes zero. |
| 3 | minor | Largest IPCW difference is 0.011, not 0.012 (subtraction of rounded values). | Fixed. |
| 4 | minor | The low-decile underprediction starts at 90 days, not at 180. | Fixed. |
| 5 | minor | 0.169, not 0.168, of 0.273 (subtraction of rounded values). | Fixed. |
| 6 | minor | "No conjunto completo" is ambiguous. | Fixed: "Na escala completa". |

## Round 3: no review

The run returned 256,000 characters of `<br>` tags and whitespace and no text. With the failed first attempt at round 2, that is two unusable runs out of four, so GLM-5.3 was replaced as a reviewer by DeepSeek V4.1 Flash and Claude Opus 5.5 (`audit/deepseek-v4-1-flash-article-review.md`, `audit/opus-5-5-article-review.md`). Its last valid score is the 8.5/10 of round 2. GPT-6.1 Sol checked the six round-2 fixes against the artifacts and found all of them correct.
