from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


SUBJECTS = [
    ("physics", "Физика"),
    ("informatics", "Информатика"),
    ("mathematics", "Математика"),
]
PRODUCT_TYPES = [
    ("research", "Исследование"),
    ("object", "Изделие"),
    ("video", "Видео"),
    ("website", "Сайт"),
]
HOBBIES = [
    ("sport", "Спорт"),
    ("games", "Игры"),
    ("music", "Музыка"),
    ("art", "Творчество"),
    ("technology", "Техника"),
    ("nature", "Природа"),
]
STAGES = [
    ("questionnaire", "Заполняет анкету"),
    ("topic_selection", "Выбирает тему"),
    ("goal", "Формулирует цель"),
    ("tasks", "Формулирует задачи"),
    ("plan", "Получает план"),
    ("implementation", "Выполняет проект"),
    ("submission", "Готовит материалы к сдаче"),
    ("defense", "Готовится к защите"),
    ("completed", "Проект защищён"),
]
PROJECT_STATUSES = [("active", "Активный"), ("defended", "Защищён"), ("deferred", "Отложен"), ("archived", "Архивный")]
REVIEW_STATUSES = [
    ("not_submitted", "Не отправлено"),
    ("submitted", "На проверке"),
    ("needs_revision", "Нужна доработка"),
    ("approved", "Проверено"),
]
JOB_STATUSES = [
    ("pending", "Ожидает"),
    ("running", "Выполняется"),
    ("done", "Выполнено"),
    ("error", "Ошибка"),
    ("cancelled", "Отменено"),
]


def is_administration(user):
    return bool(user.is_authenticated and user.is_active and (user.is_superuser or user.groups.filter(name="Администрация").exists()))


def teacher_for_user(user):
    if not user.is_authenticated or not user.is_active or not user.groups.filter(name="Учителя").exists():
        return None
    return Teacher.objects.filter(user=user, active=True).first()


def private_project_path(instance, filename):
    return f"projects/{instance.project_id}/{uuid4().hex}{Path(filename).suffix.lower()}"


def private_material_path(instance, filename):
    return f"materials/{uuid4().hex}{Path(filename).suffix.lower()}"


def validate_file_size(value):
    if value and value.size > 20971520:
        raise ValidationError("Файл должен быть не больше 20 МБ.")


def district_code():
    return uuid4().hex


def validate_district_code(value):
    if not value:
        raise ValidationError("Системный код не может быть пустым.")
    for symbol in value:
        if not symbol.isascii() or not (symbol.isalnum() or symbol in "_-"):
            raise ValidationError("В системном коде допустимы латинские буквы, цифры, дефис и подчёркивание.")


class District(models.Model):
    name = models.CharField("Название", max_length=200)
    code = models.CharField("Системный код", max_length=64, unique=True, default=district_code, editable=False, validators=[validate_district_code])
    active = models.BooleanField("Доступен для выбора", default=True)
    order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Федеральный округ"
        verbose_name_plural = "Федеральные округа"
        ordering = ["order", "name", "pk"]

    def display_name(self):
        return self.name


class Region(models.Model):
    district = models.ForeignKey(District, on_delete=models.PROTECT, verbose_name="Федеральный округ", related_name="regions")
    name = models.CharField("Название", max_length=200)
    active = models.BooleanField("Доступен для выбора", default=True)
    order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Регион"
        verbose_name_plural = "Регионы"
        ordering = ["order", "name", "pk"]

    def display_name(self):
        return self.name


class RegionalTopic(models.Model):
    region = models.ForeignKey(Region, on_delete=models.PROTECT, verbose_name="Регион", related_name="topics")
    title = models.CharField("Название", max_length=160)
    problem = models.TextField("Проблема региона", max_length=2000)
    subject = models.CharField("Предмет", max_length=40, choices=SUBJECTS, blank=True, help_text="Необязательно. Пустое значение подходит для любого предмета.")
    product_type = models.CharField("Продукт", max_length=20, choices=PRODUCT_TYPES, blank=True, help_text="Необязательно. Пустое значение подходит для любого продукта.")
    hobby = models.CharField("Увлечение", max_length=40, choices=HOBBIES, blank=True, help_text="Необязательно. Пустое значение подходит для любого увлечения.")
    active = models.BooleanField("Доступна для выбора", default=True)
    order = models.PositiveIntegerField("Порядок", default=0)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Тема региона"
        verbose_name_plural = "Темы регионов"
        ordering = ["order", "title", "pk"]

    def display_name(self):
        return self.title


class Student(models.Model):
    max_user_id = models.BigIntegerField("ID пользователя MAX", unique=True)
    max_chat_id = models.BigIntegerField("ID чата MAX")
    full_name = models.CharField("Имя и фамилия", max_length=200, blank=True)
    grade = models.PositiveSmallIntegerField("Класс", choices=[(9, "9 класс")], default=9)
    created_at = models.DateTimeField("Дата регистрации", auto_now_add=True)

    class Meta:
        verbose_name = "Ученик"
        verbose_name_plural = "Ученики"
        ordering = ["full_name", "id"]

    def display_name(self):
        return self.full_name or f"Имя ещё не указано (№ {self.pk})"


