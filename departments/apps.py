from django.apps import AppConfig


class DepartmentsConfig(AppConfig):
    name = 'departments'

    def ready(self):
        # Registers the post_save hook that seeds the cold-start guide.
        from . import signals  # noqa: F401
