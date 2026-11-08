from django.db.models import Q

from .ai import AIError, validate_result
from .models import Region, RegionalTopic


def matching_region(district, name, selectable=False):
    regions = Region.objects.filter(district__code=district)
    if selectable:
        regions = regions.filter(active=True, district__active=True)
    matches = []
    for region in regions:
        if region.name.casefold() == name.strip().casefold():
            matches.append(region)
    if len(matches) == 1:
        return matches[0]
    return None


def project_region(project):
    if project.selected_region_id:
        return Region.objects.filter(pk=project.selected_region_id).first()
    region = matching_region(project.district, project.region)
    if region:
        project.selected_region = region
        if project.pk:
            project.save(update_fields=["selected_region"])
    return region


def matching_topics(project):
    region = project_region(project)
    if not region:
        return RegionalTopic.objects.none()
    return RegionalTopic.objects.filter(region=region, active=True).filter(
        Q(subject="") | Q(subject=project.subject),
        Q(product_type="") | Q(product_type=project.product_type),
        Q(hobby="") | Q(hobby=project.hobby),
    )


def topic_snapshot(topic):
    return {"id": topic.pk, "title": topic.title, "problem": topic.problem, "updated_at": topic.updated_at.isoformat()}


def catalog_for_project(project):
    result = []
    for topic in matching_topics(project).order_by("order", "pk")[:30]:
        result.append(topic_snapshot(topic))
    return result


def validate_catalog(project, bank):
    if not isinstance(bank, list) or not 1 <= len(bank) <= 30:
        raise AIError().setup("ai_catalog_changed")
    ids = []
    for item in bank:
        if not isinstance(item, dict) or set(item) != {"id", "title", "problem", "updated_at"}:
            raise AIError().setup("ai_catalog_changed")
        if type(item["id"]) is not int or item["id"] <= 0:
            raise AIError().setup("ai_catalog_changed")
        for field in ("title", "problem", "updated_at"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise AIError().setup("ai_catalog_changed")
        ids.append(item["id"])
    if len(set(ids)) != len(ids):
        raise AIError().setup("ai_catalog_changed")
    current = {}
    for topic in matching_topics(project).filter(pk__in=ids):
        current[topic.pk] = topic
    if len(current) != len(bank):
        raise AIError().setup("ai_catalog_changed")
    for item in bank:
        if topic_snapshot(current[item["id"]]) != item:
            raise AIError().setup("ai_catalog_changed")
    return current


def proposals_with_sources(project, result, bank):
    validate_result("topics", result)
    validate_catalog(project, bank)
    sources = {}
    for item in bank:
        sources[item["id"]] = item
    proposals = []
    for item in result["topics"]:
        source = sources.get(item["source_topic_id"])
        if not source:
            raise AIError().setup("ai_invalid_topic_source")
        proposals.append(dict(item, source_title=source["title"], source_problem=source["problem"], source_updated_at=source["updated_at"]))
    return proposals


def offered_catalog(project):
    if not isinstance(project.topics, list) or len(project.topics) != 3:
        raise AIError().setup("ai_catalog_changed")
    bank = {}
    proposals = []
    for item in project.topics:
        if not isinstance(item, dict):
            raise AIError().setup("ai_catalog_changed")
        for field in ("source_topic_id", "title", "description", "regional", "source_title", "source_problem", "source_updated_at"):
            if field not in item:
                raise AIError().setup("ai_catalog_changed")
        source_id = item["source_topic_id"]
        if type(source_id) is not int or source_id <= 0:
            raise AIError().setup("ai_catalog_changed")
        source = {"id": source_id, "title": item["source_title"], "problem": item["source_problem"], "updated_at": item["source_updated_at"]}
        if source_id in bank and bank[source_id] != source:
            raise AIError().setup("ai_catalog_changed")
        bank[source_id] = source
        proposal = {}
        for field in ("source_topic_id", "title", "description", "regional"):
            proposal[field] = item[field]
        proposals.append(proposal)
    try:
        validate_result("topics", {"topics": proposals})
    except Exception:
        raise AIError().setup("ai_catalog_changed") from None
    return validate_catalog(project, list(bank.values()))
