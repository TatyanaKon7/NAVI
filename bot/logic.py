from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from . import topics
from .ai import AIError
from .models import BotJob, District, Material, Project, ProjectFile, Prompt, Region, Student
from .texts import HOBBIES, MESSAGES, PRODUCTS, REVIEWS, STAGES, STEP_STAGES, SUBJECTS


NO_TOPICS_TEXT = "Для твоего региона пока нет подходящих тем. Анкета сохранена. Попроси учителя добавить темы или измени анкету."
STALE_TOPICS_TEXT = "Темы изменились. Подбери их заново. Анкета сохранена."
START_RESET_OPTIONS = [("Да, начать заново", "confirm_start_reset"), ("Нет, продолжить работу", "cancel_start_reset"), ("Отложить проект", "defer_project")]


def button(project, text, action):
    global_actions = ("project", "materials", "pause", "revise", "restart", "edit", "current", "continue", "deferred")
    scope = project.step
    if action in global_actions or action.startswith(("file:", "page:")):
        scope = "*"
    return {"text": text, "payload": f"p:{project.pk}:{project.revision}:{scope}:{action}"}


def rows(project, options):
    buttons = []
    for text, action in options:
        buttons.append([button(project, text, action)])
    return buttons


def send(project, text, buttons=None, chat_id=None, file_path=None, deduplication_key=None, notify=False, relocate=False):
    from .messages import queue_message

    if project.step == "start_reset_confirm" and (chat_id is None or chat_id == project.student.max_chat_id):
        warning = MESSAGES["start_reset_confirm"]
        if warning not in text:
            text += "\n\n" + warning
        buttons = rows(project, START_RESET_OPTIONS)
    return queue_message(project, text, buttons=buttons, chat_id=chat_id, file_path=file_path, deduplication_key=deduplication_key, notify=notify, relocate=relocate)


def dialog_state(project):
    if project.step == "start_reset_confirm":
        return deepcopy(project.pending_changes["start_reset_state"])
    return {"step": project.step, "return_step": project.return_step, "pending_changes": deepcopy(project.pending_changes)}


def store_dialog_state(project, state):
    if project.step == "start_reset_confirm":
        project.pending_changes = {"start_reset_state": state}
    else:
        project.step = state["step"]
        project.return_step = state["return_step"]
        project.pending_changes = state["pending_changes"]


def effective_step(project):
    state = dialog_state(project)
    step = state["step"]
    previous_return = state["return_step"]
    if step in ("restart_confirm", "edit_confirm"):
        step = state["pending_changes"].get("previous_step", "")
        previous_return = state["pending_changes"].get("previous_return_step", "")
    if step in ("pause", "materials"):
        return previous_return
    return step


def set_step(project, step, keep_temporary=True):
    state = dialog_state(project)
    if keep_temporary and state["step"] in ("restart_confirm", "edit_confirm"):
        state["pending_changes"] = dict(state["pending_changes"], previous_step=step)
    elif keep_temporary and state["step"] in ("pause", "materials") and state["return_step"]:
        state["return_step"] = step
    else:
        state["step"] = step
        stage = STEP_STAGES.get(step)
        if stage and project.stage != stage:
            project.stage = stage
            project.stage_changed_at = timezone.now()
    store_dialog_state(project, state)
    project.save()


