"""Comprehensive Policy Catalog: Health Insurance, Life Insurance, Government Schemes, and Banking Policies."""

from typing import Dict, Any, List, Optional


POLICY_CATALOG: Dict[str, Dict[str, Any]] = {
    # 1. HEALTH INSURANCE POLICIES
    "POL-HEALTH-STUDENT": {
        "id": "POL-HEALTH-STUDENT",
        "title": "Nova Care Student Health Shield",
        "category": "HEALTH",
        "target_audience": "College Students & Young Adults (18-25)",
        "sum_insured": "₹3,00,000 - ₹5,00,000",
        "annual_premium": "Starting at ₹1,850/year (~₹155/month)",
        "highlights": [
            "Cashless hospitalization across 10,500+ network hospitals nationwide",
            "Emergency accidental injuries and OPD reimbursement up to ₹15,000",
            "No pre-policy medical checkup required for under 25",
            "Annual health checkup voucher included",
            "Tax benefit under Section 80D (up to ₹25,000 deduction for parents)"
        ],
        "waiting_period": "30 days initial, accidental hospitalization covered from Day 1",
        "room_rent_limit": "No capping on single private room",
        "recommendation_score": 98
    },
    "POL-HEALTH-COMPREHENSIVE": {
        "id": "POL-HEALTH-COMPREHENSIVE",
        "title": "Nova Comprehensive Health Protect",
        "category": "HEALTH",
        "target_audience": "Individuals and Families (18-65)",
        "sum_insured": "₹10,00,000 - ₹50,00,000",
        "annual_premium": "Starting at ₹6,500/year",
        "highlights": [
            "100% sum insured restoration upon exhaustion",
            "Zero room rent restrictions, day-care procedures covered",
            "Pre and post-hospitalization expenses (60/180 days)",
            "Cumulative no-claim bonus up to 100% of base cover",
            "Section 80D tax deductions up to ₹50,000 (including senior parents)"
        ],
        "waiting_period": "24 months for specified pre-existing diseases",
        "room_rent_limit": "Zero capping",
        "recommendation_score": 95
    },
    "POL-HEALTH-SUPERTOPUP": {
        "id": "POL-HEALTH-SUPERTOPUP",
        "title": "Nova Super Top-Up Health Guard",
        "category": "HEALTH",
        "target_audience": "Enhancing existing corporate or basic health covers",
        "sum_insured": "₹25,00,000 - ₹1,00,00,000",
        "annual_premium": "Starting at ₹3,200/year",
        "highlights": [
            "High deductible (₹5 Lakh) allows massive ₹50 Lakh umbrella cover at low cost",
            "Works seamlessly on top of any employer group health policy",
            "Cashless claim processing across all major hospital chains"
        ],
        "waiting_period": "12 months for pre-existing diseases",
        "room_rent_limit": "No capping",
        "recommendation_score": 92
    },

    # 2. LIFE & ACCIDENT INSURANCE
    "POL-LIFE-TERM": {
        "id": "POL-LIFE-TERM",
        "title": "Nova Shield Pure Term Life Insurance",
        "category": "LIFE",
        "target_audience": "Breadwinners, Early Career, and Young Professionals (18-55)",
        "sum_insured": "₹50,00,000 - ₹2,00,00,000 (₹2 Crore)",
        "annual_premium": "Starting at ₹4,900/year (~₹410/month)",
        "highlights": [
            "Pure risk protection: 100% payout to nominees in unforeseen demise",
            "Terminal illness accelerated payout (50% upfront upon diagnosis)",
            "Optional Accidental Death & Permanent Total Disability riders",
            "Fixed locked-in premium for the entire policy tenure (up to age 75)",
            "Section 80C tax deduction and 10(10D) tax-free claim proceeds"
        ],
        "waiting_period": "Immediate coverage after policy issuance",
        "room_rent_limit": "N/A",
        "recommendation_score": 97
    },
    "POL-LIFE-PMJJBY": {
        "id": "POL-LIFE-PMJJBY",
        "title": "Pradhan Mantri Jeevan Jyoti Bima Yojana (PMJJBY)",
        "category": "GOVT_SCHEME",
        "target_audience": "All Indian Citizens with a Bank Account (18-50 years)",
        "sum_insured": "₹2,00,000 (Life Cover for any cause of death)",
        "annual_premium": "₹436/year (Auto-debited from Savings Account in May)",
        "highlights": [
            "Government of India backed social security insurance scheme",
            "No medical examination or income proof required",
            "Simple one-click enrollment via NovaBank NetBanking or Chat Assistant",
            "Direct beneficiary claim settlement via bank account"
        ],
        "waiting_period": "30-day lien period for non-accidental death in 1st year",
        "room_rent_limit": "N/A",
        "recommendation_score": 99
    },
    "POL-LIFE-PMSBY": {
        "id": "POL-LIFE-PMSBY",
        "title": "Pradhan Mantri Suraksha Bima Yojana (PMSBY)",
        "category": "GOVT_SCHEME",
        "target_audience": "All Indian Citizens with a Bank Account (18-70 years)",
        "sum_insured": "₹2,00,000 (Accidental Death / Full Disability), ₹1,00,000 (Partial)",
        "annual_premium": "₹20/year (Auto-debited from Savings Account)",
        "highlights": [
            "Most affordable accident insurance in the world (under ₹2 per month)",
            "Direct nominee settlement via Aadhaar-linked bank account",
            "Covers accidental road mishaps, falls, and natural disasters"
        ],
        "waiting_period": "Cover begins immediately upon successful auto-debit",
        "room_rent_limit": "N/A",
        "recommendation_score": 99
    },

    # 3. GOVERNMENT INVESTMENT & RETIREMENT SCHEMES
    "POL-GOVT-PPF": {
        "id": "POL-GOVT-PPF",
        "title": "Public Provident Fund (PPF)",
        "category": "GOVT_SCHEME",
        "target_audience": "Long-Term Wealth Builders, Students, and Salaried Individuals",
        "sum_insured": "Sovereign Government Guarantee",
        "annual_premium": "Minimum ₹500/year to Maximum ₹1,50,000/year",
        "highlights": [
            "Current Government Interest Rate: 7.10% p.a. compounded annually",
            "Triple-E (Exempt-Exempt-Exempt) tax benefit under Section 80C",
            "15-year tenure with partial withdrawal facility after Year 6",
            "Immune from attachment by court decree or debt creditors"
        ],
        "waiting_period": "15-year maturity (extendable in 5-year blocks)",
        "room_rent_limit": "N/A",
        "recommendation_score": 96
    },
    "POL-GOVT-NPS": {
        "id": "POL-GOVT-NPS",
        "title": "National Pension System (NPS - Tier 1 & 2)",
        "category": "GOVT_SCHEME",
        "target_audience": "Retirement Planning & Tax Optimizers (18-70)",
        "sum_insured": "Market-linked pension corpus",
        "annual_premium": "Minimum ₹1,000/year",
        "highlights": [
            "Exclusive ₹50,000 tax deduction under Section 80CCD(1B) beyond the ₹1.5L 80C limit",
            "Lowest fund management fee in the world (0.09%)",
            "Choice of Active Choice (Equity, Corporate Debt, Govt Bonds) or Auto Life-Cycle Fund",
            "60% lump-sum tax-free withdrawal at age 60, remaining 40% into regular annuity"
        ],
        "waiting_period": "Locks until age 60 with structured partial withdrawal rules",
        "room_rent_limit": "N/A",
        "recommendation_score": 94
    },
    "POL-GOVT-APY": {
        "id": "POL-GOVT-APY",
        "title": "Atal Pension Yojana (APY)",
        "category": "GOVT_SCHEME",
        "target_audience": "Unorganized Sector, Students, and Early Savers (18-40)",
        "sum_insured": "Guaranteed Monthly Pension of ₹1,000 to ₹5,000 for life",
        "annual_premium": "₹42 - ₹210/month depending on entry age (₹42/mo for 18y age)",
        "highlights": [
            "Government of India guaranteed monthly lifelong pension post age 60",
            "Spouse continues receiving the exact same pension in case of subscriber's demise",
            "Nominee receives 100% accumulated corpus on demise of both subscriber and spouse",
            "Auto-debit from your NovaBank Savings Account"
        ],
        "waiting_period": "Pension starts after attaining 60 years of age",
        "room_rent_limit": "N/A",
        "recommendation_score": 95
    },

    # 4. BANKING DEPOSIT & INTEREST POLICIES
    "POL-BANK-FD": {
        "id": "POL-BANK-FD",
        "title": "NovaBank High-Yield Fixed Deposit (FD)",
        "category": "BANKING_DEPOSIT",
        "target_audience": "Guaranteed Returns Savers & Senior Citizens",
        "sum_insured": "DICGC Insured up to ₹5,00,000 per depositor",
        "annual_premium": "Minimum deposit ₹1,000",
        "highlights": [
            "Interest rates up to 7.25% p.a. for general public, 7.75% for Senior Citizens",
            "Tenures flexible from 7 days to 10 years with monthly/quarterly compounding",
            "Instant loan/overdraft against FD up to 90% of deposit value without breaking FD",
            "Option for tax-saving 5-year lock-in FD under Section 80C"
        ],
        "waiting_period": "Premature withdrawal permitted (1% interest penalty applies)",
        "room_rent_limit": "N/A",
        "recommendation_score": 93
    },
    "POL-BANK-RD": {
        "id": "POL-BANK-RD",
        "title": "NovaBank Recurring Deposit (RD)",
        "category": "BANKING_DEPOSIT",
        "target_audience": "Monthly Disciplined Savers & College Students",
        "sum_insured": "DICGC Insured up to ₹5,00,000",
        "annual_premium": "Starting at ₹500/month",
        "highlights": [
            "Fixed guaranteed returns matching Term Deposit interest rates (up to 7.15% p.a.)",
            "Tenure options from 6 months to 10 years",
            "Auto-debit from savings account on your preferred day each month",
            "No risk of stock market volatility, ideal for short-term targets"
        ],
        "waiting_period": "Flexible closure anytime",
        "room_rent_limit": "N/A",
        "recommendation_score": 91
    }
}


