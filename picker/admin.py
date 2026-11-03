from django.contrib import admin

from .models import Poll, PollOption, Restaurant, Vote, Voter


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ["name", "cuisine", "rating", "review_count", "price_level", "info_source", "removed_at"]
    list_filter = [("removed_at", admin.EmptyFieldListFilter), "info_source"]
    search_fields = ["name", "cuisine", "address", "notes"]


class PollOptionInline(admin.TabularInline):
    model = PollOption
    extra = 0
    raw_id_fields = ["restaurant"]


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "created_at", "closes_at", "closed_at"]
    readonly_fields = ["slug", "admin_key", "version", "created_at"]
    inlines = [PollOptionInline]


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ["option", "voter", "value", "comment", "updated_at"]
    list_select_related = ["option__poll", "option__restaurant", "voter"]
    raw_id_fields = ["option", "voter"]


@admin.register(Voter)
class VoterAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "created_at"]
    search_fields = ["name"]
