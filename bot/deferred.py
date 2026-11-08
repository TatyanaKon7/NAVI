from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Project
from .texts import SUBJECTS


def park_project(project):
    from . import logic

    if project.step == "start_reset_confirm":
        state = logic.dialog_state(project)
        project.step = state["step"]
        project.return_step = state["return_step"]
        project.pending_changes = state["pending_changes"]
    project.pending_changes["deferred_status"] = project.status
    if project.defense_ends_at is not None:
        project.pending_changes["deferred_timer_seconds"] = max(0, (project.defense_ends_at - timezone.now()).total_seconds())
        project.defense_ends_at = None
    project.status = "deferred"
    project.save()
    project.jobs.filter(kind__in=["send", "page"], status__in=["pending", "running"]).update(
        status="cancelled", error_text="project_deferred", finished_at=timezone.now(), locked_at=None,
    )


def defer_project(project):
    with transaction.atomic():
        project.refresh_from_db()
        if project.status == "deferred":
            return Project.objects.filter(student=project.student, status__in=["active", "defended"]).first()
        if project.status not in ("active", "defended"):
            return None
        park_project(project)
        return Project.objects.create(
            student=project.student, last_student_activity_at=project.last_student_activity_at,
            revision=project.revision + 1, pending_changes={"restart_profile": True},
        )


def resume_project(current, project_id):
    from . import logic

    with transaction.atomic():
        current.refresh_from_db()
        target = Project.objects.filter(pk=project_id, student=current.student, status="deferred").first()
        if target is None or current.status not in ("active", "defended"):
            return None
        if logic.project_has_started(current):
            park_project(current)
        else:
            current.status = "archived"
            current.revision += 1
            current.save()
            current.jobs.filter(status__in=["pending", "running"]).exclude(kind="event").update(
                status="cancelled", error_text="project_switched", finished_at=timezone.now(), locked_at=None,
            )
        status = target.pending_changes.pop("deferred_status", "active")
        target.status = "active"
        if status in ("active", "defended"):
            target.status = status
        seconds = target.pending_changes.pop("deferred_timer_seconds", None)
        if isinstance(seconds, (int, float)) and type(seconds) is not bool:
            target.defense_ends_at = timezone.now() + timedelta(seconds=max(0, seconds))
        target.last_student_activity_at = timezone.now()
        target.save()
        return target


def show_deferred(current):
    from . import logic

    projects = list(Project.objects.filter(student=current.student, status="deferred").order_by("-updated_at", "-pk"))
    options = []
    for project in projects:
        title = project.topic or ("Проект: " + SUBJECTS.get(project.subject, "анкета"))
        label = title[:65] + " · " + timezone.localtime(project.created_at).strftime("%d.%m")
        options.append((label, f"resume_deferred:{project.pk}"))
    options.append(("Назад", "current"))
    text = "Отложенных проектов пока нет."
    if projects:
        text = "Отложенные проекты. Выбери проект, чтобы продолжить."
    logic.send(current, text, logic.rows(current, options))
