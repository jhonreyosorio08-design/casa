from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("restaurant", "0022_sitecontent_gcash_account_name_and_more")]

    operations = [
        migrations.AlterField(
            model_name="reservation",
            name="source",
            field=models.CharField(
                choices=[("online", "Online"), ("walk_in", "Walk-In"), ("admin", "Admin")],
                default="online",
                max_length=8,
            ),
        ),
    ]
