from django.apps import AppConfig
from django.core import checks


class TcnConfig(AppConfig):
    name = "testlab.tcn"
    label = "tcn"
    verbose_name = "TCN"

    def ready(self):
        from testlab.documents.checks import chromium_check

        checks.register(chromium_check)