def show_step(project, prefix="", extra_buttons=None, notify=False, relocate=False):
    step = project.step
    options = []
    text = MESSAGES.get(step, "Выбери действие кнопкой.")
    if step == "start":
        options = [("Да", "yes"), ("Нет", "no")]
        if Project.objects.filter(student=project.student, status="deferred").exists():
            options.append(("Отложенные проекты", "deferred"))
    elif step == "grade":
        options = [("9 класс", "grade:9")]
    elif step == "district":
        for district in District.objects.filter(active=True):
            options.append((district.name, f"district:{district.code}"))
    elif step == "region":
        for region in Region.objects.filter(district__code=project.district, district__active=True, active=True):
            options.append((region.name, f"region_id:{region.pk}"))
        options.append(("Другой регион", "other_region"))
    elif step == "knows_project":
        options = [("Да", "yes"), ("Нет", "no"), ("Помощь с оформлением", "materials")]
    elif step in ("project_info", "structure_view"):
        options = [("Далее", "next")]
    elif step == "subject":
        for code, label in SUBJECTS.items():
            options.append((label, f"subject:{code}"))
    elif step == "product":
        for code, label in PRODUCTS.items():
            options.append((label, f"product:{code}"))
    elif step == "hobby":
        for code, label in HOBBIES.items():
            options.append((label, f"hobby:{code}"))
    elif step == "topics":
        if not topics.catalog_for_project(project):
            text = NO_TOPICS_TEXT
            options = [("Попробовать ещё раз", "retry")]
        elif not project.jobs.filter(kind="ai", status__in=["pending", "running"], project_revision=project.revision, payload__code="topics").exists():
            text = "Темы нужно подобрать заново. Нажми «Попробовать ещё раз»; данные анкеты сохранены."
            options = [("Попробовать ещё раз", "retry")]
    elif step == "choose_topic":
        if not project.topic:
            try:
                topics.offered_catalog(project)
            except Exception as error:
                if not isinstance(error, AIError):
                    raise
                reset_topic_selection(project)
                show_step(project, prefix + STALE_TOPICS_TEXT + "\n\n", extra_buttons=extra_buttons, notify=notify, relocate=relocate)
                return
        descriptions = []
        for index, item in enumerate(project.topics):
            descriptions.append(f"{index + 1}. {item['title']}\n{item['description']}")
            options.append((str(index + 1), f"topic:{index}"))
        text = "\n\n".join(descriptions) + "\n\n" + text
    elif step in ("structure", "tasks_ready", "defense_ready", "defense_repeat", "defended"):
        negative = "Нет"
        if step == "defense_ready":
            negative = "Позже"
        options = [("Да", "yes"), (negative, "no")]
    elif step == "goal":
        if project.goal_draft:
            text += "\n\nТвоя формулировка:\n" + project.goal_draft
        if project.goal_feedback and not project.goal_feedback.get("accepted"):
            text += "\n\n" + feedback_text(project.goal_feedback)
        if project.goal_feedback.get("example"):
            options = [("Использовать этот вариант", "use_goal_example")]
    elif step == "tasks":
        if project.tasks_draft:
            text += "\n\nТвой список:\n" + project.tasks_draft
        if project.tasks_feedback and not project.tasks_feedback.get("accepted"):
            text += "\n\n" + feedback_text(project.tasks_feedback)
        if project.tasks_feedback.get("example_tasks"):
            options = [("Использовать этот вариант", "use_tasks_example")]
    elif step == "work":
        text = checklist_text(project) + "\n\nОтмечай выполненные пункты. Сверяй работу с правилами оформления и критериями."
        for index, item in enumerate(project.checklist):
            mark = "□"
            if item.get("done"):
                mark = "✓"
            options.append((f"{mark} {index + 1}", f"check:{index}"))
        options.append(("Отправить работу", "files"))
        options.extend([("Правила оформления", "material:formatting"), ("Критерии оценивания", "material:assessment")])
    elif step == "files":
        text += f"\nСохранено материалов: {project.files.count()}."
        options = [("Готово, отправить учителю", "submit"), ("К чек-листу", "work")]
    elif step == "defense_timer":
        options = [("Остановить", "stop")]
    elif step == "defense_answer":
        questions = []
        for index, question in enumerate(project.defense_questions):
            questions.append(f"{index + 1}. {question}")
        text += "\n\n" + "\n".join(questions)
        options = [("Ответил", "answered")]
    elif step == "pause":
        options = [("Продолжить", "continue"), ("Начать заново", "restart")]
    elif step == "materials":
        options = [("Структура проекта", "material:structure"), ("Правила оформления", "material:formatting"), ("Критерии оценивания", "material:assessment"), ("Назад", "back")]
    elif step in ("restart_confirm", "edit_confirm"):
        options = [("Да, создать новый проект", "confirm_restart"), ("Отмена", "cancel")]
    elif step == "start_reset_confirm":
        options = START_RESET_OPTIONS
    elif step == "complete":
        options = [("Мой проект", "project"), ("Начать заново", "restart")]
    if step in ("topics", "literature", "goal_check", "tasks_check", "checklist", "defense_prepare", "mentor_wait"):
        code = step
        if step == "defense_prepare":
            code = "defense_questions"
        elif step == "mentor_wait":
            code = "mentor_help"
        failed = project.jobs.filter(kind="ai", status="error", project_revision=project.revision, payload__code=code).exists()
        retry_exists = False
        for label, action in options:
            if action == "retry":
                retry_exists = True
        if failed and not retry_exists:
            options.append(("Попробовать ещё раз", "retry"))
    buttons = rows(project, options)
    if extra_buttons and step != "start_reset_confirm":
        buttons = extra_buttons + buttons
    send(project, prefix + text, buttons, notify=notify, relocate=relocate)


def checklist_text(project):
    if not project.checklist:
        return "Нет плана."
    done = 0
    lines = []
    for index, item in enumerate(project.checklist):
        mark = "□"
        if item.get("done"):
            done += 1
            mark = "✓"
        lines.append(f"{mark} {index + 1}. {item['text']}")
    return f"Выполнено {done} из {len(project.checklist)}\n" + "\n".join(lines)


def feedback_text(feedback):
    parts = [feedback.get("feedback", "")]
    parts.extend(feedback.get("suggestions", []))
    if feedback.get("example"):
        parts.append("Пример: " + feedback["example"])
    if feedback.get("example_tasks"):
        parts.append("Пример:\n" + "\n".join(feedback["example_tasks"]))
    nonempty = []
    for part in parts:
        if part:
            nonempty.append(part)
    return "\n".join(nonempty)


def literature_text(result):
    if not result:
        return "Литература ещё не подобрана."
    parts = []
    for label, key in (("Книги", "books"), ("Статьи и публикации", "articles")):
        parts.append(label + ":")
        for item in result.get(key, []):
            fields = []
            for field in ("author", "title", "year", "publication"):
                if item.get(field):
                    fields.append(str(item[field]))
            parts.append(" — ".join(fields))
        if not result.get(key):
            parts.append("Не хватает надёжных сведений об источниках.")
    if result.get("search_queries"):
        parts.append("Попробуй поискать:\n" + "\n".join(result["search_queries"]))
    if result.get("advice"):
        parts.append("Совет: " + result["advice"])
    parts.append("Проверь названия и выходные данные перед включением в список литературы.")
    return "\n".join(parts)


