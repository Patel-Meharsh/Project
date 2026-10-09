"""Approved operating budget figures supplied by the business.

Period totals are maintained independently because the approved figures are
rounded/planned values and are not exact multiples of the monthly amount.
Category allocations are shown as supplied and are not silently rebalanced.
"""
APPROVED_BUDGET = {
    "monthly": 60100.0,
    "quarterly": 180000.0,
    "half_yearly": 360000.0,
    "yearly": 720000.0,
    "default_inflation_pct": 6.0,
    "categories": [
        {"category": "Washroom Supplies", "yearly": 480000.0},
        {"category": "Cleaning Chemicals", "yearly": 130000.0},
        {"category": "Pantry", "yearly": 60500.0},
        {"category": "PPE & Safety", "yearly": 16800.0},
        {"category": "Waste Management", "yearly": 15700.0},
        {"category": "Cleaning Tools", "yearly": 15000.0},
        {"category": "Electrical", "yearly": 372.24},
        {"category": "Pest Control", "yearly": 0.0},
    ],
}
