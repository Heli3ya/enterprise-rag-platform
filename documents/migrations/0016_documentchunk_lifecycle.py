from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0015_document_versioning"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="purged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="documentchunk",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="documentchunk",
            name="purged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="documentchunk",
            index=models.Index(
                condition=models.Q(("is_active", True)),
                fields=["document"],
                name="documentchunk_active_idx",
            ),
        ),
    ]