class Teacher(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Учётная запись", related_name="teacher")
    full_name = models.CharField("ФИО", max_length=200)
    subject = models.CharField("Предмет", max_length=40, choices=SUBJECTS, blank=True)
    max_link = models.URLField("Ссылка MAX", max_length=500, blank=True)
    max_chat_id = models.BigIntegerField("ID чата MAX", null=True, blank=True)
    active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Учитель"
        verbose_name_plural = "Учителя"
        ordering = ["full_name"]

    def display_name(self):
        return self.full_name


class Project(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name="Ученик", related_name="projects")
    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Наставник", related_name="projects")
    subject = models.CharField("Предмет", max_length=40, choices=SUBJECTS, blank=True)
    product_type = models.CharField("Продукт", max_length=20, choices=PRODUCT_TYPES, blank=True)
    hobby = models.CharField("Увлечение", max_length=40, choices=HOBBIES, blank=True)
    district = models.CharField("Федеральный округ", max_length=64, blank=True)
    region = models.CharField("Регион", max_length=200, blank=True)
    selected_region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Регион из справочника", related_name="projects")
    topics = models.JSONField("Предложенные темы", default=list, blank=True)
    topic = models.CharField("Тема", max_length=160, blank=True)
    topic_source = models.ForeignKey(RegionalTopic, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Основа выбранной темы", related_name="projects")
    literature = models.JSONField("Литература", default=dict, blank=True)
    goal_draft = models.TextField("Черновик цели", blank=True)
    goal = models.TextField("Принятая цель", blank=True)
    goal_feedback = models.JSONField("Замечания по цели", default=dict, blank=True)
    tasks_draft = models.TextField("Черновик задач", blank=True)
    tasks = models.JSONField("Принятые задачи", default=list, blank=True)
    tasks_feedback = models.JSONField("Замечания по задачам", default=dict, blank=True)
    checklist = models.JSONField("Чек-лист", default=list, blank=True)
    stage = models.CharField("Стадия", max_length=30, choices=STAGES, default="questionnaire", db_index=True)
    stage_changed_at = models.DateTimeField("На текущей стадии с", default=timezone.now)
    last_student_activity_at = models.DateTimeField("Последнее действие ученика", null=True, blank=True, db_index=True)
    step = models.CharField("Шаг диалога", max_length=50, default="start")
    return_step = models.CharField("Шаг возврата", max_length=50, blank=True)
    status = models.CharField("Статус проекта", max_length=20, choices=PROJECT_STATUSES, default="active", db_index=True)
    review_status = models.CharField("Статус проверки", max_length=20, choices=REVIEW_STATUSES, default="not_submitted", db_index=True)
    teacher_feedback = models.TextField("Замечание учителя", blank=True)
    submitted_at = models.DateTimeField("Отправлен на проверку", null=True, blank=True)
    defended_at = models.DateTimeField("Защищён", null=True, blank=True)
    revision = models.PositiveIntegerField("Версия проекта", default=1)
    pending_changes = models.JSONField("Изменения для подтверждения", default=dict, blank=True)
    defense_attempt = models.PositiveIntegerField("Попытка репетиции", default=0)
    defense_ends_at = models.DateTimeField("Репетиция заканчивается", null=True, blank=True, db_index=True)
    defense_questions = models.JSONField("Вопросы к защите", default=list, blank=True)
    defense_notified_at = models.DateTimeField("Уведомление о завершении репетиции", null=True, blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"
        ordering = ["-last_student_activity_at", "-stage_changed_at"]
        constraints = [models.UniqueConstraint(fields=["student"], condition=Q(status__in=["active", "defended"]), name="one_current_project_per_student")]

    @property
    def student_name(self):
        return self.student.display_name()

    @property
    def district_name(self):
        from .texts import DISTRICTS

        return District.objects.filter(code=self.district).values_list("name", flat=True).first() or DISTRICTS.get(self.district, self.district)

    @property
    def stage_label(self):
        if self.stage == "submission" and self.review_status == "needs_revision":
            return "Дорабатывает материалы"
        return self.get_stage_display()

    @property
    def checklist_progress(self):
        if not self.checklist:
            return "Нет плана"
        done = 0
        for item in self.checklist:
            if isinstance(item, dict) and item.get("done"):
                done += 1
        return f"Выполнено {done} из {len(self.checklist)}"

    def display_name(self):
        return f"{self.student_name}: {self.topic or 'Ещё не выбрана'}"


class ProjectFile(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, verbose_name="Проект", related_name="files")
    kind = models.CharField("Вид", max_length=10, choices=[("file", "Файл"), ("link", "Ссылка")])
    original_name = models.CharField("Исходное название", max_length=255, blank=True)
    stored_file = models.FileField("Файл", upload_to=private_project_path, null=True, blank=True, validators=[FileExtensionValidator(["pdf", "docx", "pptx", "png", "jpg", "jpeg"]), validate_file_size])
    external_url = models.URLField("Внешняя ссылка", max_length=2000, null=True, blank=True)
    max_attachment_id = models.CharField("ID вложения MAX", max_length=500, null=True, blank=True)
    created_at = models.DateTimeField("Загружен", auto_now_add=True)

    class Meta:
        verbose_name = "Материал ученика"
        verbose_name_plural = "Материалы учеников"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind="file") & Q(stored_file__isnull=False) & ~Q(stored_file="") & (Q(external_url__isnull=True) | Q(external_url="")))
                | (Q(kind="link") & Q(external_url__isnull=False) & ~Q(external_url="") & (Q(stored_file__isnull=True) | Q(stored_file=""))),
                name="project_file_has_file_or_link",
            )
        ]

    def clean(self):
        super().clean()
        if bool(self.stored_file) == bool(self.external_url):
            raise ValidationError("Укажите файл или внешнюю ссылку.")
        if self.kind == "file" and not self.stored_file:
            raise ValidationError({"stored_file": "Для этого вида материала нужен файл."})
        if self.kind == "link" and not self.external_url:
            raise ValidationError({"external_url": "Для этого вида материала нужна ссылка."})

    def display_name(self):
        return self.original_name or self.external_url or f"Материал № {self.pk}"


