# Cost vs. accuracy: optimizations ON vs OFF

Generated 2026-10-25 19:01. Model gpt-6-luna via Portkey. Prices used ($/1M tokens): input 1.25, cached input 0.125, output 10.0 (see config.py).

## Optimizations ON

| Step | Input | Cached | Output | Calls | Cost | Seconds | Accuracy |
|---|---|---|---|---|---|---|---|
| Spread COST 10y | 0 | 0 | 0 | 0 (+0 cached) | $0.0000 | 0.1 | 190 passed / 0 fixed / 1 flagged |
| Spread AAPL 5y (corrupted) | 377 | 0 | 52 | 1 (+0 cached) | $0.0010 | 3.3 | 102 passed / 3 fixed / 0 flagged |
| Q1 margin (Harvey) | 8,440 | 3,379 | 654 | 6 (+0 cached) | $0.0133 | 12.0 | quotes verified 3, removed 0, figures 14/14 |
| Q2 supply chain (Harvey) | 4,715 | 0 | 308 | 4 (+0 cached) | $0.0090 | 9.1 | quotes verified 2, removed 0, figures 0/0 |
| Q1 margin, new session (Mike) | 648 | 0 | 84 | 2 (+4 cached) | $0.0016 | 2.3 | quotes verified 3, removed 0, figures 14/14 |
| **Total** | **14,180** | **3,379** | **1,098** | **13** | **$0.0249** | | Harvey/Mike facts identical: True |

| Agent | Calls | Input | Cached | Output | Cost |
|---|---|---|---|---|---|
| Checker | 1 | 377 | 0 | 52 | $0.0010 |
| Router | 3 | 1,229 | 0 | 133 | $0.0029 |
| Analyst | 9 | 12,574 | 3,379 | 913 | $0.0210 |

## Optimizations OFF

| Step | Input | Cached | Output | Calls | Cost | Seconds | Accuracy |
|---|---|---|---|---|---|---|---|
| Spread COST 10y | 2,558 | 2,432 | 511 | 1 (+0 cached) | $0.0056 | 4.4 | 190 passed / 0 fixed / 1 flagged; model audit: model flagged 1, Python 1, agreed 1, false alarms 0, missed 0 |
| Spread AAPL 5y (corrupted) | 1,903 | 1,400 | 440 | 2 (+0 cached) | $0.0052 | 8.5 | 102 passed / 3 fixed / 0 flagged; model audit: model flagged 1, Python 1, agreed 1, false alarms 0, missed 0 |
| Q1 margin (Harvey) | 25,073 | 3,379 | 638 | 6 (+0 cached) | $0.0339 | 17.1 | quotes verified 3, removed 0, figures 14/14 |
| Q2 supply chain (Harvey) | 12,830 | 0 | 476 | 4 (+0 cached) | $0.0208 | 7.1 | quotes verified 3, removed 0, figures 8/8 |
| Q1 margin, new session (Mike) | 17,293 | 9,091 | 735 | 6 (+0 cached) | $0.0187 | 11.4 | quotes verified 4, removed 0, figures 14/14 |
| **Total** | **59,657** | **16,302** | **2,800** | **19** | **$0.0842** | | Harvey/Mike facts identical: False |

| Agent | Calls | Input | Cached | Output | Cost |
|---|---|---|---|---|---|
| Checker | 3 | 4,461 | 3,832 | 951 | $0.0108 |
| Router | 3 | 1,227 | 0 | 136 | $0.0029 |
| Analyst | 13 | 53,969 | 12,470 | 1,713 | $0.0706 |

**Savings:** optimizations cut cost by 70% ($0.0842 → $0.0249) and input tokens by 76%.

Headlines (for a side-by-side quality read):

- [on] Q1 margin (Harvey): Apple’s gross margin rose from 44.1% in FY2023 to 46.9% in FY2025; management attributed the improvement to higher Services margins and sales, a different Servi
- [on] Q2 supply chain (Harvey): Management describes tariff-related disruption to supply chains and the availability of components as a potential risk, alongside reliance on outsourced manufac
- [on] Q1 margin, new session (Mike): Apple’s gross margin rose from 44.1% in FY2023 to 46.9% in FY2025; management attributed the improvement to higher Services margins and sales, a different Servi
- [off] Q1 margin (Harvey): Apple’s gross margin rose from 44.1% in FY2023 to 46.9% in FY2025, with faster Services margin expansion and higher Services sales contributing, while Products 
- [off] Q2 supply chain (Harvey): Management identifies dependence on outsourcing partners and suppliers, and warns that tariffs and trade measures could disrupt supply chains or affect componen
- [off] Q1 margin, new session (Mike): Apple’s gross margin rose from 44.1% in FY2023 to 46.9% in FY2025; the filings point to growth and a richer mix in Services and improving Services margin, along
