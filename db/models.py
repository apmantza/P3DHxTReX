from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func


Base = declarative_base()


# ---------------------------------------------------------------------------
# Reference / ingestion tables (existing, kept as-is)
# ---------------------------------------------------------------------------


class PeerData(Base):
    __tablename__ = "peer_data"

    id = Column(Integer, primary_key=True)
    bank_name = Column(String, nullable=False)
    bank_lei = Column(String, nullable=True)
    period = Column(Date, nullable=True)
    template = Column(String, nullable=False)
    item = Column(String, nullable=False)
    column = Column(String, nullable=False)
    amount = Column(Float, nullable=True)
    source = Column(String, nullable=False)
    labels_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_peer_data_bank_period", "bank_lei", "period"),
        Index("ix_peer_data_template", "template", "item", "column"),
    )


class CanonicalFact(Base):
    __tablename__ = "canonical_facts"

    id = Column(Integer, primary_key=True)
    bank_name = Column(String, nullable=False)
    bank_lei = Column(String, nullable=True)
    template = Column(String, nullable=False)
    row = Column(String, nullable=False)
    column = Column(String, nullable=False)
    reference_date = Column(Date, nullable=True)
    value = Column(Float, nullable=True)
    source = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CanonicalFactEnriched(Base):
    __tablename__ = "canonical_facts_enriched"

    id = Column(Integer, primary_key=True)
    bank_name = Column(String, nullable=False)
    bank_lei = Column(String, nullable=True)
    template = Column(String, nullable=False)
    row = Column(String, nullable=False)
    column = Column(String, nullable=False)
    reference_date = Column(Date, nullable=True)
    value = Column(Float, nullable=True)
    source = Column(String, nullable=False)
    labels_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class BaseYearSnapshot(Base):
    __tablename__ = "base_year_snapshots"

    id = Column(Integer, primary_key=True)
    snapshot_name = Column(String, nullable=False)
    bank_name = Column(String, nullable=False)
    bank_lei = Column(String, nullable=True)
    period = Column(Date, nullable=True)
    template = Column(String, nullable=False)
    item = Column(String, nullable=False)
    column = Column(String, nullable=False)
    amount = Column(Float, nullable=True)
    source = Column(String, nullable=False)
    labels_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class P3DHDataDictionary(Base):
    """
    EBA Pillar 3 Data Hub annotated table layout — per-cell metadata.
    Used as a join to enrich PeerData / CanonicalFact rows with unit,
    section description, and DPM semantic properties.
    """
    __tablename__ = "p3dh_data_dictionary"

    id = Column(Integer, primary_key=True)
    template_code = Column(String, nullable=False)   # e.g. K_61.00
    template_name = Column(String, nullable=False)
    module_name = Column(String, nullable=False)     # e.g. Common disclosures
    section = Column(String, nullable=True)          # e.g. Available own funds (amounts)
    row_code = Column(String, nullable=False)        # 4-digit e.g. 0010
    row_name = Column(String, nullable=False)
    col_code = Column(String, nullable=False)        # 4-digit e.g. 0010
    col_name = Column(String, nullable=False)
    unit = Column(String, nullable=False)            # EUR | PCT | TEXT
    dpm_point_id = Column(String, nullable=True)
    main_property = Column(String, nullable=True)    # DPM concept e.g. (qABJ) Amount...
    dimensions = Column(Text, nullable=True)         # pipe-separated DPM dimensions

    __table_args__ = (
        UniqueConstraint("template_code", "row_code", "col_code", name="uq_p3dh_dict_cell"),
        Index("ix_p3dh_dict_lookup", "template_code", "row_code", "col_code"),
    )


# ---------------------------------------------------------------------------
# Core domain: Bank
# ---------------------------------------------------------------------------


