from django.urls import path

from travel import views

urlpatterns = [
    path("", views.index, name="index"),
    path("inbox/<str:username>/", views.mailbox, name="mailbox"),
    path("inbox/<str:username>/thread/<int:thread_id>/", views.mailbox, name="thread"),
    path("inbox/<str:username>/thread/<int:thread_id>/reply/", views.reply, name="reply"),
    path("inbox/<str:username>/compose/", views.compose, name="compose"),
    path("ops/", views.ops, name="ops"),
    path("ops/flights/<int:flight_id>/disrupt/", views.disrupt, name="disrupt"),
    path("ops/reset/", views.reset_demo, name="reset_demo"),
]
