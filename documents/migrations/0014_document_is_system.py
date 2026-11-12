from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0013_alter_document_file_path"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="is_system",
            field=models.BooleanField(default=False),
        ),
    ]
