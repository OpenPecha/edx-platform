# Generated migration for adding product_url field to CourseMode

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course_modes', '0016_alter_historicalcoursemode_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='coursemode',
            name='product_url',
            field=models.URLField(
                blank=True,
                help_text='OPTIONAL: URL to the product page for this course mode. This can link to an external payment or registration page.',
                max_length=500,
                null=True,
                verbose_name='Product URL'
            ),
        ),
        migrations.AddField(
            model_name='historicalcoursemode',
            name='product_url',
            field=models.URLField(
                blank=True,
                help_text='OPTIONAL: URL to the product page for this course mode. This can link to an external payment or registration page.',
                max_length=500,
                null=True,
                verbose_name='Product URL'
            ),
        ),
    ]