class Bank(Base):
    """
    Master record for each institution.
    Systemic importance and BICRA group are pre-populated from public sources.
    """
    __tablename__ = "banks"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    lei = Column(String, nullable=True, unique=True)
    country = Column(String(2), nullable=False)          # ISO-3166-2
    approach = Column(String, nullable=False)            # SA | IRB
    tier = Column(String, nullable=True)                 # Large | Other
    peer_group = Column(String, nullable=True)
    systemic_importance = Column(String, nullable=True)  # GSIB | DSIB | OTHER
    bicra_group = Column(String, nullable=True)          # S&P BICRA country group
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    plans = relationship("Plan", back_populates="bank", cascade="all, delete-orphan")
    market_data = relationship("MarketData", back_populates="bank", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Business Plan
# ---------------------------------------------------------------------------


class Plan(Base):
    """
    One per bank per planning cycle. Stores all assumption inputs as JSON
    blobs (validated by Pydantic before persistence). Engine reads this
    and produces ProjectedFinancials.
    """
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    bank_id = Column(Integer, ForeignKey("banks.id"), nullable=False)
    name = Column(String, nullable=False)
    horizon_years = Column(Integer, nullable=False, default=5)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # Assumption blobs — each validated by a Pydantic schema before save
    portfolio_allocations = Column(JSON, nullable=True)   # list[PortfolioAllocation]
    funding_strategy = Column(JSON, nullable=True)        # list[FundingStrategy]
    ftp_assumptions = Column(JSON, nullable=True)         # list[FTPAssumptions]
    capital_actions = Column(JSON, nullable=True)         # list[CapitalAction]
    dividend_policy = Column(JSON, nullable=True)         # DividendPolicy
    rate_environment = Column(JSON, nullable=True)        # RateEnvironment
    repricing_gap = Column(JSON, nullable=True)           # list[RepricingGapBucket]
    nmd_profiles = Column(JSON, nullable=True)            # list[NMDProfile]
    hedging_instruments = Column(JSON, nullable=True)     # list[HedgingInstrument]
    cet1_deductions = Column(JSON, nullable=True)         # CET1Deductions
    ifrs9_transitional = Column(JSON, nullable=True)      # IFRS9TransitionalRelief
    recovery_options = Column(JSON, nullable=True)        # list[RecoveryOption]

    bank = relationship("Bank", back_populates="plans")
    projected_financials = relationship(
        "ProjectedFinancials", back_populates="plan", cascade="all, delete-orphan"
    )
    stress_runs = relationship("StressRun", back_populates="plan", cascade="all, delete-orphan")
    rating_scores = relationship("RatingScore", back_populates="plan", cascade="all, delete-orphan")
    optimization_runs = relationship(
        "OptimizationRun", back_populates="plan", cascade="all, delete-orphan"
    )
    hedge_counterfactuals = relationship(
        "HedgeCounterfactualRun", back_populates="plan", cascade="all, delete-orphan"
    )
    hedge_optimisations = relationship(
        "HedgeOptimisationRun", back_populates="plan", cascade="all, delete-orphan"
    )
    report_runs = relationship("ReportRun", back_populates="plan", cascade="all, delete-orphan")
    icaap_drafts = relationship(
        "IcaapIlaapDraft", back_populates="plan", cascade="all, delete-orphan"
    )
    benchmark_runs = relationship("BenchmarkRun", backref="plan", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_plans_bank", "bank_id"),)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


class Scenario(Base):
    """
    Macro stress scenario. EBA presets or custom. Used by StressRun and
    referenced by ProjectedFinancials (null = base/management case).

    scenario_type: EBA_BASELINE | EBA_ADVERSE | EBA_SEVERELY_ADVERSE | CUSTOM | REVERSE
    """
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    scenario_type = Column(String, nullable=False)
    macro_assumptions = Column(JSON, nullable=True)        # MacroAssumptions
    transmission_overrides = Column(JSON, nullable=True)   # TransmissionOverrides
    funding_curve_assumptions = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    stress_runs = relationship("StressRun", back_populates="scenario")
    rating_scores = relationship("RatingScore", back_populates="scenario")


# ---------------------------------------------------------------------------
# Projected Financials (calculation engine output)
# ---------------------------------------------------------------------------


class ProjectedFinancials(Base):
    """
    Output of run_projection() for one plan × period × scenario.
    Hot-path metrics are scalar columns for fast queries/charting.
    All detail is in JSON blobs validated by Pydantic.
    """
    __tablename__ = "projected_financials"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)  # null = base
    period = Column(Date, nullable=False)   # quarter-end date
    is_stressed = Column(Boolean, nullable=False, default=False)

    # Hot-path scalar metrics for fast dashboard queries
    cet1_ratio = Column(Float, nullable=True)
    t1_ratio = Column(Float, nullable=True)
    total_capital_ratio = Column(Float, nullable=True)
    rwa = Column(Float, nullable=True)
    nii = Column(Float, nullable=True)
    nim = Column(Float, nullable=True)
    roe = Column(Float, nullable=True)
    rote = Column(Float, nullable=True)
    npl_ratio = Column(Float, nullable=True)
    cost_of_risk = Column(Float, nullable=True)
    lcr = Column(Float, nullable=True)
    nsfr = Column(Float, nullable=True)
    leverage_ratio = Column(Float, nullable=True)
    cir = Column(Float, nullable=True)       # cost-to-income
    # New hot-path scalars
    ldr = Column(Float, nullable=True)                # loan-to-deposit ratio
    nir = Column(Float, nullable=True)                # non-interest income ratio
    texas_ratio = Column(Float, nullable=True)
    breakeven_cor_bps = Column(Float, nullable=True)
    capital_gen_rate_bps = Column(Float, nullable=True)
    non_interest_income_pct = Column(Float, nullable=True)
    stage2_coverage = Column(Float, nullable=True)

    # Detail blobs (Pydantic-validated before persistence)
    pnl_detail = Column(JSON, nullable=True)
    balance_sheet_detail = Column(JSON, nullable=True)
    capital_detail = Column(JSON, nullable=True)
    asset_quality_detail = Column(JSON, nullable=True)
    irrbb_metrics = Column(JSON, nullable=True)
    liquidity_detail = Column(JSON, nullable=True)
    ecl_detail = Column(JSON, nullable=True)
    bridges = Column(JSON, nullable=True)        # cet1, nii, roe, rwa bridges
    market_metrics = Column(JSON, nullable=True) # eps, dps, pe, ptbv, tsr, ...
    segment_raroc = Column(JSON, nullable=True)
    liquidity_survival = Column(JSON, nullable=True)
    vbm_metrics = Column(JSON, nullable=True)    # economic_profit, implied_coe
    # New JSON blobs
    peer_percentiles = Column(JSON, nullable=True)
    equity_bridge = Column(JSON, nullable=True)
    oci_detail = Column(JSON, nullable=True)
    dta_detail = Column(JSON, nullable=True)
    nii_sensitivity = Column(JSON, nullable=True)
    loan_book_bridge = Column(JSON, nullable=True)

    convergence_iterations = Column(Integer, nullable=True)
    warnings = Column(JSON, nullable=True)       # list[str]
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    plan = relationship("Plan", back_populates="projected_financials")
    scenario = relationship("Scenario")

    __table_args__ = (
        Index("ix_pf_plan_period", "plan_id", "period"),
        Index("ix_pf_plan_scenario", "plan_id", "scenario_id"),
    )


# ---------------------------------------------------------------------------
# Stress Run
# ---------------------------------------------------------------------------


class StressRun(Base):
    """
    Container linking a plan + scenario to a set of stressed ProjectedFinancials.
    Also stores uncertainty bands computed via Monte Carlo / parameter uncertainty.
    """
    __tablename__ = "stress_runs"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    uncertainty_bands = Column(JSON, nullable=True)  # p10/p50/p90 per key metric
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    plan = relationship("Plan", back_populates="stress_runs")
    scenario = relationship("Scenario", back_populates="stress_runs")

    __table_args__ = (
        UniqueConstraint("plan_id", "scenario_id", name="uq_stress_run_plan_scenario"),
    )


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------


class RatingScore(Base):
    """
    Simplified rating scorecard output.
    methodology: MOODYS | SP
    scenario_id null = base case rating.
    """
    __tablename__ = "rating_scores"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    methodology = Column(String, nullable=False)    # MOODYS | SP
    factor_scores = Column(JSON, nullable=True)     # 8 factor scores
    composite_notch = Column(String, nullable=True)
    direction = Column(String, nullable=True)       # STABLE | POSITIVE | NEGATIVE
    support_uplift = Column(Integer, nullable=True, default=0)
    disclaimer_acknowledged = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    plan = relationship("Plan", back_populates="rating_scores")
    scenario = relationship("Scenario", back_populates="rating_scores")


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------


class MarketData(Base):
    """
    Daily equity market data fetched from yfinance. One row per bank × date.
    """
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True)
    bank_id = Column(Integer, ForeignKey("banks.id"), nullable=False)
    ticker = Column(String, nullable=False)
    source = Column(String, nullable=False, default="YFINANCE")
    currency = Column(String(3), nullable=True)
    exchange = Column(String, nullable=True)
    date = Column(Date, nullable=False)
    close_price = Column(Float, nullable=True)
    shares_outstanding = Column(Float, nullable=True)
    dividend_per_share = Column(Float, nullable=True)

    bank = relationship("Bank", back_populates="market_data")

    __table_args__ = (
        UniqueConstraint("bank_id", "date", name="uq_market_data_bank_date"),
        Index("ix_market_data_bank_date", "bank_id", "date"),
    )


