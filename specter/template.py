"""The standard banker template: every line item, its XBRL tags in priority order, and derivations.

Companies tag the same concept differently (and switch tags over the years), so each line item
tries its tags in order, period by period. Derived lines are plain arithmetic on other lines.

Fields
  key        stable id used everywhere (spread JSON, checks, Excel)
  label      what the banker sees
  kind       "line", "subtotal" (bold + top border), or "memo" (italic, used by the Checker)
  unit       "usd", "per_share", or "shares"
  period     "duration" (income/cash flow) or "instant" (balance sheet)
  tags       us-gaap concepts, highest priority first
  sum_of     fallback: add these components (each a tag list) when no single tag is filed
  derive     fallback (or only source): (formula text, function of other line values)
  sign       -1 to flip the filed sign (payments are filed positive but shown as outflows)
"""

INCOME = "income"
BALANCE = "balance"
CASHFLOW = "cashflow"
STATEMENTS = {INCOME: "Income Statement", BALANCE: "Balance Sheet", CASHFLOW: "Cash Flow Statement"}


def _item(key, label, tags=(), kind="line", unit="usd", period="duration", sum_of=None, derive=None, sign=1):
    return {"key": key, "label": label, "tags": list(tags), "kind": kind, "unit": unit, "period": period,
            "sum_of": sum_of, "derive": derive, "sign": sign}


TEMPLATE = {
    INCOME: [
        _item("revenue", "Revenue", [
            "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"], kind="subtotal"),
        _item("cogs", "Cost of Goods Sold", [
            "CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold",
            "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization", "CostOfServices"]),
        _item("gross_profit", "Gross Profit", ["GrossProfit"], kind="subtotal",
              derive=("Revenue − COGS", lambda v: v["revenue"] - v["cogs"])),
        _item("sga", "SG&A", ["SellingGeneralAndAdministrativeExpense"],
              sum_of=[["SellingAndMarketingExpense", "MarketingAndAdvertisingExpense"], ["GeneralAndAdministrativeExpense"]]),
        _item("rnd", "R&D", ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"]),
        _item("ebit", "Operating Income (EBIT)", ["OperatingIncomeLoss"], kind="subtotal"),
        _item("da", "D&A", [
            "DepreciationAmortizationAndOther", "DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
            "DepreciationAmortizationAndAccretionNet"],
              sum_of=[["Depreciation", "DepreciationNonproduction"], ["AmortizationOfIntangibleAssets"]]),
        _item("ebitda", "EBITDA", kind="subtotal", derive=("EBIT + D&A", lambda v: v["ebit"] + v["da"])),
        _item("interest_expense", "Interest Expense", [
            "InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"]),
        _item("pretax_income", "Pre-Tax Income", [
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
            kind="subtotal"),
        _item("taxes", "Income Taxes", ["IncomeTaxExpenseBenefit"]),
        _item("net_income", "Net Income", ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
              kind="subtotal"),
        _item("eps_diluted", "Diluted EPS", ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"], unit="per_share"),
        _item("shares_diluted", "Diluted Shares", ["WeightedAverageNumberOfDilutedSharesOutstanding"], unit="shares"),
    ],
    BALANCE: [
        _item("cash", "Cash & Equivalents", ["CashAndCashEquivalentsAtCarryingValue", "Cash"], period="instant"),
        _item("st_investments", "Short-Term Investments", [
            "MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
            period="instant"),
        _item("accounts_receivable", "Accounts Receivable", ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
              period="instant"),
        _item("inventory", "Inventory", ["InventoryNet"], period="instant"),
        _item("total_current_assets", "Total Current Assets", ["AssetsCurrent"], kind="subtotal", period="instant"),
        _item("ppe", "PP&E, Net", [
            "PropertyPlantAndEquipmentNet",
            "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
            period="instant"),
        _item("goodwill", "Goodwill", ["Goodwill"], period="instant"),
        _item("intangibles", "Intangibles, Net", ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
              period="instant"),
        _item("total_assets", "Total Assets", ["Assets"], kind="subtotal", period="instant"),
        _item("accounts_payable", "Accounts Payable", ["AccountsPayableCurrent"], period="instant"),
        _item("st_debt", "Short-Term Debt", ["DebtCurrent"], period="instant",
              sum_of=[["CommercialPaper", "ShortTermBorrowings"], ["LongTermDebtCurrent"]]),
        _item("total_current_liabilities", "Total Current Liabilities", ["LiabilitiesCurrent"], kind="subtotal",
              period="instant"),
        _item("lt_debt", "Long-Term Debt", ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
              period="instant"),
        _item("total_liabilities", "Total Liabilities", ["Liabilities"], kind="subtotal", period="instant",
              derive=("Total Liabilities & Equity − Total Equity",
                      lambda v: v["total_liabilities_and_equity"] - v["total_equity"])),
        _item("total_equity", "Total Equity", [
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"],
            kind="subtotal", period="instant"),
        _item("total_liabilities_and_equity", "Total Liabilities & Equity", ["LiabilitiesAndStockholdersEquity"],
              kind="subtotal", period="instant"),
    ],
    CASHFLOW: [
        _item("cfo", "Cash from Operations", [
            "NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
            kind="subtotal"),
        _item("capex", "Capital Expenditures", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
              sign=-1),
        _item("fcf", "Free Cash Flow", kind="subtotal", derive=("CFO − Capex", lambda v: v["cfo"] + v["capex"])),
        _item("cfi", "Cash from Investing", [
            "NetCashProvidedByUsedInInvestingActivities", "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"],
            kind="subtotal"),
        _item("cff", "Cash from Financing", [
            "NetCashProvidedByUsedInFinancingActivities", "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"],
            kind="subtotal"),
        _item("fx_effect", "FX Effect on Cash", [
            "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "EffectOfExchangeRateOnCashAndCashEquivalents",
            "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations"]),
        _item("net_change_cash", "Net Change in Cash", [
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
            "CashAndCashEquivalentsPeriodIncreaseDecrease",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect"],
            kind="subtotal"),
        _item("cash_end_cf", "Memo: Ending Cash (incl. restricted)", [
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalentsAtCarryingValue"],
            kind="memo", period="instant"),
    ],
}

ITEMS = {item["key"]: dict(item, statement=st) for st, items in TEMPLATE.items() for item in items}


def all_tags() -> set[str]:
    """Every us-gaap concept the template can use (also used to trim the bundled sample)."""
    tags = set()
    for item in ITEMS.values():
        tags.update(item["tags"])
        for group in item["sum_of"] or []:
            tags.update(group)
    return tags
