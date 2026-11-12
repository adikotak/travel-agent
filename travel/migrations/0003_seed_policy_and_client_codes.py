from django.db import migrations

POLICY_RULES = {
    "budget_per_direction": {
        "duration_basis": "total-travel-time",
        "long_haul_threshold_minutes": 360,
        "short_haul_max_usd": 400,
        "long_haul_max_usd": 1500,
    },
    "cabins": {
        "short_haul": ["economy"],
        "long_haul": ["economy", "premium-economy"],
        "senior_long_haul": {
            "min_seniority": "vice-president",
            "cabins": ["economy", "premium-economy", "business"],
            "max_usd": 3000,
        },
    },
    "lowest_logical_fare": {
        "max_over_cheapest_pct": 20,
        "exempt_if_saves_minutes": 120,
    },
    "booking_window": {"min_days_in_advance": 7},
    "never_allowed": {"cabins": ["first"]},
    "disruption_rebooking": {
        "max_cabin": "same-or-lower",
        "max_price_increase_usd": 200,
        "exempt_from_booking_window": True,
    },
}

APPROVAL_RULES = {
    "approver": "manager",
    "requires_approval": [
        "over-budget",
        "cabin-not-allowed",
        "inside-booking-window",
        "above-lowest-logical-fare",
        "disruption-rebooking-over-limit",
    ],
    "always_rejected": ["never-allowed-cabin"],
    "auto_book_requires": [
        "in-policy",
        "billable-code-when-client-billable",
        "unambiguous-request",
    ],
}

CLIENT_CODES = [
    {
        "code": "ACME-001",
        "client_name": "Acme Corp",
        "policy_overrides": {
            "budget_per_direction": {"short_haul_max_usd": 350, "long_haul_max_usd": 900},
            "cabins": {
                "short_haul": ["economy"],
                "long_haul": ["economy"],
                "senior_long_haul": {"cabins": ["economy"], "max_usd": 900},
            },
            "booking_window": {"min_days_in_advance": 14},
        },
    },
    {
        "code": "GLOBEX-001",
        "client_name": "Globex",
        "policy_overrides": {
            "budget_per_direction": {
                "long_haul_threshold_minutes": 240,
                "long_haul_max_usd": 2000,
            },
            "cabins": {"long_haul": ["economy", "premium-economy", "business"]},
        },
    },
    {
        "code": "INITECH-001",
        "client_name": "Initech",
        "policy_overrides": {},
    },
]


def seed(apps, schema_editor):
    TravelPolicy = apps.get_model("travel", "TravelPolicy")
    BillableCode = apps.get_model("travel", "BillableCode")
    TravelPolicy.objects.create(
        version=1, rules=POLICY_RULES, approval_rules=APPROVAL_RULES, is_active=True
    )
    for client_code in CLIENT_CODES:
        BillableCode.objects.create(is_client_billable=True, **client_code)


def unseed(apps, schema_editor):
    apps.get_model("travel", "TravelPolicy").objects.filter(version=1).delete()
    apps.get_model("travel", "BillableCode").objects.filter(
        code__in=[client_code["code"] for client_code in CLIENT_CODES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0002_vice_president_and_contract_overrides"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
