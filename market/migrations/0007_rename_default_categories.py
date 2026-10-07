from django.db import migrations

CATEGORIES = ["工具", "代码", "游戏"]
RENAMES = {
    "Phones": "工具",
    "Python": "代码",
}


def update_categories(apps, schema_editor):
    category = apps.get_model("market", "Category")
    for old_name, new_name in RENAMES.items():
        category.objects.filter(name=old_name).update(name=new_name)
    for name in CATEGORIES:
        category.objects.get_or_create(name=name)
    category.objects.exclude(name__in=CATEGORIES).delete()


def rollback_categories(apps, schema_editor):
    category = apps.get_model("market", "Category")
    old_names = []
    for new_name, old_name in RENAMES.items():
        category.objects.filter(name=new_name).update(name=old_name)
        old_names.append(old_name)
    for name in old_names:
        category.objects.get_or_create(name=name)
    category.objects.exclude(name__in=old_names).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0006_tag_user_avatar_user_bio_user_skills_work_tags"),
    ]

    operations = [
        migrations.RunPython(update_categories, rollback_categories),
    ]
