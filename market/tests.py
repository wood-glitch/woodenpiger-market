import zipfile
import base64
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PigerTransaction, Tag, Work, WorkSourceFile, WorkVersion

User = get_user_model()

PASSWORD = "Str0ngPass!42"

AVATAR_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
)


def make_project_zip():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("demo-project/README.md", "# Demo project\n")
        archive.writestr("demo-project/src/main.py", 'print("hello")\n')
        archive.writestr("demo-project/src/logo.png", b"\x89PNG fake data")
    return SimpleUploadedFile(
        "project.zip",
        buffer.getvalue(),
        content_type="application/zip",
    )


def make_markdown_folder_zip():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "demo-project/markdown/intro.md", "# Folder summary\n"
        )
        archive.writestr("demo-project/src/main.py", 'print("hello")\n')
    return SimpleUploadedFile(
        "project.zip",
        buffer.getvalue(),
        content_type="application/zip",
    )


def make_text_summary_zip():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("demo-project/使用说明.txt", "GGBOY 文本简介\n")
        archive.writestr("demo-project/main.py", 'print("hello")\n')
    return SimpleUploadedFile(
        "project.zip",
        buffer.getvalue(),
        content_type="application/zip",
    )


def ensure_tag(name):
    return Tag.objects.get_or_create(name=name)[0]


def find_file_node(nodes, name):
    for node in nodes:
        if node["type"] == "file" and node["name"] == name:
            return node
        if node["type"] == "directory":
            found = find_file_node(node["children"], name)
            if found:
                return found
    return None


