import bot.models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Material',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=40, unique=True, verbose_name='Код')),
                ('title', models.CharField(max_length=200, verbose_name='Название')),
                ('file', models.FileField(blank=True, null=True, upload_to=bot.models.private_material_path, verbose_name='Файл')),
                ('external_url', models.URLField(blank=True, max_length=2000, null=True, verbose_name='Ссылка')),
                ('description', models.TextField(blank=True, verbose_name='Описание')),
                ('active', models.BooleanField(default=True, verbose_name='Доступен')),
            ],
            options={
                'verbose_name': 'Методический материал',
                'verbose_name_plural': 'Методические материалы',
                'ordering': ['title'],
            },
        ),
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject', models.CharField(blank=True, choices=[('physics', 'Физика'), ('informatics', 'Информатика'), ('mathematics', 'Математика')], max_length=40, verbose_name='Предмет')),
                ('product_type', models.CharField(blank=True, choices=[('research', 'Исследование'), ('object', 'Изделие'), ('video', 'Видео'), ('website', 'Сайт')], max_length=20, verbose_name='Продукт')),
                ('hobby', models.CharField(blank=True, choices=[('sport', 'Спорт'), ('games', 'Игры'), ('music', 'Музыка'), ('art', 'Творчество'), ('technology', 'Техника'), ('nature', 'Природа')], max_length=40, verbose_name='Увлечение')),
                ('district', models.CharField(blank=True, choices=[('central', 'Центральный'), ('northwestern', 'Северо-Западный'), ('southern', 'Южный'), ('north_caucasian', 'Северо-Кавказский'), ('volga', 'Приволжский'), ('ural', 'Уральский'), ('siberian', 'Сибирский'), ('far_eastern', 'Дальневосточный')], max_length=64, verbose_name='Федеральный округ')),
                ('region', models.CharField(blank=True, max_length=200, verbose_name='Регион')),
                ('topics', models.JSONField(blank=True, default=list, verbose_name='Предложенные темы')),
                ('topic', models.CharField(blank=True, max_length=160, verbose_name='Тема')),
                ('literature', models.JSONField(blank=True, default=dict, verbose_name='Литература')),
                ('goal_draft', models.TextField(blank=True, verbose_name='Черновик цели')),
                ('goal', models.TextField(blank=True, verbose_name='Принятая цель')),
                ('goal_feedback', models.JSONField(blank=True, default=dict, verbose_name='Замечания по цели')),
                ('tasks_draft', models.TextField(blank=True, verbose_name='Черновик задач')),
                ('tasks', models.JSONField(blank=True, default=list, verbose_name='Принятые задачи')),
                ('tasks_feedback', models.JSONField(blank=True, default=dict, verbose_name='Замечания по задачам')),
                ('checklist', models.JSONField(blank=True, default=list, verbose_name='Чек-лист')),
                ('stage', models.CharField(choices=[('questionnaire', 'Заполняет анкету'), ('topic_selection', 'Выбирает тему'), ('goal', 'Формулирует цель'), ('tasks', 'Формулирует задачи'), ('plan', 'Получает план'), ('implementation', 'Выполняет проект'), ('submission', 'Готовит материалы к сдаче'), ('defense', 'Готовится к защите'), ('completed', 'Проект защищён')], db_index=True, default='questionnaire', max_length=30, verbose_name='Стадия')),
                ('stage_changed_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='На текущей стадии с')),
                ('last_student_activity_at', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Последнее действие ученика')),
                ('step', models.CharField(default='start', max_length=50, verbose_name='Шаг диалога')),
                ('return_step', models.CharField(blank=True, max_length=50, verbose_name='Шаг возврата')),
                ('status', models.CharField(choices=[('active', 'Активный'), ('defended', 'Защищён'), ('archived', 'Архивный')], db_index=True, default='active', max_length=20, verbose_name='Статус проекта')),
                ('review_status', models.CharField(choices=[('not_submitted', 'Не отправлено'), ('submitted', 'На проверке'), ('needs_revision', 'Нужна доработка'), ('approved', 'Проверено')], db_index=True, default='not_submitted', max_length=20, verbose_name='Статус проверки')),
                ('teacher_feedback', models.TextField(blank=True, verbose_name='Замечание учителя')),
                ('submitted_at', models.DateTimeField(blank=True, null=True, verbose_name='Отправлен на проверку')),
                ('defended_at', models.DateTimeField(blank=True, null=True, verbose_name='Защищён')),
                ('revision', models.PositiveIntegerField(default=1, verbose_name='Версия проекта')),
                ('pending_changes', models.JSONField(blank=True, default=dict, verbose_name='Изменения для подтверждения')),
                ('defense_attempt', models.PositiveIntegerField(default=0, verbose_name='Попытка репетиции')),
                ('defense_ends_at', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Репетиция заканчивается')),
                ('defense_questions', models.JSONField(blank=True, default=list, verbose_name='Вопросы к защите')),
                ('defense_notified_at', models.DateTimeField(blank=True, null=True, verbose_name='Уведомление о завершении репетиции')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлён')),
            ],
            options={
                'verbose_name': 'Проект',
                'verbose_name_plural': 'Проекты',
                'ordering': ['-last_student_activity_at', '-stage_changed_at'],
            },
        ),
        migrations.CreateModel(
            name='Prompt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=40, unique=True, verbose_name='Назначение')),
                ('instruction', models.TextField(verbose_name='Инструкция')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Версия')),
                ('active', models.BooleanField(default=True, verbose_name='Активен')),
            ],
            options={
                'verbose_name': 'Промпт',
                'verbose_name_plural': 'Промпты',
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='Student',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('max_user_id', models.BigIntegerField(unique=True, verbose_name='ID пользователя MAX')),
                ('max_chat_id', models.BigIntegerField(verbose_name='ID чата MAX')),
                ('full_name', models.CharField(blank=True, max_length=200, verbose_name='Имя и фамилия')),
                ('grade', models.PositiveSmallIntegerField(choices=[(9, '9 класс')], default=9, verbose_name='Класс')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата регистрации')),
            ],
            options={
                'verbose_name': 'Ученик',
                'verbose_name_plural': 'Ученики',
                'ordering': ['full_name', 'id'],
            },
        ),
        migrations.CreateModel(
            name='BotEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('deduplication_key', models.CharField(max_length=255, unique=True, verbose_name='Ключ повторной доставки')),
                ('event_type', models.CharField(max_length=100, verbose_name='Тип события')),
                ('payload', models.JSONField(default=dict, verbose_name='Содержимое')),
                ('status', models.CharField(choices=[('pending', 'Ожидает'), ('done', 'Обработано'), ('error', 'Ошибка')], db_index=True, default='pending', max_length=20, verbose_name='Состояние')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Получено')),
                ('processed_at', models.DateTimeField(blank=True, null=True, verbose_name='Обработано')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='events', to='bot.project', verbose_name='Проект')),
            ],
            options={
                'verbose_name': 'Событие бота',
                'verbose_name_plural': 'События бота',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='project',
            name='student',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='projects', to='bot.student', verbose_name='Ученик'),
        ),
        migrations.CreateModel(
            name='Teacher',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(max_length=200, verbose_name='ФИО')),
                ('subject', models.CharField(blank=True, choices=[('physics', 'Физика'), ('informatics', 'Информатика'), ('mathematics', 'Математика')], max_length=40, verbose_name='Предмет')),
                ('max_link', models.URLField(blank=True, max_length=500, verbose_name='Ссылка MAX')),
                ('max_chat_id', models.BigIntegerField(blank=True, null=True, verbose_name='ID чата MAX')),
                ('active', models.BooleanField(default=True, verbose_name='Активен')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='teacher', to=settings.AUTH_USER_MODEL, verbose_name='Учётная запись')),
            ],
            options={
                'verbose_name': 'Учитель',
                'verbose_name_plural': 'Учителя',
                'ordering': ['full_name'],
            },
        ),
        migrations.AddField(
            model_name='project',
            name='teacher',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='projects', to='bot.teacher', verbose_name='Наставник'),
        ),
        migrations.CreateModel(
            name='BotJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(max_length=100, verbose_name='Вид задания')),
                ('deduplication_key', models.CharField(blank=True, max_length=255, null=True, unique=True, verbose_name='Ключ повторного задания')),
                ('payload', models.JSONField(default=dict, verbose_name='Данные задания')),
                ('project_revision', models.PositiveIntegerField(blank=True, null=True, verbose_name='Версия проекта')),
                ('prompt_version', models.PositiveIntegerField(blank=True, null=True, verbose_name='Версия промпта')),
                ('status', models.CharField(choices=[('pending', 'Ожидает'), ('running', 'Выполняется'), ('done', 'Выполнено'), ('error', 'Ошибка'), ('cancelled', 'Отменено')], db_index=True, default='pending', max_length=20, verbose_name='Состояние')),
                ('run_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name='Выполнить после')),
                ('attempts', models.PositiveIntegerField(default=0, verbose_name='Число попыток')),
                ('result', models.JSONField(blank=True, default=dict, verbose_name='Результат')),
                ('error_text', models.TextField(blank=True, verbose_name='Код ошибки')),
                ('locked_at', models.DateTimeField(blank=True, null=True, verbose_name='Взято в работу')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='Завершено')),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='jobs', to='bot.botevent', verbose_name='Событие')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='jobs', to='bot.project', verbose_name='Проект')),
            ],
            options={
                'verbose_name': 'Задание бота',
                'verbose_name_plural': 'Задания бота',
                'ordering': ['run_at', 'id'],
                'indexes': [models.Index(fields=['status', 'run_at'], name='bot_job_ready_idx')],
            },
        ),
        migrations.CreateModel(
            name='ProjectFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('file', 'Файл'), ('link', 'Ссылка')], max_length=10, verbose_name='Вид')),
                ('original_name', models.CharField(blank=True, max_length=255, verbose_name='Исходное название')),
                ('stored_file', models.FileField(blank=True, null=True, upload_to=bot.models.private_project_path, validators=[django.core.validators.FileExtensionValidator(['pdf', 'docx', 'pptx', 'png', 'jpg', 'jpeg']), bot.models.validate_file_size], verbose_name='Файл')),
                ('external_url', models.URLField(blank=True, max_length=2000, null=True, verbose_name='Внешняя ссылка')),
                ('max_attachment_id', models.CharField(blank=True, max_length=500, null=True, verbose_name='ID вложения MAX')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Загружен')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='files', to='bot.project', verbose_name='Проект')),
            ],
            options={
                'verbose_name': 'Материал ученика',
                'verbose_name_plural': 'Материалы учеников',
                'ordering': ['created_at'],
                'constraints': [models.CheckConstraint(condition=models.Q(models.Q(('kind', 'file'), ('stored_file__isnull', False), models.Q(('stored_file', ''), _negated=True), models.Q(('external_url__isnull', True), ('external_url', ''), _connector='OR')), models.Q(('kind', 'link'), ('external_url__isnull', False), models.Q(('external_url', ''), _negated=True), models.Q(('stored_file__isnull', True), ('stored_file', ''), _connector='OR')), _connector='OR'), name='project_file_has_file_or_link')],
            },
        ),
        migrations.AddConstraint(
            model_name='project',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'archived'), _negated=True), fields=('student',), name='one_current_project_per_student'),
        ),
    ]