def project_text(project):
    teacher = "Учитель ещё не назначен"
    if project.teacher_id:
        teacher = project.teacher.full_name
    stage = STAGES.get(project.stage, project.stage)
    if project.stage == "submission" and project.review_status == "needs_revision":
        stage = "Дорабатывает материалы"
    task_lines = []
    for index, item in enumerate(project.tasks):
        task_lines.append(f"{index + 1}. {item}")
    tasks = "Пока не приняты"
    if task_lines:
        tasks = "\n".join(task_lines)
    files = []
    for item in project.files.all():
        name = item.original_name
        if item.external_url:
            name = f"{name}: {item.external_url}"
        files.append(name)
    student_name = project.student.full_name
    if not student_name:
        student_name = "Имя ещё не указано"
    topic = project.topic
    if not topic:
        topic = "Ещё не выбрана"
    goal = project.goal
    if not goal:
        goal = "Пока не принята"
    materials = "Пока не добавлены"
    if files:
        materials = "\n".join(files)
    text = f"Ученик: {student_name}\nТема: {topic}\nСтадия: {stage}"
    text += "\nПроверка: " + REVIEWS.get(project.review_status, project.review_status)
    text += f"\nНаставник: {teacher}\nЦель: {goal}\nЗадачи:\n{tasks}"
    text += "\n\n" + checklist_text(project)
    text += "\n\nМатериалы:\n" + materials
    if project.teacher_feedback:
        text += f"\nЗамечание учителя: {project.teacher_feedback}"
    if project.literature:
        text += "\n\nЛитература:\n" + literature_text(project.literature)
    return text


def show_project(project):
    buttons = []
    for item in project.files.filter(stored_file__isnull=False).exclude(stored_file=""):
        buttons.append([button(project, f"Файл: {item.original_name[:50]}", f"file:{item.pk}")])
    buttons += rows(project, [("Вернуться к работе", "current")])
    send(project, project_text(project), buttons)


def ai_data(project, code, payload=None):
    district = project.district_name
    state = dialog_state(project)
    district_name = district
    if district and "федеральный округ" not in district.lower() and district != project.district:
        district_name = f"{district} федеральный округ"
    step = effective_step(project)
    if state["step"] in ("mentor_question", "mentor_wait"):
        step = state["return_step"]
    data = {
        "grade": project.student.grade,
        "district": district_name,
        "region": project.region,
        "subject": SUBJECTS.get(project.subject, project.subject),
        "product_type": PRODUCTS.get(project.product_type, project.product_type),
        "hobby": HOBBIES.get(project.hobby, project.hobby),
        "topic": project.topic,
        "goal": project.goal,
        "goal_draft": project.goal_draft,
        "tasks": project.tasks,
        "tasks_draft": project.tasks_draft,
        "step": step,
    }
    if code == "mentor_help":
        if not payload:
            payload = {}
        data["question"] = payload.get("question", state["pending_changes"].get("question", ""))
    elif code == "topics":
        data["approved_topics"] = topics.catalog_for_project(project)
    return data


DAILY_LIMIT = 30


def queue_ai(project, code, extra=None):
    data = ai_data(project, code, extra)
    if code == "topics" and not data["approved_topics"]:
        send(project, NO_TOPICS_TEXT, rows(project, [("Попробовать ещё раз", "retry")]))
        return False
    if project.jobs.filter(kind="ai", project_revision=project.revision, status__in=["pending", "running"], payload__code=code).exists():
        send(project, "Я уже готовлю ответ. Дождись его: повторный запрос не нужен.")
        return False
    count = BotJob.objects.filter(project__student=project.student, kind="ai_usage", created_at__date=timezone.localdate()).count()
    if count >= DAILY_LIMIT:
        send(project, "Сегодня достигнут лимит подсказок. Твои данные сохранены. Продолжить можно завтра; проект и материалы доступны.", rows(project, [("Попробовать ещё раз", "retry")]))
        return False
    prompt = Prompt.objects.filter(code=code, active=True).first()
    if not prompt:
        send(project, "Не получилось получить ответ. Твой текст сохранён. Попробовать ещё раз?", rows(project, [("Попробовать ещё раз", "retry")]))
        return False
    BotJob.objects.create(project=project, kind="ai", payload={"code": code, "data": data, "instruction": prompt.instruction}, project_revision=project.revision, prompt_version=prompt.version)
    return True


def start_ai(project, code, step, extra=None):
    set_step(project, step)
    if code == "topics":
        if queue_ai(project, code, extra):
            show_step(project)
        return
    show_step(project)
    queue_ai(project, code, extra)


def reset_topic_selection(project):
    project.topics = []
    project.topic_source = None
    set_step(project, "topics")


def validate_topic_job(job):
    if job.payload.get("code") == "topics":
        if not job.project:
            raise AIError().setup("ai_catalog_changed")
        data = job.payload.get("data")
        if not isinstance(data, dict):
            raise AIError().setup("ai_catalog_changed")
        return topics.validate_catalog(job.project, data.get("approved_topics"))


def material(project, code):
    item = Material.objects.filter(code=code, active=True).first()
    action = "current"
    if project.step == "materials":
        action = "back"
    back = rows(project, [("Назад", action)])
    if not item:
        send(project, "Материал ещё не настроен. Попроси учителя добавить утверждённый файл.", back)
    else:
        text = item.title
        if item.description:
            text += "\n" + item.description
        if item.file:
            send(project, text, back, file_path=item.file.path)
        elif item.external_url:
            buttons = [[{"text": "Открыть материал", "url": item.external_url}]] + back
            send(project, text, buttons)
        else:
            send(project, "Материал ещё не настроен. Попроси учителя добавить утверждённый файл.", back)


def cancel_attempt(project):
    project.defense_ends_at = None
    project.defense_notified_at = None
    project.save()
    project.jobs.filter(status__in=["pending", "running"], deduplication_key__startswith=f"defense:{project.pk}:").update(status="cancelled", finished_at=timezone.now())


def new_project(project):
    student = project.student
    old_revision = project.revision
    project.status = "archived"
    project.defense_ends_at = None
    project.revision += 1
    project.save()
    project.jobs.filter(status__in=["pending", "running"]).exclude(kind="event").update(status="cancelled", finished_at=timezone.now())
    new = Project.objects.create(student=student, teacher=project.teacher, revision=old_revision + 1, last_student_activity_at=project.last_student_activity_at)
    step = "student_name"
    if student.full_name:
        step = "grade"
    set_step(new, step, keep_temporary=False)
    show_step(new)
    return new


