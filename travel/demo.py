from dataclasses import dataclass, field
from datetime import date

from django.db import transaction

from travel import inventory
from travel.models import (
    ActionLog,
    Approval,
    BookingIntent,
    DisruptionEvent,
    Email,
    EmailThread,
    Flight,
    Itinerary,
    SeatPreference,
    Seniority,
    User,
)


@dataclass(frozen=True)
class DemoUser:
    username: str
    first_name: str
    last_name: str
    title: str
    seniority: Seniority
    manager: str | None = None
    prefers_nonstop: bool = False
    avoids_red_eyes: bool = False
    seat_preference: SeatPreference = SeatPreference.NO_PREFERENCE
    preferred_airlines: list[str] = field(default_factory=list)
    frequent_flyer_numbers: dict[str, str] = field(default_factory=dict)

    @property
    def email(self) -> str:
        return f"{self.username}@company.example"


# Managers are listed before their reports so each manager exists when referenced.
DEMO_USERS = [
    DemoUser("daniel", "Daniel", "Park", "CEO", Seniority.EXECUTIVE),
    DemoUser(
        "victoria",
        "Victoria",
        "Chen",
        "VP Sales",
        Seniority.VICE_PRESIDENT,
        manager="daniel",
        preferred_airlines=["BA"],
        frequent_flyer_numbers={"BA": "BA7781203"},
        seat_preference=SeatPreference.AISLE,
    ),
    DemoUser(
        "morgan", "Morgan", "Lee", "Engineering Manager", Seniority.MANAGER, manager="victoria"
    ),
    DemoUser(
        "priya",
        "Priya",
        "Shah",
        "Analyst",
        Seniority.INDIVIDUAL_CONTRIBUTOR,
        manager="morgan",
        prefers_nonstop=True,
        avoids_red_eyes=True,
        preferred_airlines=["UA"],
        frequent_flyer_numbers={"UA": "MP4410298"},
        seat_preference=SeatPreference.WINDOW,
    ),
    DemoUser("sam", "Sam", "Rivera", "Analyst", Seniority.INDIVIDUAL_CONTRIBUTOR, manager="morgan"),
    DemoUser(
        "jordan",
        "Jordan",
        "Kim",
        "Consultant (Acme engagement)",
        Seniority.INDIVIDUAL_CONTRIBUTOR,
        manager="morgan",
        avoids_red_eyes=True,
        preferred_airlines=["AA"],
        frequent_flyer_numbers={"AA": "AAdv93017"},
        seat_preference=SeatPreference.AISLE,
    ),
]


@transaction.atomic
def reset(today: date, days: int = 45) -> dict[str, int]:
    """Wipe demo activity, recreate demo users, and regenerate inventory from `today`.

    Policy versions and billable codes come from migrations and are left as-is.
    """
    for model in (ActionLog, Approval, Itinerary, DisruptionEvent, Email, EmailThread):
        model.objects.all().delete()
    BookingIntent.objects.all().delete()
    Flight.objects.all().delete()
    User.objects.filter(is_superuser=False).delete()

    users: dict[str, User] = {}
    for demo in DEMO_USERS:
        users[demo.username] = User.objects.create(
            username=demo.username,
            email=demo.email,
            first_name=demo.first_name,
            last_name=demo.last_name,
            seniority=demo.seniority,
            manager=users[demo.manager] if demo.manager else None,
            prefers_nonstop=demo.prefers_nonstop,
            avoids_red_eyes=demo.avoids_red_eyes,
            seat_preference=demo.seat_preference,
            preferred_airlines=demo.preferred_airlines,
            frequent_flyer_numbers=demo.frequent_flyer_numbers,
        )
    flights = Flight.objects.bulk_create(inventory.generate(today, days), batch_size=2000)
    return {"users": len(users), "flights": len(flights)}


def title_for(user: User) -> str:
    return next((d.title for d in DEMO_USERS if d.username == user.username), "")
