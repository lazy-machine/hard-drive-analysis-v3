# Do SMART attributes (smartctl) meaningfully predict HDD failure? Evidence for and against

Scope note for the report writer: stance labels are relative to this project's methodology (Backblaze 2016–2025 daily rows; raw SMART 5, 9, 187, 188, 197, 198 and normalized 1, 3, 7; 7/30-day deltas; context features; a context-only ablation; a log-sum rule-of-thumb baseline). "In favor" = supports the claim that SMART carries useful predictive signal for this setup. "Against" = limits or undermines it. "Mixed" = both. Peer-review status is flagged on every source. Figures were read from the primary PDF text where marked "(read from PDF)"; other figures come from abstracts or official pages.

## Q1. What did the foundational studies (2002–2007) find?

### Takeaway
The early record is split. Google (FAST 2007) found that a handful of SMART counters (scan errors, reallocations, offline reallocations, probational/pending counts) raise 60-day failure risk 14–39x, yet concluded SMART alone cannot predict individual drive failures because 36–56% of failed drives showed no signal. The UCSD group (2002, 2005) showed that statistical/ML methods on SMART beat the manufacturer thresholds by a wide margin (≈50% vs 3–10% detection at low false-alarm rates) on small datasets.

### Cited Findings

#### Annotated bibliography index (all sources used in these notes)

| # | Citation | Venue / year | Peer-reviewed? | Stance | Aspect |
|---|---|---|---|---|---|
| 1 | Pinheiro, E., Weber, W.-D., Barroso, L. A. "Failure Trends in a Large Disk Drive Population." | USENIX FAST '07, 2007 | Yes | Mixed | Strong per-attribute risk ratios; silent failures cap recall; no label circularity in their data |
| 2 | Schroeder, B., Gibson, G. A. "Disk Failures in the Real World: What Does an MTTF of 1,000,000 Hours Mean to You?" | USENIX FAST '07, 2007 (Best Paper) | Yes | Mixed (indirect) | Context/age and operating conditions drive replacement rates; does not test SMART |
| 3 | Hughes, G. F., Murray, J. F., Kreutz-Delgado, K., Elkan, C. "Improved Disk-Drive Failure Warnings." IEEE Trans. Reliability 51(3):350–357 | IEEE TR, 2002 | Yes | In favor | Rank-sum tests on SMART beat vendor thresholds |
| 4 | Murray, J. F., Hughes, G. F., Kreutz-Delgado, K. "Machine Learning Methods for Predicting Failures in Hard Drives: A Multiple-Instance Application." JMLR 6:783–816 | JMLR, 2005 | Yes | In favor (with caveats) | ML/nonparametric tests ≫ vendor thresholds; simple rank-sum close to SVM |
| 5 | Bairavasundaram, L. N., Goodson, G. R., Pasupathy, S., Schindler, J. "An Analysis of Latent Sector Errors in Disk Drives." | ACM SIGMETRICS '07, 2007 | Yes | In favor (mechanism) | Sector errors cluster in time/space, i.e. degradation counters persist and grow |
| 6 | Li, J., et al. "Hard Drive Failure Prediction Using Classification and Regression Trees." | IEEE/IFIP DSN 2014 | Yes | In favor | >95% FDR at <0.1% FAR on 25,792 drives (SMART only) |
| 7 | Ma, A., Douglis, F., Lu, G., Sawyer, D., Chandra, S., Hsu, W. "RAIDShield: Characterizing, Monitoring, and Proactively Protecting Against Disk Failures." (journal version ACM TOS, DOI 10.1145/2820615) | USENIX FAST '15, 2015 | Yes | In favor | Single-attribute threshold (reallocated sectors) works in production |
| 8 | Botezatu, M. M., Giurgiu, I., Bogojeska, J., Wiesmann, D. "Predicting Disk Replacement towards Reliable Data Centers." DOI 10.1145/2939672.2939699 | ACM KDD 2016 | Yes | In favor (label = replacement) | ~98% accuracy predicting replacement 10–15 days ahead |
| 9 | Xu, Y., Sui, K., et al. "Improving Service Availability of Cloud Systems by Predicting Disk Error." (Microsoft) | USENIX ATC '18, 2018 | Yes | Mixed / against SMART-only | SMART-only TPR 27.6% at 0.1% FPR; random CV inflates TPR 91.6% vs 36.5% online |
| 10 | Lu, S., Luo, B., Patel, T., Yao, Y., Tiwari, D., Shi, W. "Making Disk Failure Predictions SMARTer!" pp. 151–167 | USENIX FAST '20, 2020 | Yes | Against SMART-only | SMART-only mean F 0.46 vs 0.95 MCC with performance + location |
| 11 | Amram, M., Dunn, J., Toledano, J. J., Zhuo, Y. D. "Interpretable Predictive Maintenance for Hard Drives." Machine Learning with Applications (Elsevier), 2021; arXiv:2102.06509 | MLWA 2021 | Yes (journal) | Mixed | Backblaze data; ~50% sensitivity at ~10% false alarms for 30–90-day horizon |
| 12 | Han, S., Lee, P. P. C., et al. "StreamDFP" (stream mining / online transfer learning for disk failure prediction) | IEEE Trans. Computers (2022, inferred from file name) | Yes | Mixed | Concept drift and minority models degrade SMART models across models |
| 13 | Zhang, J., et al. "Transfer Learning Based Failure Prediction for Minority Disks in Large Data Centers of Heterogeneous Disk Systems" (TLDFP) | 2019 (venue not confirmed) | Likely yes | Against naive cross-model use | Standard SMART ML fails on minority/heterogeneous disk models |
| 14 | Pinciroli, R., Yang, L., Alter, J., Smirni, E. "The Life and Death of SSDs and HDDs: Similarities, Differences, and Prediction Models." arXiv:2012.12373 | arXiv preprint, 2020 | **No** | Mixed | Backblaze; young vs old drive failures similar; head-positioning time informative |
| 15 | Züfle, M., Krupitzer, C., Erhard, F., Grohmann, J., Kounev, S. "To Fail or Not to Fail: Predicting Hard Disk Drive Failure Time Windows." | MMB 2020 (Springer LNCS chapter) | Yes | In favor (weak external validity) | F1 98% on 369 disks; time-to-failure hit rate 84.9% |
| 16 | Beach, B. "Hard Drive SMART Stats." Backblaze blog, 2014-11-12 | Company blog | **No** (primary operator source) | In favor + circularity evidence | 5 attributes; SMART 187 > 0 schedules replacement |
| 17 | Klein, A. "What SMART Stats Tell Us About Hard Drives." Backblaze blog, 2016-10-06 | Company blog | **No** | Mixed | 76.7% of failed vs 4.2% of operational drives had a non-zero value in the 5 attributes; 23.3% silent |
| 18 | Backblaze. "Using Machine Learning to Predict Hard Drive Failures." Backblaze blog, ~Oct 2021 (guest work by Interpretable AI) | Company blog | **No** | Mixed | SMART 5 most important; SMART 197 low value short-term |
| 19 | Backblaze Drive Stats Team. "Backblaze Drive Stats for Q3 2024." | Company blog, 2024 | **No** | Circularity evidence | Reactive vs proactive failure definitions; dataset has no flag for which |
| 20 | Backblaze Drive Stats Team. "Backblaze Drive Stats for Q3 2025" ("Defining a failure"), 2025-11-11 | Company blog | **No** | Circularity evidence | Uncorrectable errors are the main replacement signal; failure = disappearance + Jira ticket logic |
| 21 | Rosenthal, D. S. H. "More on Failures from FAST 2020." DSHR's blog, 2020-03-24 | Blog commentary | **No** | Context | Summarizes FAST '15/'20 results |