def restart_session(project):
    project.status = "archived"
    project.defense_ends_at = None
    project.revision += 1
    project.save()
    project.jobs.filter(status__in=["pending", "running"]).exclude(kind="event").update(status="cancelled", finished_at=timezone.now())
    return Project.objects.create(
        student=project.student, revision=project.revision,
        last_student_activity_at=project.last_student_activity_at,
        pending_changes={"restart_profile": True},
    )


def project_has_started(project):
    fields = ("district", "region", "selected_region_id", "subject", "product_type", "hobby", "topics", "topic", "topic_source_id", "literature", "goal_draft", "goal", "goal_feedback", "tasks_draft", "tasks", "tasks_feedback", "checklist", "teacher_id", "teacher_feedback", "defense_questions", "defense_ends_at", "defense_attempt")
    if project.step != "start" or project.return_step:
        return True
    for key in project.pending_changes:
        if key != "restart_profile":
            return True
    if project.status != "active" or project.stage != "questionnaire" or project.review_status != "not_submitted":
        return True
    for field in fields:
        if getattr(project, field):
            return True
    return project.files.exists()


def ask_start_reset(project):
    if project.step != "start_reset_confirm":
        state = dialog_state(project)
        project.step = "start_reset_confirm"
        project.return_step = ""
        project.pending_changes = {"start_reset_state": state}
        project.save(update_fields=["step", "return_step", "pending_changes", "updated_at"])
    show_step(project, relocate=True)


def restore_start_reset_state(project):
    state = dialog_state(project)
    project.step = state["step"]
    project.return_step = state["return_step"]
    project.pending_changes = state["pending_changes"]
    project.save()


def event_values(payload):
    message = payload.get("message")
    if not message:
        message = {}
    callback = payload.get("callback")
    if not callback:
        callback = {}
    user = callback.get("user")
    if not user:
        user = message.get("sender")
    if not user:
        user = payload.get("user")
    if not user:
        user = {}
    recipient = message.get("recipient")
    if not recipient:
        recipient = {}
    user_id = user.get("user_id")
    if not user_id:
        user_id = payload.get("user_id")
    chat_id = recipient.get("chat_id")
    if not chat_id:
        chat_id = payload.get("chat_id")
    body = message.get("body")
    if not body:
        body = {}
    text = body.get("text")
    if not text:
        text = ""
    attachments = body.get("attachments")
    if not attachments:
        attachments = []
    return user_id, chat_id, text.strip(), attachments, callback


def action_from_text(project, text):
    if project.step == "start_reset_confirm":
        if text.casefold() in ("да", "да, начать заново"):
            return "confirm_start_reset"
        if text.casefold() in ("нет", "нет, продолжить работу"):
            return "cancel_start_reset"
    commands = {
        "да": "yes", "нет": "no", "позже": "no", "далее": "next", "дальше": "next",
        "продолжить": "continue", "начать заново": "restart", "мой проект": "project",
        "помощь": "materials", "помощь с оформлением": "materials", "спросить нави": "mentor",
        "назад": "back", "вернуться к работе": "current", "пауза": "pause", "отмена": "cancel",
        "изменить анкету": "edit", "да, создать новый проект": "confirm_restart",
        "отправить работу": "files", "готово, отправить учителю": "submit", "отправить учителю": "submit",
        "к чек-листу": "work", "остановить": "stop", "ответил": "answered", "доработать": "revise",
        "попробовать ещё раз": "retry", "другой регион": "other_region",
        "/deferred": "deferred", "отложенные проекты": "deferred",
        "/defer": "defer_project", "отложить проект": "defer_project",
        "/project": "project", "/help": "materials", "/pause": "pause", "/continue": "continue",
    }
    if text.lower() in commands:
        return commands[text.lower()]
    if project.step == "grade" and text in ("9", "9 класс"):
        return "grade:9"
    if project.step == "district":
        for district in District.objects.filter(active=True):
            if text.lower() == district.name.lower():
                return f"district:{district.code}"
    values = {"subject": SUBJECTS, "product": PRODUCTS, "hobby": HOBBIES}
    if project.step in values:
        for code, label in values[project.step].items():
            if text.lower() == label.lower():
                return f"{project.step}:{code}"
    if project.step == "region":
        region = topics.matching_region(project.district, text, selectable=True)
        if region:
            return f"region_id:{region.pk}"
    if project.step == "choose_topic":
        for index, item in enumerate(project.topics):
            if text == str(index + 1) or text == item["title"]:
                return f"topic:{index}"
    if text == "Использовать этот вариант":
        if project.step == "goal":
            return "use_goal_example"
        return "use_tasks_example"
    return ""


