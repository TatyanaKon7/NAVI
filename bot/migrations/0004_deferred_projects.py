from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bot", "0003_regional_topics"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="project",
            name="one_current_project_per_student",
        ),
        migrations.AlterField(
            model_name="project",
            name="status",
            field=models.CharField(choices=[("active", "Активный"), ("defended", "Защищён"), ("deferred", "Отложен"), ("archived", "Архивный")], db_index=True, default="active", max_length=20, verbose_name="Статус проекта"),
        ),
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(condition=models.Q(status__in=["active", "defended"]), fields=("student",), name="one_current_project_per_student"),
        ),
    ]