# ---------------------------------------------------------------------------
# Historical Rate & Macro Data
# ---------------------------------------------------------------------------


class HistoricalRateCurve(Base):
    """
    ECB/central bank rate curves cached locally. Source: ECB SDW API.
    country null = EU-wide / ECB policy rate.
    """
    __tablename__ = "historical_rate_curves"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    series = Column(String, nullable=False)    # e.g. EURIBOR_3M, OIS_1Y, SWAP_5Y
    tenor = Column(String, nullable=True)      # e.g. 3M, 1Y, 5Y
    rate = Column(Float, nullable=True)
    country = Column(String(2), nullable=True)  # null = EU-wide
    source = Column(String, nullable=False, default="ECB_SDW")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", "series", "country", name="uq_rate_curve"),
        Index("ix_rate_curve_series_date", "series", "date"),
    )


class HistoricalMacroSeries(Base):
    """
    Macro time series from ECB/Eurostat. country null = Eurozone aggregate.
    series: GDP_YOY | UNEMPLOYMENT | HPI_YOY | CPI | ...
    """
    __tablename__ = "historical_macro_series"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    country = Column(String(2), nullable=True)  # null = Eurozone
    series = Column(String, nullable=False)
    value = Column(Float, nullable=True)
    source = Column(String, nullable=False)     # ECB_SDW | EUROSTAT
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", "series", "country", name="uq_macro_series"),
        Index("ix_macro_series_series_date", "series", "date"),
    )