def handle_event(event):
    payload = event.payload
    user_id, chat_id, text, attachments, callback = event_values(payload)
    if not user_id:
        return
    if not chat_id:
        known_student = Student.objects.filter(max_user_id=user_id).first()
        if known_student:
            chat_id = known_student.max_chat_id
        else:
            if callback.get("callback_id"):
                BotJob.objects.create(kind="callback", payload={"callback_id": callback["callback_id"]})
            return
    student, created = Student.objects.get_or_create(max_user_id=user_id, defaults={"max_chat_id": chat_id})
    if student.max_chat_id != chat_id:
        student.max_chat_id = chat_id
        student.save(update_fields=["max_chat_id"])
    project = Project.objects.filter(student=student, status__in=["active", "defended"]).first()
    fresh = project is None
    if fresh:
        project = Project.objects.create(student=student)
    event.project = project
    event.save(update_fields=["project"])
    project.last_student_activity_at = timezone.now()
    project.save(update_fields=["last_student_activity_at", "updated_at"])
    if callback.get("callback_id"):
        BotJob.objects.create(event=event, kind="callback", payload={"callback_id": callback["callback_id"]})
    if not callback and text in ("/start", "/restart"):
        if not fresh and project_has_started(project):
            ask_start_reset(project)
        else:
            if fresh:
                project.pending_changes = {"restart_profile": True}
                project.save(update_fields=["pending_changes"])
            show_step(project, relocate=True)
        return
    if event.event_type == "bot_started":
        if fresh:
            project.pending_changes = {"restart_profile": True}
            project.save(update_fields=["pending_changes"])
        show_step(project, relocate=True)
        return
    if callback:
        value = str(callback.get("payload") or "")
        pieces = value.split(":", 4)
        if len(pieces) != 5 or pieces[0] != "p" or pieces[1] != str(project.pk) or pieces[2] != str(project.revision) or pieces[3] not in ("*", project.step):
            show_step(project, "Эта кнопка устарела. Выбери действие на текущем шаге.\n\n")
            return
        action = pieces[4]
        if pieces[3] == "*" and action not in ("project", "materials", "pause", "revise", "restart", "edit", "current", "continue", "deferred") and not action.startswith(("file:", "page:")):
            show_step(project, "Эта кнопка устарела. Выбери действие на текущем шаге.\n\n")
            return
    else:
        action = action_from_text(project, text)
    handle_answer(project, action, text, attachments, event)


