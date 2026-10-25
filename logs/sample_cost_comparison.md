# Cost vs. accuracy: optimizations ON vs OFF

Generated 2026-10-25 19:10. Model gpt-6-luna via Portkey. Prices used ($/1M tokens): input 0.1, cached input 0.01, output 0.5 (see config.py).

## Optimizations ON

| Step | Input | Cached | Output | Calls | Cost | Seconds | Accuracy |
|---|---|---|---|---|---|---|---|
| Spread COST 10y | 0 | 0 | 0 | 0 (+0 cached) | $0.0000 | 0.1 | 190 passed / 0 fixed / 1 flagged |
| Spread AAPL 5y (corrupted) | 377 | 0 | 53 | 1 (+0 cached) | $0.0001 | 3.1 | 102 passed / 3 fixed / 0 flagged |
| Q1 margin (Harvey) | 8,426 | 3,379 | 606 | 6 (+0 cached) | $0.0008 | 12.2 | quotes verified 2, removed 0, figures 10/11 |
| Q2 supply chain (Harvey) | 6,558 | 0 | 405 | 4 (+0 cached) | $0.0009 | 6.4 | quotes verified 3, removed 0, figures 0/0 |
| Q1 margin, new session (Mike) | 654 | 0 | 83 | 2 (+4 cached) | $0.0001 | 2.5 | quotes verified 2, removed 0, figures 10/11 |
| **Total** | **16,015** | **3,379** | **1,147** | **13** | **$0.0019** | | Harvey/Mike facts identical: True |

| Agent | Calls | Input | Cached | Output | Cost |
|---|---|---|---|---|---|
| Checker | 1 | 377 | 0 | 53 | $0.0001 |
| Router | 3 | 1,234 | 0 | 133 | $0.0002 |
| Analyst | 9 | 14,404 | 3,379 | 961 | $0.0016 |

## Optimizations OFF

| Step | Input | Cached | Output | Calls | Cost | Seconds | Accuracy |
|---|---|---|---|---|---|---|---|
| Spread COST 10y | 2,558 | 2,432 | 488 | 1 (+0 cached) | $0.0003 | 7.5 | 190 passed / 0 fixed / 1 flagged; model audit: model flagged 1, Python 1, agreed 1, false alarms 0, missed 0 |
| Spread AAPL 5y (corrupted) | 1,903 | 1,400 | 406 | 2 (+0 cached) | $0.0003 | 4.7 | 102 passed / 3 fixed / 0 flagged; model audit: model flagged 1, Python 1, agreed 1, false alarms 0, missed 0 |
| Q1 margin (Harvey) | 15,419 | 3,379 | 597 | 6 (+0 cached) | $0.0015 | 11.2 | quotes verified 3, removed 0, figures 8/9 |
| Q2 supply chain (Harvey) | 12,673 | 0 | 393 | 4 (+0 cached) | $0.0015 | 6.9 | quotes verified 3, removed 0, figures 0/0 |
| Q1 margin, new session (Mike) | 15,784 | 3,379 | 600 | 6 (+0 cached) | $0.0016 | 14.6 | quotes verified 3, removed 0, figures 8/8 |
| **Total** | **48,337** | **10,590** | **2,484** | **19** | **$0.0051** | | Harvey/Mike facts identical: False |

| Agent | Calls | Input | Cached | Output | Cost |
|---|---|---|---|---|---|
| Checker | 3 | 4,461 | 3,832 | 894 | $0.0005 |
| Router | 3 | 1,225 | 0 | 140 | $0.0002 |
| Analyst | 13 | 42,651 | 6,758 | 1,450 | $0.0044 |

**Savings:** optimizations cut cost by 64% ($0.0051 → $0.0019) and input tokens by 67%.

Headlines (for a side-by-side quality read):

- [on] Q1 margin (Harvey): Apple’s gross margin rose from 44.1% in FY2023 to 46.9% in FY2025, with management attributing the FY2025 improvement over FY2024 to stronger Services margins a
- [on] Q2 supply chain (Harvey): Management identifies supplier and outsourcing arrangements, and warns that tariffs, trade disputes, and materials availability can disrupt supply and affect co
- [on] Q1 margin, new session (Mike): Apple’s gross margin rose from 44.1% in FY2023 to 46.9% in FY2025, with management attributing the FY2025 improvement over FY2024 to stronger Services margins a
- [off] Q1 margin (Harvey): Apple’s gross margin rose from 44.1% in FY2023 to 46.9% in FY2025; the clearest disclosed driver over the period was services, whose margin rate and sales incre
- [off] Q2 supply chain (Harvey): Management identifies tariff-related supply chain and component availability exposure, alongside reliance on outsourcing partners and a broad supplier base.
- [off] Q1 margin, new session (Mike): Apple’s gross margin rose from 44.1% in FY2023 to 46.9% in FY2025; management’s FY2025 discussion attributes the FY2025 increase versus FY2024 to higher Service