def search_policies(category: Optional[str] = None, query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Filters policy catalog by category or keyword search."""
    results = []
    cat_upper = category.upper().strip() if category else None
    q_lower = query.lower().strip() if query else None

    for policy in POLICY_CATALOG.values():
        if cat_upper and cat_upper != "ALL":
            if policy["category"] != cat_upper and cat_upper not in policy["id"]:
                continue

        if q_lower:
            text_match = (
                q_lower in policy["title"].lower()
                or q_lower in policy["category"].lower()
                or q_lower in policy["target_audience"].lower()
                or any(q_lower in h.lower() for h in policy["highlights"])
                or q_lower in policy["id"].lower()
            )
            # Synonyms matching
            if not text_match:
                if any(k in q_lower for k in ["health", "mediclaim", "hospital", "doctor"]) and policy["category"] == "HEALTH":
                    text_match = True
                elif any(k in q_lower for k in ["life", "term", "death"]) and policy["category"] == "LIFE":
                    text_match = True
                elif any(k in q_lower for k in ["govt", "government", "pension", "pmjjby", "pmsby", "ppf", "nps", "apy"]) and policy["category"] == "GOVT_SCHEME":
                    text_match = True
                elif any(k in q_lower for k in ["fd", "rd", "deposit", "fixed deposit", "recurring"]) and policy["category"] == "BANKING_DEPOSIT":
                    text_match = True

            if not text_match:
                continue

        results.append(policy)

    # Sort by recommendation score descending
    results.sort(key=lambda p: p.get("recommendation_score", 0), reverse=True)
    return results


def get_policy_by_id(policy_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a specific policy by ID or close match."""
    clean_id = policy_id.upper().strip()
    if clean_id in POLICY_CATALOG:
        return POLICY_CATALOG[clean_id]

    for pid, data in POLICY_CATALOG.items():
        if clean_id in pid or clean_id in data["title"].upper():
            return data
    return None

