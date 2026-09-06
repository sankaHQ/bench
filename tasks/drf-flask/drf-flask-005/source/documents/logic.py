from django.db import transaction
from django.utils.http import parse_etags

from documents.models import Document, RevisionEvent


def etag(document):
    return f'"doc-{document.id}-r{document.revision}"'


def headers(document):
    return {"ETag": etag(document), "Cache-Control": "private, must-revalidate"}


def matches(value, document, *, weak=False):
    if value.strip() == "*":
        return True
    tags = parse_etags(value)
    if weak:
        tags = [tag.removeprefix("W/") for tag in tags]
    return etag(document) in tags


def representation(document):
    return {
        "id": document.id,
        "title": document.title,
        "body": document.body,
        "revision": document.revision,
    }


def mutate(owner, identifier, condition, values, *, delete=False):
    with transaction.atomic():
        document = (
            Document.objects.select_for_update()
            .filter(id=identifier, owner=owner, deleted=False)
            .first()
        )
        if document is None:
            return {"detail": "Document not found."}, 404, {}
        if not condition:
            return {"detail": "If-Match is required."}, 428, headers(document)
        if not matches(condition, document):
            return {"detail": "Document revision has changed."}, 412, headers(document)
        for key, value in values.items():
            setattr(document, key, value)
        document.deleted = delete
        document.revision += 1
        document.save()
        RevisionEvent.objects.create(
            document=document, revision=document.revision, action="delete" if delete else "update"
        )
        return (
            (None if delete else representation(document)),
            (204 if delete else 200),
            headers(document),
        )
