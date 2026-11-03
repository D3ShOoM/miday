import json

from django.conf import settings
from django.core.management.base import BaseCommand

from picker.gmaps import service


class Command(BaseCommand):
    help = "Show what the app reads from a Google Maps link (bypasses the cache)."

    def add_arguments(self, parser):
        parser.add_argument("link", help="A Google Maps link or pasted share text.")
        parser.add_argument("--keyless", action="store_true", help="Ignore GOOGLE_MAPS_API_KEY.")
        parser.add_argument("--json", action="store_true", help="Print the fields as JSON.")

    def handle(self, *args, link, keyless, **options):
        if keyless:
            settings.GOOGLE_MAPS_API_KEY = ""
        result = service.lookup(link, force=True)
        if options["json"]:
            self.stdout.write(json.dumps(
                {"source": result.source, "notes": result.notes, "fields": result.fields},
                default=str, ensure_ascii=False, indent=2,
            ))
            return
        self.stdout.write(f"source: {result.source_label or 'nothing found'}")
        for note in result.notes:
            self.stdout.write(f"note:   {note}")
        for key, value in result.fields.items():
            value = str(value).replace("\n", " | ")
            self.stdout.write(f"  {key:14} {value[:120]}")
