"""
Shared helpers for extracting and normalizing course "about" / marketing details.

These helpers read author-entered data off a course block (``instructor_info``,
``learning_info``, ``duration_value``/``duration_unit``) or the course's "about"
documents (the marketing ``title``), and return them in a normalized, safe shape
suitable for serialization.

They are shared by the multiple course-detail APIs (e.g. the courseware API used by
the catalog MFE and the course API used by the mobile app) so that this logic lives
in exactly one place. All author-entered HTML (instructor bios, learning outcomes,
requirements) is passed through :func:`clean_dangerous_html` so that no endpoint
can serve unsanitized markup.
"""

import logging

from openedx.core.djangoapps.models.course_details import CourseDetails
from openedx.core.djangolib.markup import clean_dangerous_html

log = logging.getLogger(__name__)


def get_course_instructors(course, request=None):
    """
    Return the course instructors as a normalized list of dicts.

    Each returned dict contains ``name``, ``title``, ``organization``, ``image`` and
    ``bio``. Instructor bios are sanitized. When ``request`` is provided, relative
    image paths (e.g. ``/asset-v1:.../photo.jpg``) are resolved to absolute URLs so
    they load correctly from clients served on a different origin than the LMS.

    Args:
        course: The course block (may be ``None``).
        request: The current request, used to build absolute image URLs. Optional.

    Returns:
        list[dict]: One dict per valid instructor. Empty list if there are none.
    """
    if course is None:
        return []

    info = getattr(course, 'instructor_info', {}) or {}
    raw_instructors = info.get('instructors', []) if isinstance(info, dict) else []

    instructors = []
    for instructor in raw_instructors:
        if not isinstance(instructor, dict):
            log.warning(
                "Skipping malformed instructor entry (expected dict, got %s) for course %s",
                type(instructor).__name__, getattr(course, 'id', None),
            )
            continue

        image = instructor.get('image')
        image = image if isinstance(image, str) else None
        if image and request is not None and not image.startswith(('http://', 'https://')):
            image = request.build_absolute_uri(image)

        instructors.append({
            'name': instructor.get('name') or '',
            'title': instructor.get('title') or '',
            'organization': instructor.get('organization') or '',
            'image': image or '',
            'bio': clean_dangerous_html(instructor.get('bio')) or '',
        })
    return instructors


def get_course_learning_outcomes(course):
    """
    Return the course learning outcomes ("what you will learn") as a list of strings.

    Blank entries are dropped and each entry is sanitized.

    Args:
        course: The course block (may be ``None``).

    Returns:
        list[str]: The learning outcomes. Empty list if there are none.
    """
    if course is None:
        return []

    outcomes = getattr(course, 'learning_info', []) or []
    return [
        clean_dangerous_html(outcome)
        for outcome in outcomes
        if isinstance(outcome, str) and outcome.strip()
    ]


def get_course_duration(course):
    """
    Return a human-readable course duration (e.g. ``"6 weeks"``), or ``None``.

    The duration is built from the course's ``duration_value`` and ``duration_unit``
    fields, singularizing the unit when the value is 1 (e.g. ``"1 week"``).

    Args:
        course: The course block (may be ``None``).

    Returns:
        str or None: The formatted duration, or ``None`` when it is not set.
    """
    if course is None:
        return None

    duration_value = getattr(course, 'duration_value', None)
    duration_unit = getattr(course, 'duration_unit', None)
    if duration_value is not None and duration_unit:
        unit = duration_unit
        # Singularize the unit for a single-value duration (e.g. "1 week", not "1 weeks").
        if duration_value == 1 and unit.endswith('s'):
            unit = unit[:-1]
        return f"{duration_value} {unit}"
    return None


def get_course_requirement(course_key):
    """
    Return the course requirements text, or ``None``.

    In this deployment the "Course Requirements" content is stored in the marketing
    ``title`` "about" attribute in Studio. The value is sanitized before being returned.

    Args:
        course_key: The course key (``CourseKey``).

    Returns:
        str or None: The sanitized requirements text, or ``None`` when it is not set.
    """
    return clean_dangerous_html(CourseDetails.fetch_about_attribute(course_key, 'title'))
