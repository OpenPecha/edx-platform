"""
Course API Serializers.  Representing course catalog data
"""


import urllib

from common.djangoapps.student.models import CourseEnrollment
from django.contrib.auth import get_user_model
from django.urls import reverse
from edx_django_utils import monitoring as monitoring_utils
from rest_framework import serializers

from lms.djangoapps.certificates.api import can_show_certificate_available_date_field
from openedx.core.djangoapps.content.course_overviews.models import \
    CourseOverview  # lint-amnesty, pylint: disable=unused-import
from openedx.core.djangoapps.models.course_details import CourseDetails
from openedx.core.lib.api.fields import AbsoluteURLField
from xmodule.modulestore.django import modulestore

class _MediaSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Nested serializer to represent a media object.
    """

    def __init__(self, uri_attribute, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uri_attribute = uri_attribute

    uri = serializers.SerializerMethodField(source='*')

    def get_uri(self, course_overview):
        """
        Get the representation for the media resource's URI
        """
        return getattr(course_overview, self.uri_attribute)


class _AbsolutMediaSerializer(_MediaSerializer):  # pylint: disable=abstract-method
    """
    Nested serializer to represent a media object and its absolute path.
    """
    requires_context = True

    def __call__(self, serializer_field):
        self.context = serializer_field.context
        return super(self).__call__(serializer_field)  # lint-amnesty, pylint: disable=bad-super-call

    uri_absolute = serializers.SerializerMethodField(source="*")

    def get_uri_absolute(self, course_overview):
        """
        Convert the media resource's URI to an absolute URI.
        """
        uri = getattr(course_overview, self.uri_attribute)

        if not uri:
            # Return empty string here, to keep the same
            # response type in case uri is empty as well.
            return ""

        cdn_applied_uri = course_overview.apply_cdn_to_url(uri)
        field = AbsoluteURLField()

        # In order to use the AbsoluteURLField to have the same
        # behaviour what ImageSerializer provides, we need to set
        # the request for the field
        field._context = {"request": self.context.get("request")}  # lint-amnesty, pylint: disable=protected-access

        return field.to_representation(cdn_applied_uri)


class ImageSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Collection of URLs pointing to images of various sizes.

    The URLs will be absolute URLs with the host set to the host of the current request. If the values to be
    serialized are already absolute URLs, they will be unchanged.
    """
    raw = AbsoluteURLField()
    small = AbsoluteURLField()
    large = AbsoluteURLField()


class _CourseApiMediaCollectionSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Nested serializer to represent a collection of media objects
    """
    banner_image = _AbsolutMediaSerializer(source='*', uri_attribute='banner_image_url')
    course_image = _MediaSerializer(source='*', uri_attribute='course_image_url')
    course_video = _MediaSerializer(source='*', uri_attribute='course_video_url')
    image = ImageSerializer(source='image_urls')


class CourseSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for Course objects providing minimal data about the course.
    Compare this with CourseDetailSerializer.
    """

    blocks_url = serializers.SerializerMethodField()
    effort = serializers.CharField()
    end = serializers.DateTimeField()
    enrollment_start = serializers.DateTimeField()
    enrollment_end = serializers.DateTimeField()
    id = serializers.CharField()  # pylint: disable=invalid-name
    media = _CourseApiMediaCollectionSerializer(source='*')
    name = serializers.CharField(source='display_name_with_default_escaped')
    number = serializers.CharField(source='display_number_with_default')
    org = serializers.CharField(source='display_org_with_default')
    short_description = serializers.CharField()
    start = serializers.DateTimeField()
    start_display = serializers.CharField()
    start_type = serializers.CharField()
    pacing = serializers.CharField()
    mobile_available = serializers.BooleanField()
    hidden = serializers.SerializerMethodField()
    invitation_only = serializers.BooleanField()
    # fields enabled by the extended course detail flag
    duration = serializers.SerializerMethodField()
    course_requirement = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    learning_outcomes = serializers.SerializerMethodField()
    instructors = serializers.SerializerMethodField()

    # 'course_id' is a deprecated field, please use 'id' instead.
    course_id = serializers.CharField(source='id', read_only=True)

    def get_hidden(self, course_overview):
        """
        Get the representation for SerializerMethodField `hidden`
        Represents whether course is hidden in LMS
        """
        catalog_visibility = course_overview.catalog_visibility
        return catalog_visibility in ['about', 'none'] or course_overview.id.deprecated  # Old Mongo should be hidden

    def get_blocks_url(self, course_overview):
        """
        Get the representation for SerializerMethodField `blocks_url`
        """
        base_url = '?'.join([
            reverse('blocks_in_course'),
            urllib.parse.urlencode({'course_id': course_overview.id}),
        ])
        return self.context['request'].build_absolute_uri(base_url)

    # Cache for course details to avoid repeated lookups
    _course_details_cache = {}

    def get_duration(self, course_overview):
        """
        Get the course duration from course details.
        """
        course_details = self._get_course_details(course_overview)
        duration_value = getattr(course_details, "duration_value", None)
        duration_unit = getattr(course_details, "duration_unit", None)
        if course_details and duration_value and duration_unit:
            value = duration_value
            unit = duration_unit

            # Singularize if needed
            if value == 1 and unit.endswith("s"):
                unit = unit[:-1]

            return f"{value} {unit}"
        return None

    def _get_course_details(self, course_overview):
        """Helper to get cached CourseDetails for a course_overview."""
        course_id_str = str(course_overview.id)
        if course_id_str not in self.__class__._course_details_cache:
            try:
                self.__class__._course_details_cache[course_id_str] = (
                    modulestore().get_course(course_overview.id)
                )
            except (ImportError, AttributeError):
                self.__class__._course_details_cache[course_id_str] = None
        return self.__class__._course_details_cache.get(course_id_str)

    def get_course_requirement(self, course_overview):
        """
        Return the course requirement value configured in Studio.

        This maps to the CourseDetails "title" marketing field in Studio,
        which in this deployment is used to capture course requirements.
        """
        course_details = self._get_course_details(course_overview)
        return getattr(course_details, 'title', None) if course_details else None

    def get_description(self, course_overview):
        """
        Return the long description (Studio "description") from CourseDetails.
        Note: This is distinct from the 'overview' field provided on the detail endpoint.
        """
        course_details = self._get_course_details(course_overview)
        return getattr(course_details, 'description', None) if course_details else None

    def get_learning_outcomes(self, course_overview):
        """
        Return learning outcomes as a list of strings from CourseDetails.learning_info.
        """
        course_details = self._get_course_details(course_overview)
        outcomes = getattr(course_details, 'learning_info', None) if course_details else None
        # Ensure we only return list[str] or None
        if isinstance(outcomes, (list, tuple)):
            return [o for o in outcomes if isinstance(o, str)]
        return None

    def get_instructors(self, course_overview):
        """
        Return instructor details excluding media. Each item includes
        name, title, organization, and bio.
        """
        course_details = self._get_course_details(course_overview)
        instructor_info = getattr(course_details, 'instructor_info', None) if course_details else None
        instructors = []
        try:
            raw_list = (instructor_info or {}).get('instructors', [])
        except AttributeError:
            raw_list = []
        for ins in raw_list:
            if not isinstance(ins, dict):
                continue
            instructors.append({
                'name': ins.get('name'),
                'title': ins.get('title'),
                'organization': ins.get('organization'),
                'bio': ins.get('bio'),
            })
        return instructors or None


class CourseDetailSerializer(CourseSerializer):  # pylint: disable=abstract-method
    """
    Serializer for Course objects providing additional details about the
    course.

    This serializer makes additional database accesses (to the modulestore) and
    returns more data (including 'overview' text). Therefore, for performance
    and bandwidth reasons, it is expected that this serializer is used only
    when serializing a single course, and not for serializing a list of
    courses.
    """

    overview = serializers.SerializerMethodField()

    def get_overview(self, course_overview):
        """
        Get the representation for SerializerMethodField `overview`
        """
        # Note: This makes a call to the modulestore, unlike the other
        # fields from CourseSerializer, which get their data
        # from the CourseOverview object in SQL.
        return CourseDetails.fetch_about_attribute(course_overview.id, 'overview')

    def to_representation(self, instance):
        """
        Get the `certificate_available_date` in response
        if the `certificates.auto_certificate_generation` waffle switch is enabled

        Get the 'is_enrolled' in response if 'username' is in query params,
        user is staff, superuser, or user is authenticated and
        the has the same 'username' as the 'username' in the query params.
        """
        response = super().to_representation(instance)
        if can_show_certificate_available_date_field(instance):
            response['certificate_available_date'] = instance.certificate_available_date

        requested_username = self.context['request'].query_params.get('username', None)
        if requested_username:
            user = self.context['request'].user
            if ((user.is_authenticated and user.username == requested_username)
                    or user.is_staff or user.is_superuser):
                User = get_user_model()
                requested_user = User.objects.get(username=requested_username)
                response['is_enrolled'] = CourseEnrollment.is_enrolled(requested_user, instance.id)
        return response


class CourseKeySerializer(serializers.BaseSerializer):  # pylint:disable=abstract-method
    """
    Serializer that takes a CourseKey and serializes it to a string course_id.
    """

    @monitoring_utils.function_trace('course_key_serializer_to_representation')
    def to_representation(self, instance):
        # The function trace should be counting calls to this function, but I
        # couldn't find it when I looked in any of the NR transaction traces,
        # so I'm manually counting them using a custom metric:
        monitoring_utils.increment('course_key_serializer_to_representation_call_count')

        return str(instance)
