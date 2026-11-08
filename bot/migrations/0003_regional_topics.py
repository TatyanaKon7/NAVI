import django.db.models.deletion
from django.db import migrations, models


def match_selected_regions(apps, schema_editor):
    Project = apps.get_model("bot", "Project")
    Region = apps.get_model("bot", "Region")
    alias = schema_editor.connection.alias
    matches = {}
    for region_id, district_code, name in Region.objects.using(alias).values_list("pk", "district__code", "name"):
        key = (district_code, name)
        if key in matches:
            matches[key] = None
        else:
            matches[key] = region_id
    for (district_code, name), region_id in matches.items():
        if region_id is not None:
            Project.objects.using(alias).filter(district=district_code, region=name, selected_region__isnull=True).update(selected_region_id=region_id)


class Migration(migrations.Migration):
    dependencies = [
        ("bot", "0002_geography_and_working_messages"),
    ]

    operations = [
        migrations.CreateModel(
            name="RegionalTopic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160, verbose_name="Название")),
                ("problem", models.TextField(max_length=2000, verbose_name="Проблема региона")),
                ("subject", models.CharField(blank=True, choices=[("physics", "Физика"), ("informatics", "Информатика"), ("mathematics", "Математика")], help_text="Необязательно. Пустое значение подходит для любого предмета.", max_length=40, verbose_name="Предмет")),
                ("product_type", models.CharField(blank=True, choices=[("research", "Исследование"), ("object", "Изделие"), ("video", "Видео"), ("website", "Сайт")], help_text="Необязательно. Пустое значение подходит для любого продукта.", max_length=20, verbose_name="Продукт")),
                ("hobby", models.CharField(blank=True, choices=[("sport", "Спорт"), ("games", "Игры"), ("music", "Музыка"), ("art", "Творчество"), ("technology", "Техника"), ("nature", "Природа")], help_text="Необязательно. Пустое значение подходит для любого увлечения.", max_length=40, verbose_name="Увлечение")),
                ("active", models.BooleanField(default=True, verbose_name="Доступна для выбора")),
                ("order", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлена")),
                ("region", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="topics", to="bot.region", verbose_name="Регион")),
            ],
            options={
                "verbose_name": "Тема региона",
                "verbose_name_plural": "Темы регионов",
                "ordering": ["order", "title", "pk"],
            },
        ),
        migrations.AddField(
            model_name="project",
            name="selected_region",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="projects", to="bot.region", verbose_name="Регион из справочника"),
        ),
        migrations.AddField(
            model_name="project",
            name="topic_source",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="projects", to="bot.regionaltopic", verbose_name="Основа выбранной темы"),
        ),
        migrations.RunPython(match_selected_regions, migrations.RunPython.noop),
    ]