#### Pinheiro, Weber & Barroso (Google), FAST 2007 — Mixed (read from PDF)
- Abstract: several SMART parameters "correlate highly with failures," yet "models based on SMART parameters alone are unlikely to be useful for predicting individual drive failures." Temperature and activity correlated with failure much less than previously reported. — [Pinheiro et al., FAST 2007 (PDF)](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)
- Failure definition: "a drive is considered to have failed if it was replaced as part of a repairs procedure"; upgrades excluded; failure time = replacement time, sometimes days after the event. — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)
- The SMART parameters studied "were not in use as part of the repairs diagnostics procedure at the time," so "there is no risk of false (forced) correlations between these signals and repair outcomes." This is the clean-label condition that Backblaze data do not satisfy (see Q6). — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)
- Critical thresholds (risk of failure within 60 days vs drives with zero counts), all at a threshold of 1: first scan error → 39x; first reallocation → over 14x; first offline reallocation → over 21x; first probational (pending) count → 16x. About 2% of drives had non-zero probational counts. — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)
- Silent failures: "over 56%" of failed drives had no count in any of the four strong signals; adding all other SMART parameters (except temperature), "over 36% of all failed drives had zero counts on all variables"; adding a temperature heuristic still left about 36% with no signal. The authors add that usable models with low false-positive rates "are in fact likely to do much worse than these limits might suggest." — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)
- AFR by age ranged from 1.7% (first year) to over 8.6% (3-year-olds), but the 3–4-year AFR "is more strongly influenced by the underlying reliability of the particular models in that vintage than by disk drive aging effects." Age and model are confounded. — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)
- They suggest models using signals beyond SMART (performance anomalies, OS/application signals) "could achieve significantly better accuracies." FAST 2020 (Lu et al.) later tested this. — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)