class MacroElasticity(Base):
    """
    Fitted macro transmission coefficients.
    Maps a macro variable shift (e.g. GDP -2pp) to a credit metric response
    (e.g. NPL ratio +120bps). Fitted per country; null country = EU baseline.
    """
    __tablename__ = "macro_elasticities"

    id = Column(Integer, primary_key=True)
    series_pair = Column(String, nullable=False)   # e.g. GDP_YOY→NPL_RATIO
    country = Column(String(2), nullable=True)
    coefficient = Column(Float, nullable=True)
    std_error = Column(Float, nullable=True)
    r_squared = Column(Float, nullable=True)
    adj_r_squared = Column(Float, nullable=True)
    n_obs = Column(Integer, nullable=True)
    ci_lower = Column(Float, nullable=True)
    ci_upper = Column(Float, nullable=True)
    window_start = Column(Date, nullable=True)
    window_end = Column(Date, nullable=True)
    covid_excluded = Column(Boolean, nullable=False, default=False)
    regime_dummy = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("series_pair", "country", name="uq_elasticity"),
    )


# ---------------------------------------------------------------------------
# Hedge Analytics
# ---------------------------------------------------------------------------


class HedgeCounterfactualRun(Base):
    """
    Historical counterfactual: what would NII/EVE have been with a given
    hedge portfolio applied to the historical rate path?
    """
    __tablename__ = "hedge_counterfactual_runs"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    instruments = Column(JSON, nullable=True)       # list[HedgingInstrument]
    window_start = Column(Date, nullable=True)
    window_end = Column(Date, nullable=True)
    quarterly_results = Column(JSON, nullable=True) # per-quarter NII/EVE actual vs counterfactual
    known_limitation_note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    plan = relationship("Plan", back_populates="hedge_counterfactuals")


