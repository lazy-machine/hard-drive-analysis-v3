# Article verification for issue #5

Checked on 2026-11-10 against `main-article.md` and `references.md`.

The owner supplied the author line. No `[PREENCHER` placeholder remains. All 30 bibliography entries map to works in the source index. The index now includes Harrell (1982), Ke (2017), and Smartmontools (2025), and identifies the published 2023 version of Kvamme and Borgan rather than only its 2019 preprint.

## Results used by the article

The issue originally named `results/full-2026-10-27/`. The article now explicitly uses `results/full-2026-11-09-leakfix/`, after the metadata leakage correction. The October run remains historical evidence, rather than the target for the current tables. For example, its seven-day SMART gain is 0.300, whereas the corrected run and article report 0.302.

Both `results.md` and `analysis.md` in `build/report/` match their archived counterparts in `results/full-2026-11-09-leakfix/report/` byte for byte. The article's discrimination, alert, remaining-life, and calibration tables were compared with these reports. Checked values include the 8,981 test drives, 1,784 failures, 368 silent failures, the five horizons of ROC-AUC and PR-AUC, the 1.87% false-alarm rate and 3.82% precision, and the 2024/2025 calibration ratios of 1.18/2.18. Decimal commas and rounding explain presentation differences.

## Limitations retained in the article

Section 4.2 reports the capacity shift and lower discrimination for drives of at least 16 TB. Section 4.5 reports test-period drift and the retirement diagnostic. Section 5 retains the limits from label circularity, possible informative censoring, and the lack of rolling-origin evaluation. Closing the article issue does not resolve those methodological limitations or GitHub issue #4.

## Source access in a fresh clone

`article/research/` is absent in this checkout and remains gitignored. The index links to publications so citation checking does not require the original offline collection. This review checks bibliography coverage; it does not claim a new full-text audit of every quotation.

The publisher pages for LightGBM and the published Brier-score paper provide PDF links. A local full-text copy of Harrell (1982) was not obtained. The Smartmontools website returned an access-denied page during this check. The index's existing “Not saved” section records other unavailable copies, including Platt (1999). These access limits do not require inventing or removing references, and third-party files are not added to the repository.
