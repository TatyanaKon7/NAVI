from urllib.parse import urlencode, urlparse

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from .models import BotMessage, District, Material, Project, ProjectFile, Prompt, Region, RegionalTopic, Student, Teacher, is_administration, teacher_for_user


class ProjectStatusFilter(admin.SimpleListFilter):
    title = "статус проекта"
    parameter_name = "project_status"

    def lookups(self, request, model_admin):
        return [("current", "Текущие"), ("active", "Активные"), ("defended", "Защищённые"), ("deferred", "Отложенные"), ("archived", "Архивные"), ("all", "Все")]

    def queryset(self, request, queryset):
        value = self.value()
        if value in (None, "current"):
            return queryset.filter(status__in=["active", "defended"])
        if value in ("active", "defended", "deferred", "archived"):
            return queryset.filter(status=value)
        return queryset


class TeacherFilter(admin.SimpleListFilter):
    title = "наставник"
    parameter_name = "teacher"

    def lookups(self, request, model_admin):
        choices = [("none", "Не назначен")]
        for teacher in Teacher.objects.all():
            choices.append((str(teacher.pk), teacher.display_name()))
        return choices

    def queryset(self, request, queryset):
        if self.value() == "none":
            return queryset.filter(teacher__isnull=True)
        if self.value() and self.value().isdigit():
            return queryset.filter(teacher_id=self.value())
        return queryset


class DistrictFilter(admin.SimpleListFilter):
    title = "федеральный округ"
    parameter_name = "district__id__exact"
    district_lookup = "district_id"

    def lookups(self, request, model_admin):
        choices = []
        for district in District.objects.all():
            choices.append((str(district.pk), district.display_name()))
        return choices

    def queryset(self, request, queryset):
        if self.value() and self.value().isdigit():
            return queryset.filter(**{self.district_lookup: self.value()})
        return queryset


class TopicDistrictFilter(DistrictFilter):
    parameter_name = "region__district__id__exact"
    district_lookup = "region__district_id"


class RegionFilter(admin.SimpleListFilter):
    title = "регион"
    parameter_name = "region__id__exact"

    def lookups(self, request, model_admin):
        choices = []
        for region in Region.objects.all():
            choices.append((str(region.pk), region.display_name()))
        return choices

    def queryset(self, request, queryset):
        if self.value() and self.value().isdigit():
            return queryset.filter(region_id=self.value())
        return queryset


