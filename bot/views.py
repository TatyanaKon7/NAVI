from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .models import Material, ProjectFile, is_administration, teacher_for_user


def download_response(stored_file, filename):
    source = None
    transferred = False
    try:
        source = stored_file.open("rb")
        response = FileResponse(source, as_attachment=True, filename=filename)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        transferred = True
        return response
    except Exception:
        raise Http404 from None
    finally:
        if not transferred and source is not None:
            source.close()


@staff_member_required
def project_file(request, file_id):
    files = ProjectFile.objects.select_related("project__teacher__user")
    if not is_administration(request.user):
        teacher = teacher_for_user(request.user)
        if teacher is None:
            raise Http404
        files = files.filter(project__teacher=teacher)
    item = get_object_or_404(files, pk=file_id)
    if not item.stored_file:
        raise Http404
    return download_response(item.stored_file, item.original_name)


@staff_member_required
def material_file(request, material_id):
    administrator = is_administration(request.user)
    if not administrator and teacher_for_user(request.user) is None:
        raise Http404
    materials = Material.objects.filter(active=True)
    if administrator:
        materials = Material.objects.all()
    material = get_object_or_404(materials, pk=material_id)
    if not material.file:
        raise Http404
    return download_response(material.file, material.file.name.rsplit("/", 1)[-1])
