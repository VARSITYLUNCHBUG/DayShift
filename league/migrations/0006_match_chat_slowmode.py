import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('league', '0005_team_confirm'),
    ]

    operations = [
        migrations.AddField(
            model_name='runtimesettings',
            name='match_chat_slowmode_seconds',
            field=models.PositiveSmallIntegerField(default=3, help_text="Discord slowmode in each new match channel: seconds each player waits between messages, so chat can't bury the board. Staff aren't slowed. 0 turns it off. Set when the channel is made, so it costs no extra request.", validators=[django.core.validators.MaxValueValidator(21600)]),
        ),
    ]