#### Schroeder & Gibson (CMU), FAST 2007 — Mixed/indirect
- About 100,000 disks, some for a full 5-year life. Datasheet MTTF of 1,000,000–1,500,000 h implies AFR ≤ 0.88%, but field annual replacement rates were typically >1%, commonly 2–4%, up to 13% on some systems. — [USENIX FAST '07 page](https://www.usenix.org/conference/fast-07/disk-failures-real-world-what-does-mttf-1000000-hours-mean-you); [paper HTML](https://static.usenix.org/event/fast07/tech/schroeder/schroeder_html/)
- Replacement rates rise steadily with age ("significant early onset of wear-out degradation") instead of showing infant mortality; SCSI/FC/SATA differ little, suggesting operating conditions matter more than drive type. — [USENIX FAST '07 page](https://www.usenix.org/conference/fast-07/disk-failures-real-world-what-does-mttf-1000000-hours-mean-you)
- Relevance: the outcome is replacement (operator decision), and age/environment carry signal by themselves, which supports including days-in-service and context, and a context-only ablation. The paper does not evaluate SMART. — same source

#### Hughes, Murray, Kreutz-Delgado & Elkan, IEEE Trans. Reliability 2002 — In favor
- Citation: IEEE Trans. Reliability 51(3):350–357, Sept 2002 (author list includes C. Elkan). — [reference list in arXiv:1707.01952](https://arxiv.org/pdf/1707.01952)
- As summarized by the same group in 2005: on a Quantum dataset of 3,744 drives (36 failed, 14 attributes), rank-sum tests raised detection to "as much as 40–60%" at acceptably low false-alarm rates, versus manufacturers' own estimate of 3–10% detection for in-drive SMART thresholds (FAR ~0.1%/yr). An OR of single-attribute rank-sum tests did slightly better than the multivariate test at low false-alarm rates. — [Murray et al., JMLR 2005 (PDF)](https://jmlr.org/papers/volume6/murray05a/murray05a.pdf)

#### Murray, Hughes & Kreutz-Delgado, JMLR 2005 — In favor, with caveats (read from PDF)
- Data: 369 drives of one model (178 good, 191 failed), 61 attributes. Good drives came from a manufacturer reliability test in a controlled environment; failed drives were user returns, so the authors note the populations differ by environment as well as health. — [Murray et al. 2005](https://jmlr.org/papers/volume6/murray05a/murray05a.pdf)
- Best: SVM 50.6% detection with 0% measured false alarms. Rank-sum (4 attributes): 28.1% at 0 false alarms; 52.8% at 0.7% false alarms (at most one false alarm in the test set). Compared with 3–10% detection / 0.1–0.3% false alarms for in-drive thresholds. Rank-sum trains ~100x faster than the SVM with fewer parameters. — [Murray et al. 2005](https://jmlr.org/papers/volume6/murray05a/murray05a.pdf)
- "Each manufacturer develops and uses its own set of attributes and algorithm for failure prediction." — [Murray et al. 2005](https://jmlr.org/papers/volume6/murray05a/murray05a.pdf)

#### Bairavasundaram et al. (NetApp/UW-Madison), SIGMETRICS 2007 — In favor (mechanism)
- 1.53 million drives over 32 months, nearline and enterprise. Latent sector errors are not independent, vary by drive type, and show spatial and temporal locality. — [NetApp ATG summary](https://netapp.com/atg/publications/publications-an-analysis-of-latent-sector-errors-in-disk-drives-20074817); [UW ADSL page](https://research.cs.wisc.edu/adsl/Publications/latent-sigmetrics07.html); [PDF](https://pages.cs.wisc.edu/~remzi/Classes/739/Fall2015/Papers/latent-sigmetrics07.pdf)
- Roughly 3.5% of drives developed a latent sector error (secondary figure). — [Wikipedia "Bad sector"](https://en.wikipedia.org/wiki/Bad_sector). A blog reports 8.5% nearline vs 1.9% enterprise; I could not verify this against the paper. — [StorageMojo (blog)](https://storagemojo.com/2008/02/18/latent-sector-errors-in-disk-drives/)

### Inferences
- The two foundational camps do not really contradict each other. Google measured a ceiling on recall at low false-alarm rates (≥36% silent). UCSD measured improvement over vendor thresholds on small, controlled datasets. Both point to SMART being informative for a subset of failures, not all of them.
- Temporal locality of sector errors (Bairavasundaram) supports the project's 7/30-day delta features: counters that start moving tend to keep moving.
- Murray 2005 has a population confound (lab-tested good drives vs field returns), so its detection rates are probably optimistic for a field fleet like Backblaze's.

### Gaps
- I did not retrieve the Hughes 2002 paper itself; its numbers come from the 2005 JMLR summary. The DOI (10.1109/TR.2002.802886) is from memory and was not verified in this session.
- Pinheiro et al.'s exact fleet size was not confirmed from the extracted text (commonly cited as >100,000 drives; not verified here).

## Q2. Which individual SMART attributes are most and least predictive?

### Takeaway
Media-degradation counters (reallocated sectors 5, pending 197, offline uncorrectable 198, reported uncorrectable 187, and Google's scan errors) are the most consistently predictive across Google, EMC, Backblaze and Alibaba-scale studies. Seek/read error rates (normalized 1, 7) and spin-up (3) are vendor-specific and weak or ambiguous. Power-on hours (9) ranks high in some studies, which reflects age as context.

### Cited Findings
- Backblaze watches five attributes: 5 (Reallocated Sectors Count), 187 (Reported Uncorrectable Errors), 188 (Command Timeout), 197 (Current Pending Sector Count), 198 (Offline Uncorrectable). A non-zero RAW value on any prompts investigation. — [Klein, Backblaze 2016](https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/) **[Mixed; non-peer-reviewed]**
- 76.7% of failed drives had one or more of the five above zero, versus 4.2% of operational drives. SMART 189 (High Fly Writes, under review): 47.0% of failed vs 16.4% of operational. — [Klein, Backblaze 2016](https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/)
- SMART 187: drives with zero uncorrectable errors rarely fail. SMART 1 (Read Error Rate): "The raw value has different structure for different vendors and is often not meaningful as a decimal number"; lower normalized values have higher failure rates but not monotonically. SMART 12 (power cycles) correlates with failure; its correlation with age is weak (0.05). — [Beach, Backblaze 2014](https://www.backblaze.com/blog/hard-drive-smart-stats/) **[non-peer-reviewed]**
- Google: scan errors (39x), offline reallocations (21x), probational counts (16x), reallocations (14x) were the four strong signals. Seek errors were widespread (>72% of drives had them) and their trend was unclear and manufacturer-dependent. — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)
- EMC (~1 million SATA disks, six models, up to 5 years): reallocated sector count correlates strongly with impending failure. The journal version adds that "the relative efficacy of reallocated sectors and medium errors varies across disk models." — [Ma et al., FAST 2015](https://www.usenix.org/conference/fast15/technical-sessions/presentation/ma); [ACM TOS record](https://api.crossref.org/works/10.1145%2F2820615) **[In favor; peer-reviewed]**
- Backblaze data (Seagate ST12000NM0007, >35,000 drives, through Q1 2020), optimal survival trees: SMART 5 ranked most important; SMART 197 "has diminished in value so much that it is not considered important in assessing the short-term health." — [Backblaze ML blog, 2021](https://www.backblaze.com/blog/using-machine-learning-to-predict-hard-drive-failures/) (as summarized in search results; underlying paper: [Amram et al., MLWA 2021](https://www.sciencedirect.com/science/article/pii/S2666827021000219)) **[Mixed]**
- Large e-commerce operator (380,000 HDDs, 64 sites): highest single-attribute Youden J indexes were 9R (power-on hours, J 0.21), 9N (0.19), 3R (spin-up time, 0.18), 5R (0.18), 194N/194R (temperature, 0.18/0.15), 1R (0.14). J values in this range are modest; the best performance metrics reached J 0.45. — [Lu et al., FAST 2020 (PDF)](https://weisongshi.org/papers/lu20-diskfailure.pdf) (read from PDF) **[Against SMART-only]**
- Lu et al. show a randomly chosen failed disk from Baidu's public hourly dataset whose 12 normalized SMART attributes "do not vary noticeably" for 477 hours before failure. — [Lu et al. 2020](https://weisongshi.org/papers/lu20-diskfailure.pdf)
- A Backblaze-based preprint finds head-positioning time helps distinguish failures. — [Pinciroli et al., arXiv 2020](https://arxiv.org/abs/2012.12373) **[non-peer-reviewed]**

### Inferences
- The project's feature set (5, 187, 188, 197, 198 raw + deltas) matches the attributes with the strongest independent support. Normalized 1, 3, 7 are the attributes with the weakest and most vendor-dependent semantics; low importance for them would be consistent with prior work.
- SMART 9 doubles as a context feature (age). The context-only ablation probably already contains most of the signal from 9, so 9 should be counted as context, not SMART, when interpreting the ablation gap.

### Gaps
- I found no peer-reviewed per-attribute ranking on the full 2016–2025 Backblaze data across all models; existing rankings are model-specific (e.g., the single Seagate 12 TB model in Amram et al.).
- SMART 188 (Command Timeout) had no published quantitative ranking in the sources I retrieved.

## Q3. How large is the share of "silent" failures, and does it cap any SMART model?

### Takeaway
Silent failures, meaning drives that fail with no non-zero degradation counter, are a large share in every operator dataset that reports them: about 36–56% at Google (2007) and 23.3% at Backblaze (2016, five attributes). This sets a hard recall ceiling for any rule or model that depends only on those counters. ML can recover some silent failures through weaker attributes and trends, but the large-fleet studies (Google, Microsoft, Lu et al.) all find SMART-only recall to be the weak point.

### Cited Findings
- Google: >56% of failed drives had zero counts on the four strong signals, and >36% had zero counts on all SMART variables. "Models based only on those signals can never predict more than half of the failed drives." — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf) **[Against, peer-reviewed; older fleet, 2005–2006 drives]**
- Backblaze: 23.3% of failed drives had no warning in the five attributes (complement of 76.7%). — [Klein, Backblaze 2016](https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/) **[Mixed, non-peer-reviewed]**
- Lu et al.: SMART-attribute-based models "have a very high false negative rate" across all five model types; adding performance and location features "decreases the FNR significantly." — [Lu et al., FAST 2020](https://weisongshi.org/papers/lu20-diskfailure.pdf) (read from PDF) **[Against SMART-only]**
- Microsoft Azure: disk errors appear on average 15.8 days before complete failure and show up in system-level signals that SMART does not capture; "that is why incorporating the system-level signals is better than using SMART alone." — [Xu et al., ATC 2018 (PDF)](https://www.microsoft.com/en-us/research/uploads/prod/2018/04/DiskErrorPrediction_cameraReady_final.pdf) (read from PDF)
- DSHR commentary: earlier SMART-based work flagged failures too close to the actual failure to allow proactive replacement; Lu et al.'s performance metrics separated earlier. — [Rosenthal, DSHR blog 2020](https://blog.dshr.org/2020/03/more-on-failures-from-fast-2020.html) **[non-peer-reviewed commentary]**
- Context on what "failure" includes: Elerath & Shah (cited in Pinheiro) report 15–60% of user-returned "failed" drives are no-defect-found at the manufacturer; Hughes et al. saw 20–30% "no problem found." Some silent "failures" may not be drive failures at all. — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)

### Inferences
- For this project, the share of failed drives with all-zero 5/187/188/197/198 at their last row gives an empirical recall ceiling for the log-sum rule. Reporting it would turn the literature's 23–56% into a number specific to this dataset.
- Silent failures probably include electronics, firmware, controller/cable, and sudden head failures. Those mechanisms do not move media counters, so this ceiling is physical and more model capacity will not remove it.
- The Backblaze 23.3% is lower than Google's 36–56%. One plausible reason is that Backblaze's own proactive removals are triggered by those same counters (see Q6), which mechanically raises the share of "failures" with non-zero counters. This is an inference, not a measured effect.

### Gaps
- No updated (post-2016) Backblaze figure for the silent-failure share was found.
- No source breaks silent failures down by root cause on a large fleet.

## Q4. Does SMART add information beyond age/model/context? Do vendor-specific semantics undermine cross-model use?

### Takeaway
Yes, SMART adds information beyond context, but less than the headline numbers suggest. In the large-fleet studies that ran ablations, SMART-only models were the weakest group (Lu et al.: mean F 0.46; Microsoft: TPR 27.6% at 0.1% FPR), and other signal families (performance, system logs) beat SMART alone. Heterogeneous SMART semantics across vendors and models are well documented and motivate per-model normalization or transfer learning.

### Cited Findings
- Lu et al. feature-group ablation, 10-day horizon (mean over Bayes, RF, GBDT, LSTM, CNN-LSTM; read from figure-table text in PDF): **S (SMART only)**: precision 0.52, recall 0.43, F 0.46, MCC 0.41; best single model CNN-LSTM F 0.58 / MCC 0.54; RF F 0.54. **P (performance only)**: mean F 0.73 / MCC 0.71 (GBDT F 0.95). **SPL (all)**: CNN-LSTM MCC 0.95, RF MCC 0.77. Performance metrics alone beat SMART alone. — [Lu et al., FAST 2020](https://weisongshi.org/papers/lu20-diskfailure.pdf) **[Against SMART-only; peer-reviewed]**. Caveat: these numbers were reconstructed from the extracted PDF text of Figure 8, where each table precedes its group label; the label-to-table mapping was checked against the text's statement that CNN-LSTM reaches MCC 0.95 and RF 0.77 for SPL.
- Lu et al.: when only SMART is available, RF and GBDT perform about as well as LSTM/CNN-LSTM: "there is no need to employ complex DNNs when only SMART data are available." — [Lu et al. 2020](https://weisongshi.org/papers/lu20-diskfailure.pdf)
- Lu et al. failure label: a disk is failed "when the production data center operator deems a disk necessary to be replaced," i.e. a failed read/write that persists after restart. — [Lu et al. 2020](https://weisongshi.org/papers/lu20-diskfailure.pdf)
- Microsoft Azure (three datasets): average TPR at FPR 0.1% was 27.6% for SMART-only features, 30.3% with system-level signals, 35.8% with system signals plus feature selection. Labels came from root-cause analysis of service issues by field engineers, not from SMART. — [Xu et al., ATC 2018](https://www.microsoft.com/en-us/research/uploads/prod/2018/04/DiskErrorPrediction_cameraReady_final.pdf) (read from PDF) **[Mixed]**
- Google: age-group AFR differences mostly reflect model vintage, so age and model are confounded; signals that act consistently across age/model groups carry real information. — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf) **[Supports the ablation design]**
- Schroeder & Gibson: replacement rates rise with age from early in life, and operating conditions outweigh interface type. A context-only model has real signal to work with. — [Schroeder & Gibson, FAST 2007](https://www.usenix.org/conference/fast-07/disk-failures-real-world-what-does-mttf-1000000-hours-mean-you)
- Vendor semantics: "SMART stats are inconsistent from hard drive to hard drive"; "different disk drive manufacturers report SMART stats differently"; SMART 187 is reported consistently across manufacturers. — [Beach, Backblaze 2014](https://www.backblaze.com/blog/hard-drive-smart-stats/). Not all manufacturers report both 197 and 198. — [Klein, Backblaze 2016](https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/) **[non-peer-reviewed]**
- "Each manufacturer develops and uses its own set of attributes and algorithm"; Hughes 2002's 14 attributes and Murray 2005's 61 overlap "but with different names." — [Murray et al., JMLR 2005](https://jmlr.org/papers/volume6/murray05a/murray05a.pdf)
- Relative usefulness of reallocated sectors vs medium errors varies by disk model. — [Ma et al., ACM TOS](https://api.crossref.org/works/10.1145%2F2820615)
- TLDFP: traditional ML "fail[s] to deliver satisfactory predictive performance" on heterogeneous minority disk models; proposes transfer learning. — [Zhang et al., TLDFP (BIT record)](https://pure.bit.edu.cn/en/publications/transfer-learning-based-failure-prediction-for-minority-disks-in-/) **[Against naive cross-model pooling]**
- StreamDFP: concept drift in streaming SMART logs; drift adaptation gives up to 51.8% F1 gain on minority models; evaluated on 12 HDD datasets from Backblaze and Alibaba plus 3 SSD datasets. — [Han et al., StreamDFP (PDF)](https://www.cse.cuhk.edu.hk/~pclee/www/pubs/tc22streamdfp.pdf) **[Mixed]**
- Prior heterogeneity remedies include selecting common SMART attributes across models and normalizing distributions; meta-learning (MDP-MAML) addresses heterogeneity, aging and minority samples. — [Guan et al., FITEE 2023](https://www.fitee.zjujournals.com/en/article/doi/10.1631/FITEE.2200488)
- Backblaze preprint: young and old drives "do not present many differences in their failures." — [Pinciroli et al., arXiv 2020](https://arxiv.org/abs/2012.12373) **[non-peer-reviewed]**

### Inferences
- The project's context-only vs SMART comparison is the same design as Lu et al.'s and Microsoft's ablations. Those papers support the design and set expectations: a positive but bounded SMART gain, concentrated in drives with moving degradation counters.
- Restricting to raw counters (5, 187, 197, 198) plus vendor and model features is consistent with the literature's warning that normalized and error-rate attributes are vendor-encoded. A per-vendor or per-model breakdown of the SMART gain would check the cross-model concern directly.
- The 2016–2025 window spans many model generations. StreamDFP's drift results suggest that random train/test splits across years would overstate performance (see also Q5).

### Gaps
- No peer-reviewed study was found that runs exactly a "context-only vs context+SMART" ablation on Backblaze data.
- The TLDFP venue and exact numbers were not retrieved.

## Q5. Do simple threshold rules perform comparably to ML models? How does evaluation design affect the comparison?

### Takeaway
The answer depends on the baseline. Vendor in-drive thresholds are poor (3–10% detection). Simple operator rules on degradation counters, such as "any non-zero 5/187/197/198" or a reallocated-sector threshold, capture much of what ML captures at the cost of false positives, and EMC deployed one in production. Published ML gains are often inflated by random cross-validation: Microsoft measured 91.6% TPR under cross-validation vs 36.5% under online (time-ordered) evaluation. I found no peer-reviewed head-to-head of a counter-sum rule vs ML on Backblaze data.

### Cited Findings
- In-drive SMART thresholds: manufacturer-estimated 3–10% detection at 0.1–0.3% false alarms. — [Murray et al., JMLR 2005](https://jmlr.org/papers/volume6/murray05a/murray05a.pdf)
- A nonparametric rank-sum test on 4 attributes gave 52.8% detection at 0.7% false alarms vs the SVM's 50.6% at 0%, with ~100x faster training. Simple statistical tests got close to the SVM. — [Murray et al. 2005](https://jmlr.org/papers/volume6/murray05a/murray05a.pdf) **[In favor of simple methods]**
- EMC RAIDShield: proactive replacement based on reallocated-sector monitoring "has been incorporated into our product" and eliminates 88% of triple disk errors (80% of RAID failures); RAID-level analysis raises coverage to 98% of triple errors in RAID-6. — [Ma et al., FAST 2015](https://www.usenix.org/conference/fast15/technical-sessions/presentation/ma) **[In favor of simple rules]**
- DSHR summary: EMC "could effectively predict SATA disk failures by observing the reallocated sector count" and proactively replace drives above a threshold. — [Rosenthal 2020](https://blog.dshr.org/2020/03/more-on-failures-from-fast-2020.html) **[non-peer-reviewed]**
- Backblaze's 5-attribute "any non-zero" heuristic: 76.7% of failed drives flagged vs 4.2% of operational drives (no horizon given). — [Klein 2016](https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/)
- ML results reported as high: CART on 25,792 drives, >95% of failures predicted at <0.1% FAR; follow-up on 121,698 drives, DT >93% at <0.01% FAR. — [Li et al., DSN 2014 (authors' copy)](https://nbjl.nankai.edu.cn/_upload/article/files/b8/df/788a01c9442a8597ae8379cb37f1/14fde84e-654a-4fe7-a3c9-f788efa70fce.pdf) **[In favor; no independent replication found]**
- IBM: ~98% accuracy predicting disk replacement, 10–15 days ahead, on >30,000 disks from two manufacturers over 17 months; target is replacement. — [Botezatu et al., KDD 2016 (Unpaywall/ACM)](https://unpaywall.org/10.1145%2F2939672.2939699); [IBM Research](https://research.ibm.com/publications/predicting-disk-replacement-towards-reliable-data-centers)
- Backblaze data, interpretable trees (Optimal Classification/Survival Trees) for a 30–90-day horizon: sensitivity about 50% at a false alarm rate around 10%. Much more modest than the 95%/0.1% claims. — [Amram et al., MLWA 2021 (arXiv)](https://arxiv.org/pdf/2102.06509); [Backblaze ML post](https://www.backblaze.com/blog/using-machine-learning-to-predict-hard-drive-failures/) **[Mixed]**
- Züfle et al.: F1 up to 98.0% (two windows) and 97.6% (multiple windows); time-to-failure hit rate 84.9% (MAE 4.5 h) on 369 disks. — [Springer Professional record](https://www.springerprofessional.de/en/to-fail-or-not-to-fail-predicting-hard-disk-drive-failure-time-w/17780208). The 369-disk size matches the Murray 2005 dataset (178 good lab-tested + 191 field-returned); that identity is my inference, not confirmed.
- Evaluation design: Microsoft found cross-validation on Dataset 1 gave TPR 91.64% at FPR 0.1%, while online (train on past, test on future) gave 36.50%. Random splits put future data in training, so "cross-validation may not always reflect the actual effectiveness" and "online prediction should be used in practice." — [Xu et al., ATC 2018](https://www.microsoft.com/en-us/research/uploads/prod/2018/04/DiskErrorPrediction_cameraReady_final.pdf) (read from PDF) **[Key methodological evidence]**
- Not peer-reviewed: a personal GitHub project reports an adjustable-threshold baseline catching about half of failing drives at 1% false alarms vs 81% for LightGBM. — [driveguard (GitHub)](https://github.com/chetank-github/driveguard) **[non-peer-reviewed, low weight]**

### Inferences
- The project's log-sum rule is the right kind of baseline: an operator-style counter rule, not the vendor threshold straw man. The literature suggests ML should beat it mainly on recall at low false-alarm rates and on silent-ish failures with weak drift in other attributes, not by a large margin on counter-positive drives.
- The very high ML figures (95–98%) come from small or single-operator datasets, random splits, or replacement-defined labels. They should not be used as the target the project is expected to reach. The Backblaze-based Amram et al. result (~50% sensitivity at ~10% FAR for 30–90 days) is the closest comparable number.
- The project should keep time-ordered splits grouped by drive (serial). The Microsoft 91.6% vs 36.5% gap is the strongest published quantification of how much random splits inflate scores.

### Gaps
- No peer-reviewed study compares a Backblaze-style counter-sum rule against ML on Backblaze data at matched false-alarm rate and horizon.
- I could not locate the Tencent ICPP 2018 online-learning paper (Xiao et al.) in this session; it is not cited.

## Q6. Is there label circularity? How does Backblaze define a failed drive?

### Takeaway
Yes, there is direct, documented circularity. Backblaze's "failure" label includes proactive removals triggered by SMART, specifically SMART 187 > 0 (2014) and uncorrectable-error thresholds in the drive sentinel (2025). The public dataset does not distinguish proactive from reactive failures. The project's strongest features (187, 5, 197, 198) are therefore partly inputs to the labeling policy. This inflates SMART's apparent power, especially at short horizons and for the log-sum rule. Google's 2007 study explicitly avoided this; Microsoft and Lu et al. used non-SMART labels.

### Cited Findings
- 2014 definition: "Backblaze counts a drive as failed when it is removed from a Storage Pod" and replaced because it has "totally stopped working" or "shown evidence of failing soon." "Once SMART 187 goes above zero, we schedule the drive for replacement." — [Beach, Backblaze 2014](https://www.backblaze.com/blog/hard-drive-smart-stats/) **[Circularity evidence; non-peer-reviewed primary]**
- The same period's wording: "we use SMART statistics as evidence to remove a drive before it fails catastrophically." — [Backblaze 2014 (search excerpt)](https://www.backblaze.com/blog/?p=13711)
- Drives removed for non-failure reasons (e.g., pod upgrades) are not marked as failures. — [Klein, Backblaze 2016](https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/)
- Q3 2024: failures are *reactive* (drive no longer operational: won't boot, doesn't respond, won't stay up) or *proactive* (generally anything not reactive, typically when "SMART stats, FSCK (file system) checks, etc." signal difficulty). Both count as failures unless later evidence shows otherwise (example: a loosely seated drive scheduled for proactive replacement tested fine and was un-counted). The Drive Stats data carry only a 0/1 failure flag, not the reactive/proactive split. — [Backblaze Drive Stats Q3 2024](https://www.backblaze.com/blog/backblaze-drive-stats-for-q3-2024/) **[non-peer-reviewed primary]**
- Q3 2025 ("Defining a failure"): Backblaze collects SMART with smartmontools; the main signal for replacing a drive is uncorrectable medium errors. On SATA-connected Storage Pods, the drive sentinel removes a drive's access once its uncorrectable error count passes a threshold (five drives share one SATA link); on SAS pods it does not. In the data layer, a failure is a drive that disappears from the reporting population; three human-curated tables and Jira tickets resolve ambiguity: a drive logging data on the quarter's last day has not failed; a serial that is the primary in a drive-replacement ticket has failed; a clone/temporary-replacement target has not. This can create "cosmetic" failures, e.g. the Toshiba MG08ACA16TEY's 16.9% quarterly rate from firmware-update pulls of drives that were not mechanically bad. — [Backblaze Drive Stats Q3 2025](https://www.backblaze.com/blog/backblaze-drive-stats-for-q3-2025/) **[non-peer-reviewed primary]**
- Contrast: Google states the SMART parameters "were not in use as part of the repairs diagnostics procedure," so "there is no risk of false (forced) correlations." — [Pinheiro et al. 2007](https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf)
- Contrast: Microsoft labels came from field engineers' root-cause analysis of service issues. — [Xu et al., ATC 2018](https://www.microsoft.com/en-us/research/uploads/prod/2018/04/DiskErrorPrediction_cameraReady_final.pdf). Lu et al.'s label is a failed read/write that persists after restart. — [Lu et al., FAST 2020](https://weisongshi.org/papers/lu20-diskfailure.pdf)
- IBM's KDD 2016 target is replacement itself ("predicting disk replacement"), which by construction inherits whatever SMART-based replacement policy the operator used. — [Botezatu et al., KDD 2016](https://unpaywall.org/10.1145%2F2939672.2939699)
- A Backblaze-based paper notes the dataset does not document failure symptoms or root causes. — [Robust Data Preprocessing for ML-Based Disk Failure Prediction, arXiv:1912.09722](https://arxiv.org/pdf/1912.09722) **[preprint]**

### Inferences
- Mechanism in this project: when SMART 187 (or a sentinel uncorrectable-error threshold) trips, Backblaze schedules removal; the drive disappears; the last row gets `failure=1`. A model that sees 187 rising in the last 7 days is partly learning Backblaze's maintenance policy, not drive physics. The log-sum rule over 5/197/198 (and 187 if included) is especially exposed, because it nearly restates the trigger.
- The effect should be strongest at short horizons (days to weeks) and weaker at 30+ days, since a policy trigger produces a removal soon after the counter moves. Comparing the SMART gain at short vs long horizons is a practical diagnostic.
- Possible sensitivity analyses, since the dataset lacks a reactive/proactive flag: (a) drop 187 (and optionally 197/198) and re-measure the SMART-over-context gain; (b) evaluate separately on failed drives whose 187 stayed 0 until the end, a subset proactive 187 rules could not have caused; (c) report performance at a horizon that excludes the final N days before failure.
- Circularity does not mean SMART is useless. Google and Microsoft, with non-SMART labels, still found SMART informative (14–39x risk ratios; 27.6% TPR at 0.1% FPR). The project's numbers should be presented as an upper bound on SMART's operator-independent predictive power.
- The policy also changed over 2016–2025 (sentinel on SATA vs SAS pods, Jira-based failure attribution formalized in 2025), so the label-generating process is non-stationary across the study window.

### Gaps
- Backblaze has not published the sentinel's uncorrectable-error threshold value or the share of failures that were proactive vs reactive; the Q3 2024 post calls that breakdown a future project.
- It is not documented when (by date or pod type) the "187 > 0 → replace" rule applied during 2016–2025, so the strength of circularity per year cannot be quantified from public sources.
- I found no peer-reviewed paper that measures label-policy leakage in Backblaze-based failure prediction.
