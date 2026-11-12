from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from travel.models import (
    ActionLog,
    Approval,
    BillableCode,
    BookingIntent,
    DisruptionEvent,
    Email,
    EmailThread,
    Flight,
    Itinerary,
    TravelPolicy,
    User,
)


@admin.register(User)
class TravelUserAdmin(UserAdmin):
    fieldsets = (
        *UserAdmin.fieldsets,
        (
            "Travel",
            {
                "fields": (
                    "manager",
                    "seniority",
                    "seat_preference",
                    "preferred_airlines",
                    "frequent_flyer_numbers",
                )
            },
        ),
    )
    list_display = ("username", "email", "seniority", "manager")


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = (
        "flight_number",
        "origin",
        "destination",
        "departs_at",
        "duration_minutes",
        "cabin",
        "price",
        "is_refundable",
        "seats_left",
    )
    list_filter = ("origin", "destination", "cabin", "airline")


class EmailInline(admin.TabularInline):
    model = Email
    extra = 0
    fields = ("direction", "from_address", "subject", "sent_at")
    readonly_fields = fields


@admin.register(EmailThread)
class EmailThreadAdmin(admin.ModelAdmin):
    list_display = ("subject", "booking_intent", "created_at")
    inlines = [EmailInline]


class ActionLogInline(admin.TabularInline):
    model = ActionLog
    extra = 0
    fields = ("action", "reasoning", "created_at")
    readonly_fields = fields


@admin.register(BookingIntent)
class BookingIntentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "traveler", "billable_code", "status", "created_at")
    list_filter = ("status",)
    inlines = [ActionLogInline]


@admin.register(Approval)
class ApprovalAdmin(admin.ModelAdmin):
    list_display = ("booking_intent", "approver", "quoted_price", "status", "decided_at")
    list_filter = ("status",)


@admin.register(Itinerary)
class ItineraryAdmin(admin.ModelAdmin):
    list_display = ("booking_intent", "total_price", "policy", "status", "booked_at")
    list_filter = ("status",)


@admin.register(DisruptionEvent)
class DisruptionEventAdmin(admin.ModelAdmin):
    list_display = ("flight", "kind", "delay_minutes", "occurred_at", "processed_at")
    list_filter = ("kind",)


admin.site.register(TravelPolicy)
admin.site.register(BillableCode)
admin.site.register(Email)
admin.site.register(ActionLog)
