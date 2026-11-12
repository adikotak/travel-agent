from django.db import migrations

CABIN_NOT_ALLOWED = "cabin-not-allowed"


def activate_v2(apps, schema_editor):
    TravelPolicy = apps.get_model("travel", "TravelPolicy")
    v1 = TravelPolicy.objects.get(version=1)
    approval_rules = dict(v1.approval_rules)
    approval_rules["requires_approval"] = [
        v for v in approval_rules["requires_approval"] if v != CABIN_NOT_ALLOWED
    ]
    approval_rules["always_rejected"] = [*approval_rules["always_rejected"], CABIN_NOT_ALLOWED]
    v1.is_active = False
    v1.save(update_fields=["is_active"])
    TravelPolicy.objects.create(
        version=2, rules=v1.rules, approval_rules=approval_rules, is_active=True
    )


def restore_v1(apps, schema_editor):
    TravelPolicy = apps.get_model("travel", "TravelPolicy")
    TravelPolicy.objects.filter(version=2).delete()
    TravelPolicy.objects.filter(version=1).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0005_email_card"),
    ]

    operations = [migrations.RunPython(activate_v2, restore_v1)]
