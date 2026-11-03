from django.urls import path

from .views import polls, restaurants

urlpatterns = [
    path("", restaurants.index, name="home"),
    path("restaurants/add/", restaurants.edit, name="restaurant_add"),
    path("restaurants/<int:pk>/edit/", restaurants.edit, name="restaurant_edit"),
    path("restaurants/<int:pk>/remove/", restaurants.remove, name="restaurant_remove"),
    path("restaurants/<int:pk>/restore/", restaurants.restore, name="restaurant_restore"),
    path("votes/new/", polls.create, name="poll_new"),
    path("v/<slug:slug>/", polls.detail, name="poll"),
    path("v/<slug:slug>/o/<int:option_id>/", polls.option, name="poll_option"),
    path("v/<slug:slug>/add/", polls.add_option, name="poll_add"),
    path("v/<slug:slug>/name/", polls.set_name, name="poll_name"),
    path("v/<slug:slug>/manage/<str:key>/", polls.manage, name="poll_manage"),
    path("v/<slug:slug>/state/", polls.set_state, name="poll_state"),
]