class RegisterAndCheckInTests(APITestCase):
    def test_register_gets_five_piger_and_records_transaction(self):
        response = self.client.post(
            "/api/auth/register/",
            {"username": "alice", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["piger_balance"], 5)
        self.assertEqual(PigerTransaction.objects.count(), 1)
        self.assertEqual(PigerTransaction.objects.get().reason, "register")

    def test_checkin_adds_one_piger_once_per_day(self):
        user = User.objects.create_user("alice", password=PASSWORD)
        self.client.force_authenticate(user)

        response = self.client.get("/api/checkins/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["has_checked_in"])

        response = self.client.post("/api/checkins/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["piger_balance"], 1)

        response = self.client.post("/api/checkins/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        user.refresh_from_db()
        self.assertEqual(user.piger_balance, 1)
        self.assertEqual(
            PigerTransaction.objects.filter(reason="checkin").count(), 1
        )


class WorkVisibilityTests(APITestCase):
    def setUp(self):
        self.author = User.objects.create_superuser(
            "author", password=PASSWORD
        )
        self.work = Work.objects.create(
            title="demo",
            summary="public summary",
            content="private detail",
            cost_piger=2,
            status="published",
            author=self.author,
        )
        self.work.tags.add(ensure_tag("Demo"))

    def test_only_admin_can_create_work_for_now(self):
        member = User.objects.create_user("member", password=PASSWORD)
        self.client.force_authenticate(member)
        response = self.client.post(
            "/api/works/",
            {"title": "not allowed", "summary": "x"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.author)
        response = self.client.post(
            "/api/works/",
            {
                "title": "allowed",
                "summary": "x",
                "cost_piger": 0,
                "status": "draft",
                "tags": ["Django"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Work.objects.count(), 2)

    def test_create_work_requires_tags(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(
            "/api/works/",
            {"title": "missing tags", "summary": "x"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("tags", response.json())

    def test_public_list_only_contains_published_works(self):
        Work.objects.create(
            title="draft",
            author=self.author,
            status="draft",
        )
        response = self.client.get("/api/works/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["title"], "demo")
        self.assertEqual(response.json()["results"][0]["tags"], ["Demo"])
        self.assertEqual(
            response.json()["results"][0]["author"]["username"], "author"
        )

    def test_draft_is_hidden_from_public_but_visible_to_author(self):
        self.work.status = "draft"
        self.work.save()

        response = self.client.get(f"/api/works/{self.work.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        other = User.objects.create_user("other", password=PASSWORD)
        self.client.force_authenticate(other)
        response = self.client.get(f"/api/works/{self.work.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(self.author)
        response = self.client.get(f"/api/works/{self.work.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class SourceAndUnlockTests(APITestCase):
    def setUp(self):
        self.author = User.objects.create_superuser(
            "author", password=PASSWORD
        )
        self.work = Work.objects.create(
            title="demo",
            summary="public summary",
            content="private detail",
            cost_piger=2,
            status="published",
            author=self.author,
        )
        self.work.tags.add(ensure_tag("Demo"))
        self.client.force_authenticate(self.author)
        response = self.client.post(
            f"/api/works/{self.work.id}/source/",
            {"file": make_project_zip()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.source_response = response.json()

    def test_upload_zip_builds_directory_tree(self):
        self.assertEqual(self.source_response["source_file_count"], 3)
        self.assertTrue(self.source_response["can_view_source"])
        main_node = find_file_node(self.source_response["source_tree"], "main.py")
        self.assertIsNotNone(main_node)
        self.assertEqual(main_node["path"], "src/main.py")
        self.assertTrue(main_node["is_text"])

    def test_work_detail_returns_version_and_archive_download_info(self):
        WorkVersion.objects.create(
            work=self.work,
            version="v1.0.0",
            changelog="第一个版本",
        )

        response = self.client.get(f"/api/works/{self.work.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["source_download_url"],
            f"/api/works/{self.work.id}/source/download/",
        )
        self.assertEqual(response.json()["versions"][0]["version"], "v1.0.0")

    def test_download_work_source_archive_requires_unlock(self):
        self.client.force_authenticate(None)

        response = self.client.get(f"/api/works/{self.work.id}/source/download/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.author)
        response = self.client.get(f"/api/works/{self.work.id}/source/download/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/zip")
        archive_data = b"".join(response.streaming_content)
        with zipfile.ZipFile(BytesIO(archive_data)) as archive:
            self.assertEqual(
                archive.namelist(),
                ["README.md", "src/logo.png", "src/main.py"],
            )
            self.assertEqual(archive.read("README.md"), b"# Demo project\n")

    def test_paid_source_is_hidden_until_unlocked(self):
        self.client.post(
            "/api/auth/register/",
            {"username": "buyer", "password": PASSWORD},
            format="json",
        )
        buyer = User.objects.get(username="buyer")
        self.client.force_authenticate(buyer)

        response = self.client.get(f"/api/works/{self.work.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["can_view_source"])
        self.assertIsNone(response.json()["content"])

        main_node = find_file_node(self.source_response["source_tree"], "main.py")
        response = self.client.get(
            f"/api/works/{self.work.id}/source-files/{main_node['file_id']}/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unlock_deducts_once_and_grants_permanent_access(self):
        self.client.post(
            "/api/auth/register/",
            {"username": "buyer", "password": PASSWORD},
            format="json",
        )
        buyer = User.objects.get(username="buyer")
        self.client.force_authenticate(buyer)

        response = self.client.post(f"/api/works/{self.work.id}/unlock/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        buyer.refresh_from_db()
        self.assertEqual(buyer.piger_balance, 3)

        main_node = find_file_node(self.source_response["source_tree"], "main.py")
        response = self.client.get(
            f"/api/works/{self.work.id}/source-files/{main_node['file_id']}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["content"], 'print("hello")\n')

        self.client.post(f"/api/works/{self.work.id}/unlock/")
        buyer.refresh_from_db()
        self.assertEqual(buyer.piger_balance, 3)
        self.assertEqual(
            PigerTransaction.objects.filter(
                user=buyer, reason="unlock"
            ).count(),
            1,
        )

    def test_invalid_zip_is_rejected(self):
        response = self.client.post(
            f"/api/works/{self.work.id}/source/",
            {
                "file": SimpleUploadedFile(
                    "bad.zip", b"not a zip", content_type="application/zip"
                )
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CorsTests(APITestCase):
    def test_allowed_dev_origin_gets_cors_headers(self):
        response = self.client.get(
            "/api/categories/", HTTP_ORIGIN="http://localhost:5173"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response["Access-Control-Allow-Origin"], "http://localhost:5173"
        )


class CategoryTests(APITestCase):
    def test_default_categories_are_tools_code_and_games(self):
        response = self.client.get("/api/categories/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [category["name"] for category in response.json()["results"]],
            ["工具", "代码", "游戏"],
        )


class ProfileAndOverviewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "member",
            password=PASSWORD,
            bio="Building useful web tools.",
        )
        self.user.skills.add(ensure_tag("Django"), ensure_tag("Python"))
        self.admin = User.objects.create_superuser(
            "owner",
            password=PASSWORD,
            bio="Personal works and source.",
        )
        self.admin.skills.add(ensure_tag("Django"), ensure_tag("Product Design"))

        self.work = Work.objects.create(
            title="owned work",
            summary="public summary",
            status="published",
            author=self.admin,
        )
        self.work.tags.add(ensure_tag("Django"))
        WorkSourceFile.objects.create(
            work=self.work,
            path="README.md",
            file="work-sources/test.txt",
            size=10,
        )

    def test_overview_returns_owner_profile_and_site_counts(self):
        response = self.client.get("/api/site/overview/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["profile"]["username"], "owner")
        self.assertEqual(response.json()["profile"]["skills"], ["Django", "Product Design"])
        self.assertEqual(response.json()["work_count"], 1)
        self.assertEqual(response.json()["source_file_count"], 1)

    def test_work_author_contains_profile(self):
        response = self.client.get("/api/works/")

        author = response.json()["results"][0]["author"]
        self.assertEqual(author["id"], self.admin.id)
        self.assertEqual(author["bio"], "Personal works and source.")
        self.assertEqual(author["skills"], ["Django", "Product Design"])

    def test_works_can_filter_by_tag(self):
        response = self.client.get("/api/works/", {"tag": "Django"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        response = self.client.get("/api/works/", {"tag": "not-exists"})
        self.assertEqual(response.json()["count"], 0)

    def test_user_can_update_own_profile_with_avatar_and_skills(self):
        self.client.force_authenticate(self.user)

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=Path(media_root)):
                response = self.client.patch(
                    "/api/auth/me/profile/",
                    {
                        "bio": "Full-stack developer.",
                        "skills": "Python, Django, Vue",
                        "avatar": SimpleUploadedFile(
                            "avatar.png", AVATAR_PNG, content_type="image/png"
                        ),
                    },
                    format="multipart",
                )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["bio"], "Full-stack developer.")
        self.assertEqual(
            response.json()["skills"], ["Django", "Python", "Vue"]
        )
        self.assertIn("avatars/", response.json()["avatar"])

    def test_user_can_update_profile_without_skills(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            "/api/auth/me/profile/",
            {"bio": "Building useful web tools.", "skills": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["skills"], [])


class HomePageTests(SimpleTestCase):
    def test_home_page_returns_frontend_template(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, 'Woodenpiger 作品站')
        self.assertContains(response, '/static/market/css/app.css')
        self.assertContains(response, '/static/market/js/app.js')
        self.assertNotContains(response, 'id="starfield"')


class AdminTests(APITestCase):
    def test_admin_dashboard_renders_aggregated_stats(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        author = User.objects.create_user("author", password=PASSWORD)
        published = Work.objects.create(
            title="published work",
            author=author,
            status="published",
        )
        Work.objects.create(title="draft work", author=author, status="draft")
        self.client.force_login(admin_user)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, "核心数据")
        self.assertContains(response, "2")
        self.assertContains(response, "published work")

    def test_work_publish_form_integrates_source_archive(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        author = User.objects.create_user("author", password=PASSWORD)
        tag = Tag.objects.create(name="AdminZip")
        work = Work.objects.create(
            title="admin publish work",
            author=author,
            status="draft",
        )
        work.tags.add(tag)
        self.client.force_login(admin_user)

        add_response = self.client.get("/admin/market/work/add/")
        self.assertEqual(add_response.status_code, status.HTTP_200_OK)
        self.assertContains(add_response, 'name="source_archive"')
        self.assertContains(add_response, 'data-max-size="524288000"')
        self.assertContains(add_response, "woodenpiger-work-publish.js")

        storage = WorkSourceFile._meta.get_field("file").storage
        with tempfile.TemporaryDirectory() as private_root:
            with patch.object(storage, "location", Path(private_root)):
                response = self.client.post(
                    f"/admin/market/work/{work.id}/change/",
                    {
                        "title": "admin publish work",
                        "summary": "published with source",
                        "content": "source included",
                        "author": author.id,
                        "status": "published",
                        "cost_piger": 0,
                        "tags": [tag.id],
                        "source_archive": make_project_zip(),
                        "source_files-TOTAL_FORMS": "0",
                        "source_files-INITIAL_FORMS": "0",
                        "source_files-MIN_NUM_FORMS": "0",
                        "source_files-MAX_NUM_FORMS": "0",
                    },
                    format="multipart",
                )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            WorkSourceFile.objects.filter(work=work).count(), 3
        )

    def test_work_publish_uses_readme_as_summary_when_summary_is_empty(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        author = User.objects.create_user("author", password=PASSWORD)
        tag = Tag.objects.create(name="AdminReadme")
        work = Work.objects.create(
            title="auto summary work",
            author=author,
            status="draft",
        )
        self.client.force_login(admin_user)

        storage = WorkSourceFile._meta.get_field("file").storage
        with tempfile.TemporaryDirectory() as private_root:
            with patch.object(storage, "location", Path(private_root)):
                response = self.client.post(
                    f"/admin/market/work/{work.id}/change/",
                    {
                        "title": "auto summary work",
                        "summary": "",
                        "content": "",
                        "author": author.id,
                        "status": "published",
                        "cost_piger": 0,
                        "tags": [tag.id],
                        "source_archive": make_project_zip(),
                        "source_files-TOTAL_FORMS": "0",
                        "source_files-INITIAL_FORMS": "0",
                        "source_files-MIN_NUM_FORMS": "0",
                        "source_files-MAX_NUM_FORMS": "0",
                    },
                    format="multipart",
                )

        self.assertEqual(response.status_code, 302)
        work.refresh_from_db()
        self.assertEqual(work.summary, "# Demo project")

    def test_work_publish_uses_single_markdown_file_from_markdown_folder(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        author = User.objects.create_user("author", password=PASSWORD)
        tag = Tag.objects.create(name="AdminMarkdown")
        work = Work.objects.create(
            title="markdown folder work",
            author=author,
            status="draft",
        )
        self.client.force_login(admin_user)

        storage = WorkSourceFile._meta.get_field("file").storage
        with tempfile.TemporaryDirectory() as private_root:
            with patch.object(storage, "location", Path(private_root)):
                response = self.client.post(
                    f"/admin/market/work/{work.id}/change/",
                    {
                        "title": "markdown folder work",
                        "summary": "",
                        "content": "",
                        "author": author.id,
                        "status": "published",
                        "cost_piger": 0,
                        "tags": [tag.id],
                        "source_archive": make_markdown_folder_zip(),
                        "source_files-TOTAL_FORMS": "0",
                        "source_files-INITIAL_FORMS": "0",
                        "source_files-MIN_NUM_FORMS": "0",
                        "source_files-MAX_NUM_FORMS": "0",
                    },
                    format="multipart",
                )

        self.assertEqual(response.status_code, 302)
        work.refresh_from_db()
        self.assertEqual(work.summary, "# Folder summary")

    def test_work_publish_uses_text_summary_when_markdown_is_absent(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        author = User.objects.create_user("author", password=PASSWORD)
        tag = Tag.objects.create(name="AdminText")
        self.client.force_login(admin_user)

        storage = WorkSourceFile._meta.get_field("file").storage
        with tempfile.TemporaryDirectory() as private_root:
            with patch.object(storage, "location", Path(private_root)):
                response = self.client.post(
                    "/admin/market/work/add/",
                    {
                        "title": "text summary work",
                        "summary": "",
                        "content": "",
                        "author": author.id,
                        "status": "published",
                        "cost_piger": 0,
                        "tags": [tag.id],
                        "source_archive": make_text_summary_zip(),
                        "source_files-TOTAL_FORMS": "0",
                        "source_files-INITIAL_FORMS": "0",
                        "source_files-MIN_NUM_FORMS": "0",
                        "source_files-MAX_NUM_FORMS": "0",
                    },
                    format="multipart",
                )

        self.assertEqual(response.status_code, 302)
        work = Work.objects.get(title="text summary work")
        self.assertEqual(work.summary, "GGBOY 文本简介")
        self.assertEqual(work.source_files.count(), 2)

    def test_work_publish_requires_source_archive_on_add(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        author = User.objects.create_user("author", password=PASSWORD)
        tag = Tag.objects.create(name="AdminRequiredZip")
        self.client.force_login(admin_user)

        response = self.client.post(
            "/admin/market/work/add/",
            {
                "title": "empty source work",
                "summary": "",
                "content": "",
                "author": author.id,
                "status": "published",
                "cost_piger": 0,
                "tags": [tag.id],
                "source_files-TOTAL_FORMS": "0",
                "source_files-INITIAL_FORMS": "0",
                "source_files-MIN_NUM_FORMS": "0",
                "source_files-MAX_NUM_FORMS": "0",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Work.objects.filter(title="empty source work").count(), 0)

    def test_work_publish_shows_error_when_uncompressed_size_exceeds_limit(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        author = User.objects.create_user("author", password=PASSWORD)
        tag = Tag.objects.create(name="AdminSizeLimit")
        self.client.force_login(admin_user)

        buffer = BytesIO()
        with zipfile.ZipFile(
            buffer, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                "demo-project/main.py", b"0" * (2 * 1024 * 1024)
            )
        uploaded = SimpleUploadedFile(
            "project.zip",
            buffer.getvalue(),
            content_type="application/zip",
        )

        with patch.multiple(
            "market.services",
            MAX_SOURCE_FILE_SIZE=3 * 1024 * 1024,
            MAX_SOURCE_TOTAL_SIZE=1024 * 1024,
        ):
            response = self.client.post(
                "/admin/market/work/add/",
                {
                    "title": "oversized source work",
                    "summary": "",
                    "content": "",
                    "author": author.id,
                    "status": "published",
                    "cost_piger": 0,
                    "tags": [tag.id],
                    "source_archive": uploaded,
                    "source_files-TOTAL_FORMS": "0",
                    "source_files-INITIAL_FORMS": "0",
                    "source_files-MIN_NUM_FORMS": "0",
                    "source_files-MAX_NUM_FORMS": "0",
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "解压后源码总大小超过 1MB")
        self.assertEqual(
            Work.objects.filter(title="oversized source work").count(), 0
        )

    def test_work_search_page_filters_by_keyword(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        author = User.objects.create_user("author", password=PASSWORD)
        alpha = Work.objects.create(
            title="Alpha Django tool",
            author=author,
            status="published",
        )
        alpha.tags.add(ensure_tag("Django"))
        beta = Work.objects.create(title="Beta game", author=author, status="draft")
        beta.tags.add(ensure_tag("Game"))
        self.client.force_login(admin_user)

        response = self.client.get("/admin/market/work/search/", {"q": "alpha"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, "作品查询")
        self.assertContains(response, "Alpha Django tool")
        self.assertNotContains(response, "Beta game")
        self.assertContains(response, "共 1 个作品")

    def test_source_files_are_not_a_separate_admin_module(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        self.client.force_login(admin_user)

        response = self.client.get("/admin/market/worksourcefile/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_change_page_has_no_plaintext_password_field(self):
        admin_user = User.objects.create_superuser("admin", password=PASSWORD)
        target = User.objects.create_user("target", password=PASSWORD)
        self.client.force_login(admin_user)

        response = self.client.get(f"/admin/market/user/{target.id}/change/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotContains(response, 'name="password"')
