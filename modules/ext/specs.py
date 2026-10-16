"""The countries and the indicators of the external statistics.

A spec is one request to a source for all countries. In an ECB key, {A} stands for the list of countries (AT+BE+...).
Banking indicators of the ECB (CBD2) are for domestic banks: banks that have their head office in the country. A foreign bank in the country is not in them.
"""

from __future__ import annotations

from dataclasses import dataclass

# iso2, name, in the euro area on 1 January 2026
COUNTRIES = [
    ("AT", "Austria", 1), ("BE", "Belgium", 1), ("BG", "Bulgaria", 1), ("HR", "Croatia", 1), ("CY", "Cyprus", 1), ("CZ", "Czechia", 0), ("DK", "Denmark", 0),
    ("EE", "Estonia", 1), ("FI", "Finland", 1), ("FR", "France", 1), ("DE", "Germany", 1), ("GR", "Greece", 1), ("HU", "Hungary", 0), ("IE", "Ireland", 1),
    ("IT", "Italy", 1), ("LV", "Latvia", 1), ("LT", "Lithuania", 1), ("LU", "Luxembourg", 1), ("MT", "Malta", 1), ("NL", "Netherlands", 1), ("PL", "Poland", 0),
    ("PT", "Portugal", 1), ("RO", "Romania", 0), ("SK", "Slovakia", 1), ("SI", "Slovenia", 1), ("ES", "Spain", 1), ("SE", "Sweden", 0),
]
EURO_AREA = "U2"  # the aggregate of the euro area: code of the ECB, and the code that this database uses
# Geographic groups for peer aggregates. A group is a list of countries and can be changed in the table ext_geo_group. The membership is today's, also for the history.
_EA = [c[0] for c in COUNTRIES if c[2]]
GEO_GROUPS = {
    "Euro area (members)": _EA,
    "EU27": [c[0] for c in COUNTRIES],
    "Non-euro EU": [c[0] for c in COUNTRIES if not c[2]],
    "Benelux": ["BE", "NL", "LU"],
    "DACH": ["DE", "AT"],
    "Nordics": ["DK", "SE", "FI"],
    "Southern Europe": ["ES", "IT", "PT", "GR", "CY", "MT"],
    "Baltics": ["EE", "LV", "LT"],
    "Central and Eastern Europe": ["PL", "CZ", "SK", "HU", "SI", "HR", "RO", "BG"],
    "Core euro area": ["DE", "FR", "NL", "AT", "BE", "LU", "FI"],
    "Periphery": ["ES", "IT", "PT", "GR", "IE", "CY"],
}

ECB_AREAS = [c[0] for c in COUNTRIES] + [EURO_AREA]
EUROSTAT_CODE = {"GR": "EL"}  # Eurostat writes EL for Greece; its euro area aggregate has the code EA plus the number of members (EA21)


@dataclass(frozen=True)
class Spec:
    indicator: str
    source: str            # ecb or eurostat
    dataset: str           # the dataflow of the ECB, or the dataset of Eurostat
    key: str               # ECB: key with {A}. Eurostat: the filters of the query
    freq: str              # A, Q, M, or D
    unit: str
    group: str
    desc: str
    indicator_col: str = ""   # a column of the answer that gives a series its own indicator (indicator_col value is added to the name)
    euro_area_only: bool = False


def ecb(indicator, dataset, key, freq, unit, group, desc, **kw) -> Spec:
    return Spec(indicator, "ecb", dataset, key, freq, unit, group, desc, **kw)


def es(indicator, dataset, params, freq, unit, group, desc, **kw) -> Spec:
    return Spec(indicator, "eurostat", dataset, params, freq, unit, group, desc, **kw)


CBD = "A.{A}.W0.11._Z._Z.A.%s.%s._Z._Z._Z._Z._Z._Z.%s"  # consolidated banking data, domestic banks: framework, item, unit
CBD_AMOUNT = "A.{A}.W0.11._Z._Z.A.%s.%s._X.ALL.%s._Z.%s._T.EUR"  # framework, item, type, valuation

