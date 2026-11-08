import bot.models
import django.db.models.deletion
from django.db import migrations, models


def seed_geography(apps, schema_editor):
    District = apps.get_model('bot', 'District')
    Region = apps.get_model('bot', 'Region')
    districts = [
        ('central', 'Центральный'),
        ('northwestern', 'Северо-Западный'),
        ('southern', 'Южный'),
        ('north_caucasian', 'Северо-Кавказский'),
        ('volga', 'Приволжский'),
        ('ural', 'Уральский'),
        ('siberian', 'Сибирский'),
        ('far_eastern', 'Дальневосточный'),
    ]
    regions = [
        'Белгородская область', 'Брянская область', 'Владимирская область',
        'Воронежская область', 'Ивановская область', 'Калужская область',
        'Костромская область', 'Курская область', 'Липецкая область',
        'Московская область', 'Орловская область', 'Рязанская область',
        'Смоленская область', 'Тамбовская область', 'Тверская область',
        'Тульская область', 'Ярославская область',
    ]
    for order, (code, name) in enumerate(districts):
        district, created = District.objects.using(schema_editor.connection.alias).get_or_create(code=code, defaults={'name': name, 'order': order})
        if code == 'central':
            for index, region in enumerate(regions):
                Region.objects.using(schema_editor.connection.alias).get_or_create(district=district, name=region, defaults={'order': index})


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='District',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Название')),
                ('code', models.CharField(default=bot.models.district_code, editable=False, max_length=64, unique=True, validators=[bot.models.validate_district_code], verbose_name='Системный код')),
                ('active', models.BooleanField(default=True, verbose_name='Доступен для выбора')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
            ],
            options={
                'verbose_name': 'Федеральный округ',
                'verbose_name_plural': 'Федеральные округа',
                'ordering': ['order', 'name', 'pk'],
            },
        ),
        migrations.AlterField(
            model_name='project',
            name='district',
            field=models.CharField(blank=True, max_length=64, verbose_name='Федеральный округ'),
        ),
        migrations.CreateModel(
            name='BotMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('max_chat_id', models.BigIntegerField(unique=True, verbose_name='ID чата MAX')),
                ('message_id', models.CharField(blank=True, max_length=255, verbose_name='ID сообщения MAX')),
                ('payload', models.JSONField(default=dict, verbose_name='Содержимое')),
                ('version', models.PositiveIntegerField(default=0, verbose_name='Версия сообщения')),
                ('page', models.PositiveIntegerField(default=0, verbose_name='Страница')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлено')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='messages', to='bot.project', verbose_name='Проект')),
            ],
            options={
                'verbose_name': 'Рабочее сообщение бота',
                'verbose_name_plural': 'Рабочие сообщения бота',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='Region',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Название')),
                ('active', models.BooleanField(default=True, verbose_name='Доступен для выбора')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
                ('district', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='regions', to='bot.district', verbose_name='Федеральный округ')),
            ],
            options={
                'verbose_name': 'Регион',
                'verbose_name_plural': 'Регионы',
                'ordering': ['order', 'name', 'pk'],
            },
        ),
        migrations.RunPython(seed_geography, migrations.RunPython.noop),
    ]