def handle_answer(project, action, text="", attachments=None, event=None):
    attachments = attachments or []
    if project.step == "start_reset_confirm":
        if action == "confirm_start_reset":
            restore_start_reset_state(project)
            new = restart_session(project)
            if event:
                event.project = new
                event.save(update_fields=["project"])
            show_step(new, relocate=True)
        elif action == "cancel_start_reset":
            restore_start_reset_state(project)
            show_step(project)
        elif action == "defer_project":
            from .deferred import defer_project

            restore_start_reset_state(project)
            home = defer_project(project)
            if event:
                event.project = home
                event.save(update_fields=["project"])
            show_step(home, "Проект отложен. К нему можно вернуться через «Отложенные проекты».\n\n", relocate=True)
        else:
            show_step(project)
        return
    if action == "deferred":
        from .deferred import show_deferred

        show_deferred(project)
        return
    if action == "defer_project":
        from .deferred import defer_project

        home = defer_project(project)
        if event:
            event.project = home
            event.save(update_fields=["project"])
        show_step(home, "Проект отложен. К нему можно вернуться через «Отложенные проекты».\n\n", relocate=True)
        return
    if action.startswith("resume_deferred:") and action[16:].isdigit():
        from .deferred import resume_project, show_deferred

        resumed = resume_project(project, int(action[16:]))
        if resumed:
            if event:
                event.project = resumed
                event.save(update_fields=["project"])
            show_step(resumed, "Продолжаем отложенный проект.\n\n", relocate=True)
        else:
            show_deferred(project)
        return
    if action.startswith("page:"):
        from .messages import handle_page

        if handle_page(project, action):
            return
    if action.startswith("material:") and action[9:] in ("structure", "formatting", "assessment"):
        material(project, action[9:])
        return
    if action == "project":
        show_project(project)
        return
    if action.startswith("file:"):
        item = None
        if action[5:].isdigit():
            item = project.files.filter(pk=action[5:]).first()
        if item and item.stored_file:
            send(project, item.original_name, rows(project, [("Вернуться к работе", "current")]), file_path=item.stored_file.path)
        else:
            send(project, "Этот файл недоступен.")
        return
    if action == "current":
        show_step(project)
        return
    if action == "restart" or action == "edit":
        if action == "edit" and not project.topic:
            project.revision += 1
            project.topics = []
            project.topic_source = None
            project.jobs.filter(status__in=["pending", "running"], kind="ai").update(status="cancelled", finished_at=timezone.now())
            project.return_step = ""
            set_step(project, "grade", keep_temporary=False)
            show_step(project)
        else:
            project.pending_changes = {"previous_step": project.step, "previous_return_step": project.return_step}
            project.step = "restart_confirm"
            if action == "edit":
                project.step = "edit_confirm"
            project.save()
            show_step(project)
        return
    if project.step in ("restart_confirm", "edit_confirm"):
        if action == "confirm_restart":
            new_project(project)
        elif action == "cancel":
            old = project.pending_changes
            project.step = old.get("previous_step", "start")
            project.return_step = old.get("previous_return_step", "")
            project.pending_changes = {}
            project.save()
            show_step(project)
        else:
            show_step(project)
        return
    if action == "pause":
        if project.step != "pause":
            if project.step == "materials":
                previous = project.return_step
            else:
                previous = project.step
            project.return_step = previous
            project.step = "pause"
            project.save()
        show_step(project)
        return
    if action == "continue":
        if project.step == "pause":
            target = project.return_step
            if not target:
                target = "start"
            project.return_step = ""
            set_step(project, target, keep_temporary=False)
        show_step(project)
        return
    if action == "materials":
        if project.step not in ("materials", "mentor_question", "mentor_wait"):
            if project.step != "pause":
                project.return_step = project.step
            project.step = "materials"
            project.save()
        show_step(project)
        return
    if project.step == "materials":
        if action.startswith("material:") and action[9:] in ("structure", "formatting", "assessment"):
            material(project, action[9:])
        elif action == "back":
            target = project.return_step
            if not target:
                target = "start"
            project.return_step = ""
            set_step(project, target, keep_temporary=False)
            show_step(project)
        else:
            show_step(project)
        return
    if action == "mentor" and project.topic and project.status == "active":
        if project.jobs.filter(kind="ai", status__in=["pending", "running"], project_revision=project.revision).exists():
            send(project, "Сначала дождись текущего ответа, затем задай вопрос.")
            return
        if project.step not in ("mentor_question", "mentor_wait"):
            if project.step != "pause":
                project.return_step = project.step
            project.pending_changes = {"mentor_return_step": project.return_step}
            project.step = "mentor_question"
            project.save()
        show_step(project)
        return
    if project.step == "mentor_question":
        if text and not action and not attachments and len(text) <= 3000:
            project.pending_changes = dict(project.pending_changes, question=text)
            project.step = "mentor_wait"
            project.save()
            show_step(project)
            queue_ai(project, "mentor_help", {"question": text})
        else:
            show_step(project)
        return
    if action == "revise" and project.status == "active" and project.review_status == "needs_revision":
        cancel_attempt(project)
        project.jobs.filter(kind="ai", status__in=["pending", "running"], payload__code="defense_questions").update(status="cancelled", finished_at=timezone.now())
        project.return_step = ""
        set_step(project, "files", keep_temporary=False)
        show_step(project)
        return
    if action == "retry":
        target = project.step
        if project.step in ("pause", "materials"):
            target = project.return_step
        if target == "choose_topic" and not project.topic:
            reset_topic_selection(project)
            target = "topics"
        code = {"topics": "topics", "literature": "literature", "goal_check": "goal_check", "tasks_check": "tasks_check", "checklist": "checklist", "defense_prepare": "defense_questions", "mentor_wait": "mentor_help"}.get(target)
        if code:
            queued = queue_ai(project, code)
            if code == "topics" and queued:
                show_step(project)
        else:
            show_step(project)
        return
    if action == "answered" and project.step in ("pause", "materials") and project.return_step == "defense_answer":
        project.return_step = ""
        set_step(project, "defense_repeat", keep_temporary=False)
        show_step(project)
        return
    if project.step == "start" and action == "yes":
        restart_profile = project.pending_changes.pop("restart_profile", False)
        step = "grade"
        if restart_profile or not project.student.full_name:
            step = "student_name"
        set_step(project, step)
    elif project.step == "start" and action == "no":
        project.return_step = "start"
        project.step = "pause"
        project.save()
    elif project.step == "student_name" and text and not action and not attachments and len(text) <= 200:
        project.student.full_name = text
        project.student.save(update_fields=["full_name"])
        set_step(project, "grade")
    elif project.step == "grade" and action == "grade:9":
        project.student.grade = 9
        project.student.save(update_fields=["grade"])
        set_step(project, "district")
    elif project.step == "district" and action.startswith("district:"):
        district = District.objects.filter(code=action[9:], active=True).first()
        if district:
            project.district = district.code
            project.region = ""
            project.selected_region = None
            set_step(project, "region")
    elif project.step == "region" and action == "other_region":
        set_step(project, "region_text")
    elif project.step == "region" and action.startswith("region_id:") and action[10:].isdigit():
        region = Region.objects.filter(pk=action[10:], district__code=project.district, district__active=True, active=True).first()
        if region:
            project.region = region.name
            project.selected_region = region
            set_step(project, "knows_project")
    elif project.step == "region_text" and text and not action and not attachments and len(text) <= 150:
        project.region = text
        project.selected_region = topics.matching_region(project.district, text)
        set_step(project, "knows_project")
    elif project.step == "knows_project" and action in ("yes", "no"):
        step = "project_info"
        if action == "yes":
            step = "subject"
        set_step(project, step)
    elif project.step == "project_info" and action == "next":
        set_step(project, "subject")
    elif project.step == "subject" and action.startswith("subject:") and action[8:] in SUBJECTS:
        project.subject = action[8:]
        set_step(project, "product")
    elif project.step == "product" and action.startswith("product:") and action[8:] in PRODUCTS:
        project.product_type = action[8:]
        set_step(project, "hobby")
    elif project.step == "hobby" and action.startswith("hobby:") and action[6:] in HOBBIES:
        project.hobby = action[6:]
        start_ai(project, "topics", "topics")
        return
    elif project.step == "choose_topic" and action.startswith("topic:") and action[6:].isdigit() and int(action[6:]) < len(project.topics):
        try:
            current = topics.offered_catalog(project)
        except Exception as error:
            if not isinstance(error, AIError):
                raise
            reset_topic_selection(project)
            show_step(project, STALE_TOPICS_TEXT + "\n\n")
            return
        selected = project.topics[int(action[6:])]
        project.topic = selected["title"]
        project.topic_source = current[selected["source_topic_id"]]
        start_ai(project, "literature", "literature")
        return
    elif project.step == "structure" and action == "yes":
        set_step(project, "structure_view")
        material(project, "structure")
    elif (project.step == "structure" and action == "no") or (project.step == "structure_view" and action == "next"):
        set_step(project, "goal")
    elif project.step == "goal" and (action == "use_goal_example" and project.goal_feedback.get("example") or text and not action and not attachments and len(text) <= 5000):
        project.goal_draft = text
        if action:
            project.goal_draft = project.goal_feedback["example"]
        start_ai(project, "goal_check", "goal_check")
        return
    elif project.step == "tasks_ready" and action == "yes":
        set_step(project, "tasks")
    elif project.step == "tasks_ready" and action == "no":
        project.return_step = "tasks_ready"
        project.step = "pause"
        project.save()
    elif project.step == "tasks" and (action == "use_tasks_example" and project.tasks_feedback.get("example_tasks") or text and not action and not attachments and len(text) <= 6000):
        project.tasks_draft = text
        if action:
            project.tasks_draft = "\n".join(project.tasks_feedback["example_tasks"])
        start_ai(project, "tasks_check", "tasks_check")
        return
    elif project.step == "work" and action.startswith("check:") and action[6:].isdigit() and int(action[6:]) < len(project.checklist):
        index = int(action[6:])
        project.checklist[index]["done"] = not project.checklist[index].get("done", False)
        project.save()
    elif project.step == "work" and action == "files":
        set_step(project, "files")
    elif project.step == "files" and action == "work":
        set_step(project, "work")
    elif project.step == "files" and action == "submit":
        submit(project)
        return
    elif project.step == "files" and attachments:
        add_attachments(project, attachments, event)
        return
    elif project.step == "files" and text and not action:
        add_link(project, text)
        return
    elif project.step == "defense_ready" and action == "yes":
        cancel_attempt(project)
        start_ai(project, "defense_questions", "defense_prepare")
        return
    elif project.step == "defense_ready" and action == "no":
        project.return_step = "defense_ready"
        project.step = "pause"
        project.save()
    elif project.step == "defense_timer" and action == "stop":
        cancel_attempt(project)
        set_step(project, "defense_repeat")
    elif project.step == "defense_answer" and action == "answered":
        set_step(project, "defense_repeat")
    elif project.step == "defense_repeat" and action == "yes":
        cancel_attempt(project)
        set_step(project, "defense_ready")
    elif project.step == "defense_repeat" and action == "no":
        set_step(project, "defended")
    elif project.step == "defended" and action == "yes":
        cancel_attempt(project)
        project.status = "defended"
        project.defended_at = timezone.now()
        set_step(project, "complete")
    elif project.step == "defended" and action == "no":
        send(project, "Хорошо. К репетиции можно вернуться позже.")
        set_step(project, "defense_ready")
    else:
        show_step(project, "Сейчас ожидается другое действие. Выбери актуальную кнопку или ответь на вопрос.\n\n")
        return
    show_step(project)