class RoleAdmin(admin.ModelAdmin):
    teacher_relation = None
    teacher_can_change = False

    def has_module_permission(self, request):
        return is_administration(request.user) or bool(self.teacher_relation and teacher_for_user(request.user))

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if is_administration(request.user):
            return queryset
        teacher = teacher_for_user(request.user)
        if teacher and self.teacher_relation:
            return queryset.filter(**{self.teacher_relation: teacher}).distinct()
        return queryset.none()

    def has_view_permission(self, request, obj=None):
        if is_administration(request.user):
            return True
        if not self.teacher_relation or not teacher_for_user(request.user):
            return False
        return obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_add_permission(self, request):
        return is_administration(request.user)

    def has_change_permission(self, request, obj=None):
        return is_administration(request.user) or (self.teacher_can_change and self.has_view_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return is_administration(request.user)

    def get_actions(self, request):
        if not is_administration(request.user):
            return {}
        return super().get_actions(request)

    def related_label(self, obj):
        if hasattr(obj, "display_name"):
            return obj.display_name()
        return str(obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field is not None:
            field.label_from_instance = self.related_label
        return field

    @admin.display(description="Проект", ordering="project__topic")
    def project_label(self, obj):
        if obj.project_id:
            return obj.project.display_name()
        return "Проект не указан"

    @admin.display(description="Наставник", ordering="teacher__full_name")
    def teacher_label(self, obj):
        if obj.teacher_id:
            return obj.teacher.display_name()
        return "Не назначен"

    @admin.display(description="Регион из справочника")
    def selected_region_label(self, obj):
        if obj.selected_region_id:
            return obj.selected_region.display_name()
        return "Не выбран"

    @admin.display(description="Основа выбранной темы")
    def topic_source_label(self, obj):
        if obj.topic_source_id:
            return obj.topic_source.display_name()
        return "Не указана"


class RegionInline(admin.TabularInline):
    model = Region
    fields = ["name", "active", "order"]
    extra = 0

    def has_view_permission(self, request, obj=None):
        return is_administration(request.user)

    def has_add_permission(self, request, obj=None):
        return is_administration(request.user)

    def has_change_permission(self, request, obj=None):
        return is_administration(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_administration(request.user)


@admin.register(District)
class DistrictAdmin(RoleAdmin):
    list_display = ["name", "active", "order"]
    list_filter = ["active"]
    search_fields = ["name"]
    fields = ["name", "active", "order"]
    inlines = [RegionInline]


@admin.register(Region)
class RegionAdmin(RoleAdmin):
    list_display = ["name", "district_label", "active", "order"]
    list_filter = ["active", DistrictFilter]
    search_fields = ["name", "district__name"]
    list_select_related = ["district"]
    fields = ["name", "district", "active", "order"]

    @admin.display(description="Федеральный округ", ordering="district__name")
    def district_label(self, obj):
        return obj.district.display_name()


@admin.register(RegionalTopic)
class RegionalTopicAdmin(RoleAdmin):
    list_display = ["title", "region_label", "subject", "product_type", "hobby", "active"]
    list_filter = ["active", TopicDistrictFilter, RegionFilter, "subject", "product_type", "hobby"]
    search_fields = ["title", "problem", "region__name", "region__district__name"]
    list_select_related = ["region", "region__district"]
    fields = ["title", "region", "problem", "subject", "product_type", "hobby", "active", "order", "updated_at"]
    readonly_fields = ["updated_at"]

    @admin.display(description="Регион", ordering="region__name")
    def region_label(self, obj):
        return obj.region.display_name()


@admin.register(Student)
class StudentAdmin(RoleAdmin):
    teacher_relation = "projects__teacher"
    list_display = ["student_label", "grade", "created_at"]
    search_fields = ["full_name", "=max_user_id"]
    list_filter = ["grade"]

    @admin.display(description="Ученик", ordering="full_name")
    def student_label(self, obj):
        return obj.display_name()

    def get_readonly_fields(self, request, obj=None):
        if is_administration(request.user):
            return ["created_at"]
        fields = []
        for field in self.model._meta.fields:
            fields.append(field.name)
        return fields


@admin.register(Teacher)
class TeacherAdmin(RoleAdmin):
    list_display = ["full_name", "subject", "max_link", "projects_link", "active"]
    list_filter = ["active", "subject"]
    search_fields = ["full_name", "user__username"]

    @admin.display(description="Проекты")
    def projects_link(self, obj):
        query = urlencode({"teacher": obj.pk, "project_status": "all"})
        return format_html('<a href="{}?{}">Проекты</a>', reverse("admin:bot_project_changelist"), query)


@admin.register(Project)
class ProjectAdmin(RoleAdmin):
    teacher_relation = "teacher"
    teacher_can_change = True
    list_display = ["student_label", "grade", "topic_label", "current_stage", "review_status", "teacher_label", "progress", "last_student_activity_at", "stage_changed_at", "paused"]
    list_select_related = ["student", "teacher", "selected_region", "topic_source"]
    search_fields = ["student__full_name", "topic"]
    ordering = ["-last_student_activity_at", "-stage_changed_at"]
    fields = [
        "student", "teacher", "topic", "topic_source", "current_stage", "stage_changed_at", "paused", "review_status",
        "progress", "last_student_activity_at", "subject", "product_type", "hobby", "district_label", "region", "selected_region",
        "goal", "accepted_tasks", "full_checklist", "literature", "project_files", "teacher_feedback",
        "status", "submitted_at", "defended_at", "step", "return_step", "revision", "defense_attempt",
        "defense_ends_at", "defense_questions", "defense_notified_at", "created_at", "updated_at",
    ]

    def get_list_filter(self, request):
        filters = ["stage", "student__grade", "subject", "review_status", ProjectStatusFilter]
        if is_administration(request.user):
            filters.append(TeacherFilter)
        return filters

    def editable_fields(self, request, obj=None):
        editable = {"teacher_feedback"}
        if obj is None or obj.status == "active":
            editable.add("review_status")
        if is_administration(request.user):
            editable.add("teacher")
            if obj is None:
                editable.add("student")
        return editable

    def get_fields(self, request, obj=None):
        editable = self.editable_fields(request, obj)
        labels = {"student": "student_label", "teacher": "teacher_label", "selected_region": "selected_region_label", "topic_source": "topic_source_label"}
        fields = []
        for field in self.fields:
            if field not in editable and field in labels:
                fields.append(labels[field])
            else:
                fields.append(field)
        return fields

    def get_readonly_fields(self, request, obj=None):
        editable = self.editable_fields(request, obj)
        fields = []
        for field in self.get_fields(request, obj):
            if field not in editable:
                fields.append(field)
        return fields

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not is_administration(request.user):
            teacher = teacher_for_user(request.user)
            if db_field.name == "teacher":
                kwargs["queryset"] = Teacher.objects.none()
                if teacher:
                    kwargs["queryset"] = Teacher.objects.filter(pk=teacher.pk)
            if db_field.name == "student":
                kwargs["queryset"] = Student.objects.none()
                if teacher:
                    kwargs["queryset"] = Student.objects.filter(projects__teacher=teacher).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Ученик", ordering="student__full_name")
    def student_label(self, obj):
        return obj.student_name

    @admin.display(description="Класс", ordering="student__grade")
    def grade(self, obj):
        return obj.student.grade

    @admin.display(description="Федеральный округ")
    def district_label(self, obj):
        return obj.district_name

    @admin.display(description="Тема", ordering="topic")
    def topic_label(self, obj):
        return obj.topic or "Ещё не выбрана"

    @admin.display(description="Стадия", ordering="stage")
    def current_stage(self, obj):
        return obj.stage_label

    @admin.display(description="Чек-лист")
    def progress(self, obj):
        return obj.checklist_progress

    @admin.display(description="Состояние")
    def paused(self, obj):
        if obj.step == "pause":
            return "Пауза"
        return "В работе"

    @admin.display(description="Принятые задачи")
    def accepted_tasks(self, obj):
        if not obj.tasks:
            return "Ещё не приняты"
        tasks = []
        for task in obj.tasks:
            tasks.append((task,))
        return format_html('<ol>{}</ol>', format_html_join("", "<li>{}</li>", tasks))

    @admin.display(description="Полный чек-лист")
    def full_checklist(self, obj):
        if not obj.checklist:
            return "Нет плана"
        items = []
        for item in obj.checklist:
            if isinstance(item, dict):
                mark = "—"
                if item.get("done"):
                    mark = "✓"
                items.append((mark, item.get("text", "")))
        return format_html('<ul>{}</ul>', format_html_join("", "<li>{} {}</li>", items))

    @admin.display(description="Материалы ученика")
    def project_files(self, obj):
        rows = []
        for item in obj.files.all():
            if item.stored_file:
                rows.append((reverse("project_file", args=[item.pk]), item.original_name or "Скачать файл"))
            elif item.external_url and urlparse(item.external_url).scheme in ("http", "https"):
                rows.append((item.external_url, item.original_name or item.external_url))
        if rows:
            return format_html_join("<br>", '<a href="{}">{}</a>', rows)
        return "Материалы не загружены"

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            previous = None
            if change:
                previous = self.get_queryset(request).select_for_update().filter(pk=obj.pk).first()
            if change and previous is None:
                raise PermissionDenied
            changed_review = previous is not None and (previous.teacher_feedback != obj.teacher_feedback or (previous.status == "active" and previous.review_status != obj.review_status))
            if previous is not None:
                allowed = ["teacher_feedback", "updated_at"]
                if previous.status == "active":
                    allowed.append("review_status")
                else:
                    obj.review_status = previous.review_status
                if is_administration(request.user):
                    allowed.append("teacher")
                obj.save(update_fields=allowed)
            else:
                super().save_model(request, obj, form, change)
            obj.refresh_from_db()
            if changed_review:
                from .logic import queue_review_notification

                queue_review_notification(obj)


@admin.register(ProjectFile)
class ProjectFileAdmin(RoleAdmin):
    teacher_relation = "project__teacher"
    list_display = ["original_name", "project_label", "kind", "download_link", "created_at"]
    list_select_related = ["project__student", "project__teacher"]
    search_fields = ["original_name", "project__student__full_name", "project__topic"]
    fields = ["project_label", "kind", "original_name", "download_link", "created_at"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    @admin.display(description="Открыть материал")
    def download_link(self, obj):
        if obj.stored_file:
            return format_html('<a href="{}">Скачать файл</a>', reverse("project_file", args=[obj.pk]))
        if obj.external_url and urlparse(obj.external_url).scheme in ("http", "https"):
            return format_html('<a href="{}">Открыть ссылку</a>', obj.external_url)
        return "Материал недоступен"


class MaterialForm(forms.ModelForm):
    remove_file = forms.BooleanField(label="Убрать загруженный файл", required=False)

    class Meta:
        model = Material
        fields = "__all__"
        widgets = {"file": forms.FileInput()}

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("remove_file"):
            if self.files.get("file"):
                self.add_error("file", "Выберите одно действие: загрузить новый файл или убрать старый.")
            else:
                cleaned_data["file"] = False
        return cleaned_data


@admin.register(Material)
class MaterialAdmin(RoleAdmin):
    form = MaterialForm
    list_display = ["title", "code", "download_link", "active"]
    list_filter = ["active"]
    search_fields = ["title", "code"]
    readonly_fields = ["download_link"]
    fields = ["code", "title", "file", "download_link", "remove_file", "external_url", "description", "active"]

    @admin.display(description="Загруженный файл")
    def download_link(self, obj):
        if obj.pk and obj.file:
            return format_html('<a href="{}">Скачать файл</a>', reverse("material_file", args=[obj.pk]))
        return "Файл не загружен"


@admin.register(Prompt)
class PromptAdmin(RoleAdmin):
    list_display = ["code", "version", "active"]
    list_filter = ["active"]
    search_fields = ["code", "instruction"]

    def save_model(self, request, obj, form, change):
        if change:
            previous = Prompt.objects.get(pk=obj.pk)
            if previous.instruction != obj.instruction:
                obj.version = max(obj.version, previous.version + 1)
        super().save_model(request, obj, form, change)


@admin.register(BotMessage)
class BotMessageAdmin(RoleAdmin):
    list_display = ["max_chat_id", "project_label", "updated_at"]
    fields = ["id", "max_chat_id", "message_id", "project_label", "payload", "version", "page", "updated_at"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False


admin.site.site_header = "Навигатор проектов Нави"
admin.site.site_title = "Нави"
admin.site.index_title = "Ученики и проекты"