class Material(models.Model):
    code = models.CharField("Код", max_length=40, unique=True)
    title = models.CharField("Название", max_length=200)
    file = models.FileField("Файл", upload_to=private_material_path, null=True, blank=True)
    external_url = models.URLField("Ссылка", max_length=2000, null=True, blank=True)
    description = models.TextField("Описание", blank=True)
    active = models.BooleanField("Доступен", default=True)

    class Meta:
        verbose_name = "Методический материал"
        verbose_name_plural = "Методические материалы"
        ordering = ["title"]

    def display_name(self):
        return self.title


class Prompt(models.Model):
    code = models.CharField("Назначение", max_length=40, unique=True)
    instruction = models.TextField("Инструкция")
    version = models.PositiveIntegerField("Версия", default=1)
    active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Промпт"
        verbose_name_plural = "Промпты"
        ordering = ["code"]

    def display_name(self):
        return f"{self.code}, версия {self.version}"


class BotEvent(models.Model):
    deduplication_key = models.CharField("Ключ повторной доставки", max_length=255, unique=True)
    event_type = models.CharField("Тип события", max_length=100)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Проект", related_name="events")
    payload = models.JSONField("Содержимое", default=dict)
    status = models.CharField("Состояние", max_length=20, choices=[("pending", "Ожидает"), ("done", "Обработано"), ("error", "Ошибка")], default="pending", db_index=True)
    created_at = models.DateTimeField("Получено", auto_now_add=True)
    processed_at = models.DateTimeField("Обработано", null=True, blank=True)

    class Meta:
        verbose_name = "Событие бота"
        verbose_name_plural = "События бота"
        ordering = ["-created_at"]

    def display_name(self):
        return f"{self.event_type}: {self.deduplication_key}"


class BotJob(models.Model):
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Проект", related_name="jobs")
    event = models.ForeignKey(BotEvent, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Событие", related_name="jobs")
    kind = models.CharField("Вид задания", max_length=100)
    deduplication_key = models.CharField("Ключ повторного задания", max_length=255, null=True, blank=True, unique=True)
    payload = models.JSONField("Данные задания", default=dict)
    project_revision = models.PositiveIntegerField("Версия проекта", null=True, blank=True)
    prompt_version = models.PositiveIntegerField("Версия промпта", null=True, blank=True)
    status = models.CharField("Состояние", max_length=20, choices=JOB_STATUSES, default="pending", db_index=True)
    run_at = models.DateTimeField("Выполнить после", default=timezone.now, db_index=True)
    attempts = models.PositiveIntegerField("Число попыток", default=0)
    result = models.JSONField("Результат", default=dict, blank=True)
    error_text = models.TextField("Код ошибки", blank=True)
    locked_at = models.DateTimeField("Взято в работу", null=True, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    finished_at = models.DateTimeField("Завершено", null=True, blank=True)

    class Meta:
        verbose_name = "Задание бота"
        verbose_name_plural = "Задания бота"
        ordering = ["run_at", "id"]
        indexes = [models.Index(fields=["status", "run_at"], name="bot_job_ready_idx")]

    def display_name(self):
        return f"{self.kind} № {self.pk}"


class BotMessage(models.Model):
    max_chat_id = models.BigIntegerField("ID чата MAX", unique=True)
    message_id = models.CharField("ID сообщения MAX", max_length=255, blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Проект", related_name="messages")
    payload = models.JSONField("Содержимое", default=dict)
    version = models.PositiveIntegerField("Версия сообщения", default=0)
    page = models.PositiveIntegerField("Страница", default=0)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Рабочее сообщение бота"
        verbose_name_plural = "Рабочие сообщения бота"
        ordering = ["-updated_at"]

    def display_name(self):
        return f"Сообщение чата {self.max_chat_id}"