def submit(project):
    if project.jobs.filter(kind="download", status__in=["pending", "running"], project_revision=project.revision).exists():
        send(project, "Подожди, пока добавленные файлы сохранятся, затем отправь работу.")
        return
    if not project.files.exists():
        show_step(project, "Сначала добавь хотя бы один файл или ссылку.\n\n")
        return
    if not project.teacher_id or not project.teacher.active:
        show_step(project, "Учитель ещё не назначен. Работа сохранена. Попроси администрацию назначить наставника, затем отправь её снова.\n\n")
        return
    if project.review_status != "submitted":
        project.review_status = "submitted"
        project.submitted_at = timezone.now()
        project.save()
        if project.teacher.max_chat_id:
            url = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
            text = f"Ученик {project.student.full_name} отправил проект «{project.topic}» на проверку."
            if url:
                text += f"\n{url}/admin/bot/project/{project.pk}/change/"
            send(project, text, chat_id=project.teacher.max_chat_id)
    set_step(project, "defense_ready")
    show_step(project, "Работа доступна твоему учителю в кабинете проверки.\n\n")


def add_link(project, text):
    if project.files.count() >= 10:
        send(project, "В проект уже добавлено 10 материалов. Новый материал добавить нельзя.")
        return
    contains_space = False
    for character in text:
        if character.isspace():
            contains_space = True
    parsed = None
    try:
        parsed = urlsplit(text)
    except Exception:
        send(project, "Пришли отдельную ссылку, начинающуюся с http:// или https://, либо разрешённый файл.")
        return
    if parsed.scheme not in ("http", "https") or not parsed.hostname or contains_space or len(text) > 2000:
        send(project, "Пришли отдельную ссылку, начинающуюся с http:// или https://, либо разрешённый файл.")
        return
    if project.files.filter(external_url=text).exists():
        send(project, "Эта ссылка уже сохранена.")
        return
    ProjectFile.objects.create(project=project, kind="link", original_name=parsed.hostname[:255], external_url=text)
    show_step(project, "Ссылка сохранена. Проверь, что учитель сможет её открыть.\n\n")


def add_attachments(project, attachments, event=None):
    pending = project.jobs.filter(kind="download", status__in=["pending", "running"], project_revision=project.revision).count()
    count = project.files.count() + pending
    for attachment in attachments:
        if count >= 10:
            send(project, "Можно сохранить до 10 материалов на проект.")
            break
        if attachment.get("type") not in ("file", "image"):
            send(project, "Этот тип вложения не подходит. Пришли PDF, DOCX, PPTX, PNG или JPG, а для видео — ссылку.")
            continue
        BotJob.objects.create(project=project, event=event, kind="download", payload={"attachment": attachment}, project_revision=project.revision)
        count += 1
    send(project, "Проверяю и сохраняю разрешённые файлы. После сохранения сообщу результат.")


def apply_download(job, result):
    project = job.project
    if not project or project.status != "active" or project.revision != job.project_revision:
        return
    if project.files.count() >= 10:
        send(project, "Можно сохранить до 10 материалов на проект.")
        return
    name = Path(result["original_name"].replace("\\", "/")).name[:255]
    if Path(name).suffix.lower() not in (".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg") or len(result["content"]) > 20 * 1024 * 1024:
        send(project, "Файл не сохранён. Нужен PDF, DOCX, PPTX, PNG или JPG размером до 20 МБ.")
        return
    attachment_id = str(result.get("max_attachment_id") or "")[:500]
    if attachment_id and project.files.filter(max_attachment_id=attachment_id).exists():
        send(project, "Этот файл уже сохранён.")
        return
    item = ProjectFile(project=project, kind="file", original_name=name, max_attachment_id=attachment_id)
    item.stored_file.save(name, ContentFile(result["content"]), save=True)
    send(project, f"Файл «{name}» сохранён. Материалов: {project.files.count()}.", rows(project, [("Готово, отправить учителю", "submit")]))


