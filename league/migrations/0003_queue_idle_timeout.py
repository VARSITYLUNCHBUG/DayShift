import django.core.validators
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('league', '0002_submission_image_type_and_command_fingerprint'),
    ]

    operations = [
        # Anyone already waiting starts a fresh idle clock, from the deploy.
        migrations.AddField(
            model_name='queueentry',
            name='active_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='queueentry',
            name='warned_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='runtimesettings',
            name='queue_idle_minutes',
            field=models.PositiveSmallIntegerField(default=90, help_text="Minutes a player can sit in the queue without checking in. Then they're taken out, with no penalty, so they can't miss a ready check. 0 turns this off.", validators=[django.core.validators.MaxValueValidator(1440)]),
        ),
        migrations.AddField(
            model_name='runtimesettings',
            name='queue_warn_minutes',
            field=models.PositiveSmallIntegerField(default=5, help_text='Minutes before they\'re taken out that a "Still queueing?" DM asks them to stay in. 0: no DM. Must be less than the idle minutes.', validators=[django.core.validators.MaxValueValidator(1440)]),
        ),
    ]
