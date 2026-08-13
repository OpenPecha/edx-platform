"""
Tests for the shared course "about" / marketing detail helpers.
"""

from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from openedx.core.lib import course_about


class _FakeRequest:
    """Minimal request stub that resolves relative paths against a fixed host."""

    def build_absolute_uri(self, location):
        return f"http://lms.example.com{location}"


def _course(**attrs):
    """Build a lightweight stand-in for a course block with the given attributes."""
    return SimpleNamespace(**attrs)


class GetCourseInstructorsTests(TestCase):
    """Tests for :func:`get_course_instructors`."""

    def test_returns_empty_list_for_none_course(self):
        self.assertEqual(course_about.get_course_instructors(None), [])

    def test_returns_empty_list_when_not_configured(self):
        self.assertEqual(course_about.get_course_instructors(_course(instructor_info={})), [])

    def test_normalizes_instructor_fields(self):
        course = _course(instructor_info={'instructors': [{
            'name': 'Jane Doe',
            'title': 'Professor',
            'organization': 'openedX University',
            'image': 'https://cdn.example.com/jane.jpg',
            'bio': '<p>Bio</p>',
        }]})

        result = course_about.get_course_instructors(course)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'Jane Doe')
        self.assertEqual(result[0]['title'], 'Professor')
        self.assertEqual(result[0]['organization'], 'openedX University')

    def test_resolves_relative_image_to_absolute_url(self):
        course = _course(instructor_info={'instructors': [{'name': 'Jane', 'image': '/asset-v1:x/jane.jpg'}]})

        result = course_about.get_course_instructors(course, _FakeRequest())

        self.assertEqual(result[0]['image'], 'http://lms.example.com/asset-v1:x/jane.jpg')

    def test_leaves_absolute_image_untouched(self):
        course = _course(instructor_info={'instructors': [{'name': 'Jane', 'image': 'https://cdn/j.jpg'}]})

        result = course_about.get_course_instructors(course, _FakeRequest())

        self.assertEqual(result[0]['image'], 'https://cdn/j.jpg')

    def test_leaves_relative_image_untouched_without_request(self):
        course = _course(instructor_info={'instructors': [{'name': 'Jane', 'image': '/asset/j.jpg'}]})

        result = course_about.get_course_instructors(course)

        self.assertEqual(result[0]['image'], '/asset/j.jpg')

    def test_sanitizes_instructor_bio(self):
        course = _course(instructor_info={'instructors': [
            {'name': 'Jane', 'bio': '<script>alert(1)</script><p>Safe</p>'},
        ]})

        result = course_about.get_course_instructors(course)

        self.assertNotIn('<script>', result[0]['bio'])
        self.assertIn('Safe', result[0]['bio'])

    def test_skips_non_dict_entries(self):
        course = _course(instructor_info={'instructors': ['not-a-dict', {'name': 'Jane'}]})

        result = course_about.get_course_instructors(course)

        self.assertEqual([i['name'] for i in result], ['Jane'])


class GetCourseLearningOutcomesTests(TestCase):
    """Tests for :func:`get_course_learning_outcomes`."""

    def test_returns_empty_list_for_none_course(self):
        self.assertEqual(course_about.get_course_learning_outcomes(None), [])

    def test_filters_blank_and_non_string_entries(self):
        course = _course(learning_info=['Learn X', '', '   ', None, 42, 'Learn Y'])

        self.assertEqual(
            course_about.get_course_learning_outcomes(course),
            ['Learn X', 'Learn Y'],
        )

    def test_sanitizes_entries(self):
        course = _course(learning_info=['<script>bad</script>keep'])

        result = course_about.get_course_learning_outcomes(course)

        self.assertNotIn('<script>', result[0])
        self.assertIn('keep', result[0])


class GetCourseDurationTests(TestCase):
    """Tests for :func:`get_course_duration`."""

    def test_returns_none_for_none_course(self):
        self.assertIsNone(course_about.get_course_duration(None))

    def test_returns_none_when_unset(self):
        self.assertIsNone(course_about.get_course_duration(_course(duration_value=None, duration_unit=None)))

    def test_formats_value_and_unit(self):
        self.assertEqual(
            course_about.get_course_duration(_course(duration_value=6, duration_unit='weeks')),
            '6 weeks',
        )

    def test_singularizes_unit_for_value_of_one(self):
        self.assertEqual(
            course_about.get_course_duration(_course(duration_value=1, duration_unit='weeks')),
            '1 week',
        )


class GetCourseRequirementTests(TestCase):
    """Tests for :func:`get_course_requirement`."""

    @mock.patch('openedx.core.lib.course_about.CourseDetails.fetch_about_attribute')
    def test_fetches_and_sanitizes_title_attribute(self, mock_fetch):
        mock_fetch.return_value = '<script>x</script><p>Requirement</p>'

        result = course_about.get_course_requirement('course-v1:Org+Course+Run')

        mock_fetch.assert_called_once_with('course-v1:Org+Course+Run', 'title')
        self.assertNotIn('<script>', result)
        self.assertIn('Requirement', result)

    @mock.patch('openedx.core.lib.course_about.CourseDetails.fetch_about_attribute')
    def test_returns_none_when_unset(self, mock_fetch):
        mock_fetch.return_value = None

        self.assertIsNone(course_about.get_course_requirement('course-v1:Org+Course+Run'))