def review_text(project):
    text = f"Учитель обновил проверку проекта «{project.topic}». Статус: {REVIEWS.get(project.review_status, project.review_status)}."
    if project.teacher_feedback:
        text += f"\n{project.teacher_feedback}"
    return text


def queue_review_notification(project):
    if project.status == "deferred":
        return
    buttons = rows(project, [("Мой проект", "project")])
    if project.status == "active" and project.review_status == "needs_revision":
        buttons = rows(project, [("Доработать", "revise")])
    if project.status == "active":
        extra_buttons = None
        if project.review_status == "needs_revision":
            extra_buttons = buttons
        show_step(project, review_text(project) + "\n\n", extra_buttons=extra_buttons, notify=True)
    else:
        send(project, review_text(project), buttons, notify=True)


def trim_task_prefix(text):
    text = text.strip()
    if not text:
        return text
    if text[0] in ("-", "•"):
        return text[1:].strip()
    digit_count = 0
    for character in text:
        if not character.isdecimal():
            break
        digit_count += 1
    if digit_count > 0 and digit_count < len(text):
        if text[digit_count] in (".", ")"):
            return text[digit_count + 1:].strip()
    return text


def apply_ai_result(job, result):
    project = job.project
    if not project or project.status != "active" or project.revision != job.project_revision:
        return
    code = job.payload["code"]
    expected = {"topics": "topics", "literature": "literature", "goal_check": "goal_check", "tasks_check": "tasks_check", "checklist": "checklist", "defense_questions": "defense_prepare", "mentor_help": "mentor_wait"}[code]
    if effective_step(project) != expected:
        return
    if code == "topics":
        validate_topic_job(job)
        project.topics = topics.proposals_with_sources(project, result, job.payload["data"]["approved_topics"])
        project.topic_source = None
        set_step(project, "choose_topic")
    elif code == "literature":
        project.literature = result
        send(project, literature_text(result))
        set_step(project, "structure")
    elif code == "goal_check":
        project.goal_feedback = result
        if result["accepted"]:
            project.goal = project.goal_draft
            set_step(project, "tasks_ready")
            send(project, "Цель принята. " + result["feedback"])
        else:
            set_step(project, "goal")
    elif code == "tasks_check":
        project.tasks_feedback = result
        if result["accepted"]:
            project.tasks = []
            for line in project.tasks_draft.splitlines():
                if line.strip():
                    project.tasks.append(trim_task_prefix(line))
            set_step(project, "checklist")
            send(project, "Задачи приняты. " + result["feedback"])
            queue_ai(project, "checklist")
        else:
            set_step(project, "tasks")
    elif code == "checklist":
        project.checklist = []
        for item in result["items"]:
            project.checklist.append({"text": item, "done": False})
        set_step(project, "work")
    elif code == "defense_questions":
        project.defense_questions = result["questions"]
        project.defense_attempt += 1
        project.defense_ends_at = timezone.now() + timedelta(seconds=300)
        project.defense_notified_at = None
        set_step(project, "defense_timer")
    elif code == "mentor_help":
        send(project, result["answer"])
        state = dialog_state(project)
        target = state["pending_changes"].get("mentor_return_step")
        if not target:
            target = state["return_step"]
        if not target:
            target = "work"
        if state["step"] in ("restart_confirm", "edit_confirm"):
            state["pending_changes"] = dict(state["pending_changes"], previous_step=target, previous_return_step="")
        elif state["step"] in ("pause", "materials"):
            state["pending_changes"] = {}
            state["return_step"] = target
        else:
            state["pending_changes"] = {}
            state["return_step"] = ""
        store_dialog_state(project, state)
        project.save()
        if state["step"] not in ("restart_confirm", "edit_confirm", "pause", "materials"):
            set_step(project, target, keep_temporary=False)
    show_step(project)


def fail_ai_job(job):
    project = job.project
    if project and project.status == "active" and project.revision == job.project_revision:
        if job.error_text == "ai_catalog_changed":
            text = STALE_TOPICS_TEXT
        elif job.error_text == "ai_daily_limit":
            text = "Сегодня достигнут лимит подсказок. Твой текст сохранён. Продолжить можно завтра; проект и материалы доступны."
        else:
            text = "Не получилось получить ответ. Твой текст сохранён. Попробовать ещё раз?"
        if project.step == "start_reset_confirm":
            show_step(project, text + "\n\n")
        else:
            send(project, text, rows(project, [("Попробовать ещё раз", "retry")]))


def check_timers():
    now = timezone.now()
    projects = Project.objects.filter(status="active", defense_ends_at__lte=now, defense_notified_at__isnull=True)
    for project in projects:
        if len(project.defense_questions) != 2:
            continue
        project.defense_notified_at = now
        set_step(project, "defense_answer")
        text = "Время вышло. Ответь на два вопроса вслух:\n1. " + project.defense_questions[0] + "\n2. " + project.defense_questions[1]
        options = [("Ответил", "answered")]
        if project.step == "start_reset_confirm":
            text += "\n\n" + MESSAGES["start_reset_confirm"]
            options = START_RESET_OPTIONS
        send(project, text, rows(project, options), deduplication_key=f"defense:{project.pk}:{project.revision}:{project.defense_attempt}")