class HedgeOptimisationRun(Base):
    """
    Efficient frontier of hedge strategies optimised for NII-at-risk vs EVE variance.
    """
    __tablename__ = "hedge_optimisation_runs"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    constraints = Column(JSON, nullable=True)       # max_notional, max_cost
    historical_window = Column(Integer, nullable=True)  # months
    efficient_frontier = Column(JSON, nullable=True)    # list[EfficientFrontierPoint]
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    plan = relationship("Plan", back_populates="hedge_optimisations")


# ---------------------------------------------------------------------------
# Portfolio Optimisation
# ---------------------------------------------------------------------------


class OptimizationRun(Base):
    """
    Portfolio steering optimisation: given objective + constraints, find
    the Pareto-optimal set of allocation strategies.
    """
    __tablename__ = "optimization_runs"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    objective = Column(String, nullable=False)     # e.g. MAX_ROE | MAX_RAROC | MIN_CAPITAL
    constraints = Column(JSON, nullable=True)      # list[constraint dicts]
    levers = Column(JSON, nullable=True)           # list[lever names]
    efficient_frontier = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    plan = relationship("Plan", back_populates="optimization_runs")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class ReportRun(Base):
    """Tracks generated PDF/Excel reports for audit and re-download."""
    __tablename__ = "report_runs"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    scenarios = Column(JSON, nullable=True)          # list of scenario IDs included
    format = Column(String, nullable=False)          # PDF | EXCEL
    sections_included = Column(JSON, nullable=True)
    file_path = Column(String, nullable=True)
    session_id = Column(String, nullable=True)
    generated_at = Column(DateTime, nullable=False, server_default=func.now())

    plan = relationship("Plan", back_populates="report_runs")


class IcaapIlaapDraft(Base):
    """
    Auto-generated ICAAP/ILAAP narrative pack.
    Stores both structured quantitative annexes and narrative sections as JSON.
    """
    __tablename__ = "icaap_ilaap_drafts"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    horizon_years = Column(Integer, nullable=False, default=3)
    base_scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    adverse_scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    internal_capital_buffer = Column(Float, nullable=True)
    internal_liquidity_buffer = Column(Float, nullable=True)
    survival_horizon_days = Column(Integer, nullable=True)
    liquidity_reverse_stress_result = Column(JSON, nullable=True)
    capital_reverse_stress_result = Column(JSON, nullable=True)
    management_actions_summary = Column(Text, nullable=True)
    narrative_sections = Column(JSON, nullable=True)
    quantitative_annexes = Column(JSON, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="DRAFT")  # DRAFT | APPROVED
    file_path = Column(String, nullable=True)
    generated_at = Column(DateTime, nullable=False, server_default=func.now())

    plan = relationship("Plan", back_populates="icaap_drafts")


# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------


class BenchmarkRun(Base):
    """Peer benchmarking results for a plan."""
    __tablename__ = "benchmark_runs"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    peer_group_leis = Column(JSON, nullable=True)    # list[str]
    peer_count = Column(Integer, nullable=True)
    base_year_period = Column(Date, nullable=True)
    results = Column(JSON, nullable=True)            # BenchmarkReport as dict
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_benchmark_plan", "plan_id"),)


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """
    Append-only log of every Plan modification.
    Required for ECB/SSM ICAAP regulatory traceability.
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, server_default=func.now())
    entity_type = Column(String, nullable=False)   # Plan | Scenario | ...
    entity_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)        # CREATE | UPDATE | DELETE
    field_changed = Column(String, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    session_id = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_timestamp", "timestamp"),
    )