SPECS: list[Spec] = [
    # ---- ECB, interest rates of banks (MIR), monthly, % per year
    ecb("mir_cob_nfc", "MIR", "M.{A}.B.A2I.AM.R.A.2240.EUR.N", "M", "pct", "rates", "Cost of borrowing, loans to non-financial corporations, new business"),
    ecb("mir_cob_hp", "MIR", "M.{A}.B.A2C.AM.R.A.2250.EUR.N", "M", "pct", "rates", "Cost of borrowing, loans to households for house purchase, new business"),
    ecb("mir_rate_cons", "MIR", "M.{A}.B.A2B.A.R.A.2250.EUR.N", "M", "pct", "rates", "Rate on loans to households for consumption, new business"),
    ecb("mir_rate_nfc_out", "MIR", "M.{A}.B.A20.A.R.A.2240.EUR.O", "M", "pct", "rates", "Rate on loans to non-financial corporations, outstanding amounts (the book)"),
    ecb("mir_rate_hh_out", "MIR", "M.{A}.B.A20.A.R.A.2250.EUR.O", "M", "pct", "rates", "Rate on loans to households, outstanding amounts (the book)"),
    ecb("mir_dep_hh_term", "MIR", "M.{A}.B.L22.A.R.A.2250.EUR.N", "M", "pct", "rates", "Rate on deposits of households with an agreed maturity, new business"),
    ecb("mir_dep_nfc_term", "MIR", "M.{A}.B.L22.A.R.A.2240.EUR.N", "M", "pct", "rates", "Rate on deposits of corporations with an agreed maturity, new business"),
    ecb("mir_dep_hh_on", "MIR", "M.{A}.B.L21.A.R.A.2250.EUR.N", "M", "pct", "rates", "Rate on overnight deposits of households"),
    ecb("newvol_hp", "MIR", "M.{A}.B.A2C.A.B.A.2250.EUR.N", "M", "eur_m", "volumes", "New loans to households for house purchase (volume of the month)"),
    # ---- ECB, balance sheet of the banks (BSI), monthly, stocks in EUR million
    ecb("bsi_loans_nfc", "BSI", "M.{A}.N.A.A20.A.1.U2.2240.Z01.E", "M", "eur_m", "volumes", "Loans to non-financial corporations, stock"),
    ecb("bsi_loans_hh", "BSI", "M.{A}.N.A.A20.A.1.U2.2250.Z01.E", "M", "eur_m", "volumes", "Loans to households, stock"),
    ecb("bsi_loans_hp", "BSI", "M.{A}.N.A.A22.A.1.U2.2250.Z01.E", "M", "eur_m", "volumes", "Lending for house purchase, stock"),
    ecb("bsi_loans_cons", "BSI", "M.{A}.N.A.A21.A.1.U2.2250.Z01.E", "M", "eur_m", "volumes", "Credit for consumption, stock"),
    ecb("bsi_dep_hh", "BSI", "M.{A}.N.A.L20.A.1.U2.2250.Z01.E", "M", "eur_m", "volumes", "Deposits of households, stock"),
    ecb("bsi_dep_nfc", "BSI", "M.{A}.N.A.L20.A.1.U2.2240.Z01.E", "M", "eur_m", "volumes", "Deposits of non-financial corporations, stock"),
    ecb("bsi_dep_hh_on", "BSI", "M.{A}.N.A.L21.A.1.U2.2250.Z01.E", "M", "eur_m", "volumes", "Overnight deposits of households, stock"),
    ecb("bsi_dep_hh_term", "BSI", "M.{A}.N.A.L22.A.1.U2.2250.Z01.E", "M", "eur_m", "volumes", "Deposits of households with an agreed maturity, stock"),
    # ---- ECB, annual growth rates of the same stocks, as the ECB computes them (index of notional stocks: corrected for reclassifications and exchange rates)
    ecb("growth_loans_nfc", "BSI", "M.{A}.N.A.A20.A.I.U2.2240.Z01.A", "M", "pct", "growth", "Loans to non-financial corporations, annual growth rate"),
    ecb("growth_loans_hh", "BSI", "M.{A}.N.A.A20.A.I.U2.2250.Z01.A", "M", "pct", "growth", "Loans to households, annual growth rate"),
    ecb("growth_loans_hp", "BSI", "M.{A}.N.A.A22.A.I.U2.2250.Z01.A", "M", "pct", "growth", "Lending for house purchase, annual growth rate"),
    ecb("growth_dep_hh", "BSI", "M.{A}.N.A.L20.A.I.U2.2250.Z01.A", "M", "pct", "growth", "Deposits of households, annual growth rate"),
    ecb("growth_dep_nfc", "BSI", "M.{A}.N.A.L20.A.I.U2.2240.Z01.A", "M", "pct", "growth", "Deposits of non-financial corporations, annual growth rate"),
    # ---- ECB, bank lending survey (BLS), quarterly, net percentage of banks (positive: tightening, or rising demand)
    ecb("bls_std_nfc", "BLS", "Q.{A}.ALL.O.E.Z.B3.ST.S.FNET", "Q", "net_pct", "survey", "Credit standards for loans to enterprises, last 3 months (positive: tighter)"),
    ecb("bls_dem_nfc", "BLS", "Q.{A}.ALL.O.E.Z.B3.ZZ.D.FNET", "Q", "net_pct", "survey", "Demand for loans from enterprises, last 3 months (positive: higher)"),
    ecb("bls_std_hp", "BLS", "Q.{A}.ALL.Z.H.H.B3.ST.S.FNET", "Q", "net_pct", "survey", "Credit standards for house purchase loans, last 3 months (positive: tighter)"),
    ecb("bls_dem_hp", "BLS", "Q.{A}.ALL.Z.H.H.B3.ZZ.D.FNET", "Q", "net_pct", "survey", "Demand for house purchase loans, last 3 months (positive: higher)"),
    ecb("bls_std_cons", "BLS", "Q.{A}.ALL.Z.H.C.B3.ST.S.FNET", "Q", "net_pct", "survey", "Credit standards for consumer credit, last 3 months (positive: tighter)"),
    ecb("bls_dem_cons", "BLS", "Q.{A}.ALL.Z.H.C.B3.ZZ.D.FNET", "Q", "net_pct", "survey", "Demand for consumer credit, last 3 months (positive: higher)"),
    # ---- ECB, consolidated banking data of domestic banks (CBD2), annual
    ecb("cbd_roe", "CBD2", CBD % ("A", "I2003", "PC"), "A", "pct", "profitability", "Return on equity of domestic banks"),
    ecb("cbd_cir", "CBD2", CBD % ("A", "I2100", "PC"), "A", "pct", "profitability", "Cost-to-income ratio of domestic banks (the ECB shows costs with a minus sign)"),
    ecb("cbd_income_assets", "CBD2", CBD % ("A", "I2400", "PC"), "A", "pct", "profitability", "Total operating income to assets"),
    ecb("cbd_nii_assets", "CBD2", CBD % ("A", "I2410", "PC"), "A", "pct", "profitability", "Net interest income to assets"),
    ecb("cbd_fee_assets", "CBD2", CBD % ("A", "I2430", "PC"), "A", "pct", "profitability", "Net fee and commission income to assets"),
    ecb("cbd_nii_share", "CBD2", CBD % ("A", "I2510", "PC"), "A", "pct", "profitability", "Net interest income to total operating income"),
    ecb("cbd_fee_share", "CBD2", CBD % ("A", "I2530", "PC"), "A", "pct", "profitability", "Net fee and commission income to total operating income"),
    ecb("cbd_income", "CBD2", CBD_AMOUNT % ("A", "P2100", "CP", "T"), "A", "eur_th", "profitability", "Total operating income, net (EUR thousand)"),
    ecb("cbd_nii", "CBD2", CBD_AMOUNT % ("A", "P2110", "CP", "T"), "A", "eur_th", "profitability", "Net interest income (EUR thousand)"),
    ecb("cbd_fee", "CBD2", CBD_AMOUNT % ("A", "P2130", "CP", "T"), "A", "eur_th", "profitability", "Net fee and commission income (EUR thousand)"),
    ecb("cbd_impairment", "CBD2", CBD_AMOUNT % ("F", "P2410", "CP", "T"), "A", "eur_th", "profitability", "Impairment of financial assets not at fair value (EUR thousand)"),
    ecb("cbd_profit", "CBD2", CBD_AMOUNT % ("A", "P0000", "CP", "T"), "A", "eur_th", "profitability", "Profit or loss for the year (EUR thousand)"),
    ecb("cbd_assets", "CBD2", CBD_AMOUNT % ("A", "A0000", "CA", "LE"), "A", "eur_th", "balance sheet", "Assets of domestic banks (EUR thousand)"),
    ecb("cbd_equity_assets", "CBD2", CBD % ("F", "I3300", "PC"), "A", "pct", "capital", "Total equity to assets"),
    ecb("cbd_npl", "CBD2", CBD % ("F", "I3632", "PC"), "A", "pct", "asset quality", "Gross non-performing loans to gross loans"),
    ecb("cbd_cet1", "CBD2", CBD % ("A", "I4008", "PC"), "A", "pct", "capital", "Common equity Tier 1 ratio of domestic banks"),
    # ---- ECB, supervisory banking statistics of all supervised banks (SUP), quarterly
    ecb("sup_roe", "SUP", "Q.{A}.W0._Z.I2003._T.ALL._Z._Z._Z.PCT.C", "Q", "pct", "profitability", "Return on equity, all supervised banks"),
    ecb("sup_roa", "SUP", "Q.{A}.W0._Z.I2004._T.ALL._Z._Z._Z.PCT.C", "Q", "pct", "profitability", "Return on assets, all supervised banks"),
    ecb("sup_cir", "SUP", "Q.{A}.W0._Z.I2100._T.ALL._Z._Z._Z.PCT.C", "Q", "pct", "profitability", "Cost-to-income ratio, all supervised banks"),
    ecb("sup_nim", "SUP", "Q.{A}.W0._Z.I2120._T.ALL._Z._Z._Z.PCT.C", "Q", "pct", "profitability", "Net interest margin, all supervised banks"),
    ecb("sup_nii_share", "SUP", "Q.{A}.W0._Z.I2513._T.ALL._Z._Z._Z.PCT.C", "Q", "pct", "profitability", "Net interest income to total operating income, all supervised banks"),
    ecb("sup_lcr", "SUP", "Q.{A}.W0._Z.I3017._T.ALL._Z._Z._Z.PCT.C", "Q", "pct", "liquidity", "Liquidity coverage ratio, all supervised banks"),
    ecb("sup_npl", "SUP", "Q.{A}.W0._Z.I7005._T.ALL._Z._Z._Z.PCT.C", "Q", "pct", "asset quality", "Non-performing loans ratio (without cash balances), all supervised banks"),
    # ---- ECB, structure of the banking sector (SSI): every indicator of the dataflow, one indicator name for each (ssi_H10, ssi_N30, ...)
    ecb("ssi", "SSI", "A.{A}.122C.....", "A", "various", "structure", "Structural indicators of the banking sector (number of banks, employees, concentration)", indicator_col="SSI_INDICATOR"),
    # ---- ECB, market rates (euro area only)
    ecb("estr_daily", "EST", "B.EU000A2X2A25.WT", "D", "pct", "market", "Euro short-term rate (euro area)", euro_area_only=True),
    ecb("euribor_3m", "FM", "M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA", "M", "pct", "market", "3-month Euribor, average of the month (euro area)", euro_area_only=True),
    ecb("ecb_dfr", "FM", "B.U2.EUR.4F.KR.DFR.LEV", "D", "pct", "market", "Deposit facility rate of the ECB, day of each change (euro area)", euro_area_only=True),
    # ---- Eurostat, economy of the country
    es("es_hpi_yoy", "prc_hpi_q", "unit=RCH_A&purchase=TOTAL", "Q", "pct", "economy", "House price index, change on the same quarter of the year before"),
    es("es_gdp_yoy", "namq_10_gdp", "unit=CLV_PCH_SM&na_item=B1GQ&s_adj=SCA", "Q", "pct", "economy", "Real GDP, change on the same quarter of the year before"),
    es("es_unemployment", "une_rt_m", "s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT", "M", "pct", "economy", "Unemployment rate, seasonally adjusted"),
    es("es_inflation", "prc_hicp_minr", "unit=RCH_A&coicop18=TOTAL", "M", "pct", "economy", "Inflation (HICP), annual rate of change"),
    es("es_gov_debt", "gov_10q_ggdebt", "sector=S13&na_item=GD&unit=PC_GDP", "Q", "pct", "economy", "General government gross debt, % of GDP"),
    # ---- Eurostat, market rates of the countries (the local reference rate of the countries outside the euro area, and the government yield of every country)
    es("es_mm_3m", "irt_st_m", "int_rt=IRT_M3", "M", "pct", "market", "3-month money market rate (euro area members: no series; use euribor_3m)"),
    es("es_lt_yield", "irt_lt_mcby_m", "int_rt=MCBY", "M", "pct", "market", "10-year government bond yield (convergence criterion)"),
    # ---- Eurostat, households and companies
    es("es_hh_debt", "tipspd22", "unit=PC_GDP", "A", "pct", "economy", "Household debt, consolidated, % of GDP"),
    es("es_private_debt", "tipspd20", "unit=PC_GDP", "A", "pct", "economy", "Private sector debt (companies and households), consolidated, % of GDP"),
    es("es_consumer_conf", "ei_bsco_m", "indic=BS-CSMCI&s_adj=SA&unit=BAL", "M", "balance", "economy", "Consumer confidence indicator, seasonally adjusted (balance)"),
    es("es_hh_deposits", "nasq_10_f_bs", "sector=S14_S15&finpos=ASS&na_item=F2&unit=MIO_EUR", "Q", "eur_m", "economy", "Households: currency and deposits (assets), EUR million"),
    es("es_hh_loans", "nasq_10_f_bs", "sector=S14_S15&finpos=LIAB&na_item=F4&unit=MIO_EUR", "Q", "eur_m", "economy", "Households: loans (liabilities), EUR million"),
    es("es_nfc_deposits", "nasq_10_f_bs", "sector=S11&finpos=ASS&na_item=F2&unit=MIO_EUR", "Q", "eur_m", "economy", "Non-financial corporations: currency and deposits (assets), EUR million"),
    es("es_nfc_loans", "nasq_10_f_bs", "sector=S11&finpos=LIAB&na_item=F4&unit=MIO_EUR", "Q", "eur_m", "economy", "Non-financial corporations: loans (liabilities), EUR million"),
]
BY_INDICATOR = {s.indicator: s for s in SPECS}
