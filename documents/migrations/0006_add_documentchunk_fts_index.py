from django.db import migrations
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0005_add_embedding_hnsw_index'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='documentchunk',
            index=GinIndex(
                SearchVector(
                    'content',
                    config='simple',
                ),
                name='documentchunk_content_fts_idx',
            ),
        ),
    ]