from django.core.management.base import BaseCommand
from django.utils import timezone

from travel.demo import reset


class Command(BaseCommand):
    help = "Reset demo users, emails, trips, and flight inventory relative to today."

    def handle(self, *args, **options) -> None:
        counts = reset(timezone.now().date())
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {counts['users']} users and {counts['flights']} flights.")
        )
