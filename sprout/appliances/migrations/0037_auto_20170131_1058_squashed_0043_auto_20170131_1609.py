# -*- coding: utf-8 -*-
# Generated by Django 1.9.12 on 2017-01-31 16:12


from django.db import migrations, models


class Migration(migrations.Migration):

    replaces = [
        (b'appliances', '0037_auto_20170131_1058'),
        (b'appliances', '0038_auto_20170131_1512'),
        (b'appliances', '0039_auto_20170131_1512'),
        (b'appliances', '0040_provider_memory_limit'),
        (b'appliances', '0041_auto_20170131_1518'),
        (b'appliances', '0042_auto_20170131_1526'),
        (b'appliances', '0043_auto_20170131_1609')]

    dependencies = [
        ('appliances', '0036_template_ga_released'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='appliance',
            options={'permissions': (('can_modify_hw', 'Can modify HW configuration'),)},
        ),
        migrations.AddField(
            model_name='appliance',
            name='cpu',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='appliance',
            name='ram',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='provider',
            name='total_cpu',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='provider',
            name='total_memory',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='provider',
            name='used_cpu',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='provider',
            name='used_memory',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='appliancepool',
            name='override_cpu',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='appliancepool',
            name='override_memory',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='provider',
            name='memory_limit',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
