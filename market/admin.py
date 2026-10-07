from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html

from .admin_site import WoodenpigerAdminSite
from .models import (
    Category,
    CheckIn,
    PigerTransaction,
    Unlock,
    Tag,
    User,
    Work,
    WorkImage,
    WorkSourceFile,
    WorkVersion,
)
from .services import (
    MAX_SOURCE_TOTAL_SIZE,
    ServiceError,
    replace_work_source,
    validate_source_archive,
)


woodenpiger_admin_site = WoodenpigerAdminSite(name="woodenpiger_admin")


class MarketUserAdmin(UserAdmin):
    list_display = (
        "username", "email", "piger_balance", "is_staff", "is_active",
        "date_joined",
    )
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email")
    ordering = ("-date_joined",)
    filter_horizontal = ("groups", "user_permissions", "skills")
    fieldsets = (
        (
            "账号信息",
            {"fields": ("username", "password")},
        ),
        (
            "联系方式",
            {"fields": ("email", "first_name", "last_name")},
        ),
        (
            "个人资料",
            {"fields": ("avatar", "bio", "skills")},
        ),
        (
            "piger",
            {"fields": ("piger_balance",)},
        ),
        (
            "权限",
            {
                "fields": (
                    "is_active", "is_staff", "is_superuser", "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "重要日期",
            {"fields": ("last_login", "date_joined")},
        ),
    )
    add_fieldsets = (
        (
            "创建用户",
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
    )


class WorkPublishForm(forms.ModelForm):
    source_archive = forms.FileField(
        label="源码包",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".zip",
                "data-max-size": MAX_SOURCE_TOTAL_SIZE,
            }
        ),
        help_text=(
            "请选择压缩包。新增作品时必填；压缩包和解压后源码都不能超过 500MB，"
            "超过限制会在保存时提示。"
            "简介为空时自动使用 README、Markdown 或说明类 TXT 内容。"
        ),
    )

    class Media:
        js = ("admin/js/woodenpiger-work-publish.js",)

    def clean_source_archive(self):
        source_archive = self.cleaned_data.get("source_archive")
        if not source_archive:
            return source_archive
        try:
            validate_source_archive(source_archive)
        except ServiceError as exc:
            raise forms.ValidationError(str(exc))
        return source_archive

    class Meta:
        model = Work
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["summary"].help_text = (
            "留空时，保存 ZIP 后会自动使用 README、Markdown 或说明类 TXT 内容。"
        )
        if not self.instance.pk:
            self.fields["source_archive"].required = True


class WorkSourceFileInline(admin.TabularInline):
    model = WorkSourceFile
    fields = ("path", "size", "is_text")
    readonly_fields = fields
    can_delete = False
    extra = 0
    max_num = 0
    verbose_name_plural = "已导入源码文件"


class WorkVersionInline(admin.TabularInline):
    model = WorkVersion
    fields = ("version", "changelog", "released_at")
    readonly_fields = ("released_at",)
    extra = 0
    verbose_name_plural = "版本更新"


class WorkAdmin(admin.ModelAdmin):
    form = WorkPublishForm
    inlines = (WorkSourceFileInline, WorkVersionInline)
    list_display = (
        "title", "author", "category", "cost_piger", "status_label",
        "source_file_count", "created_at",
    )
    list_filter = ("status", "category", "author")
    search_fields = ("title", "summary", "content", "author__username")
    ordering = ("-created_at",)
    list_select_related = ("author", "category")
    raw_id_fields = ("author",)
    date_hierarchy = "created_at"
    filter_horizontal = ("tags",)
    list_per_page = 20
    actions = ("make_published", "make_archived")
    fieldsets = (
        (
            "作品信息",
            {"fields": ("title", "summary", "content", "category", "tags")},
        ),
        (
            "发布设置",
            {"fields": ("author", "status", "cost_piger")},
        ),
        (
            "源码包",
            {"fields": ("source_archive",)},
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            source_file_count=Count("source_files")
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_url = path(
            "search/",
            self.admin_site.admin_view(self.work_search_view),
            name="market_work_search",
        )
        return [custom_url, *urls]

    def save_model(self, request, obj, form, change):
        source_archive = form.cleaned_data.get("source_archive")
        try:
            with transaction.atomic():
                super().save_model(request, obj, form, change)
                if source_archive:
                    replace_work_source(
                        obj, source_archive, auto_summary=True
                    )
        except ServiceError as exc:
            form.add_error("source_archive", str(exc))
            raise

    def work_search_view(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied

        queryset = self.get_queryset(request).prefetch_related("tags")
        keyword = request.GET.get("q", "").strip()
        status = request.GET.get("status", "").strip()
        category_id = request.GET.get("category", "").strip()
        tag_id = request.GET.get("tag", "").strip()

        if keyword:
            queryset = queryset.filter(
                Q(title__icontains=keyword)
                | Q(summary__icontains=keyword)
                | Q(content__icontains=keyword)
                | Q(author__username__icontains=keyword)
            )
        if status:
            queryset = queryset.filter(status=status)
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if tag_id:
            queryset = queryset.filter(tags__id=tag_id)

        context = dict(
            self.admin_site.each_context(request),
            title="作品查询",
            filters={
                "q": keyword,
                "status": status,
                "category": category_id,
                "tag": tag_id,
            },
            categories=Category.objects.all(),
            tags=Tag.objects.all(),
            works=queryset.order_by("-updated_at")[:100],
            result_count=queryset.count(),
        )
        return TemplateResponse(
            request,
            "admin/woodenpiger/work_search.html",
            context,
        )

    @admin.display(description="状态")
    def status_label(self, obj):
        css_class = {
            "published": "wp-badge wp-badge-success",
            "draft": "wp-badge wp-badge-warning",
            "archived": "wp-badge wp-badge-muted",
        }.get(obj.status, "wp-badge")
        return format_html(
            '<span class="{}">{}</span>', css_class, obj.get_status_display()
        )

    @admin.display(description="源码文件数", ordering="source_file_count")
    def source_file_count(self, obj):
        return obj.source_file_count

    @admin.action(description="标记为已发布")
    def make_published(self, request, queryset):
        queryset.update(status="published")

    @admin.action(description="标记为已归档")
    def make_archived(self, request, queryset):
        queryset.update(status="archived")


class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "work_count")
    search_fields = ("name",)
    ordering = ("name",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(work_count=Count("works"))

    @admin.display(description="作品数量", ordering="work_count")
    def work_count(self, obj):
        return obj.work_count


class WorkImageAdmin(admin.ModelAdmin):
    list_display = ("work", "image", "uploaded_at")
    search_fields = ("work__title",)
    raw_id_fields = ("work",)
    list_select_related = ("work",)
    ordering = ("-uploaded_at",)


class CheckInAdmin(admin.ModelAdmin):
    list_display = ("user", "checkin_date", "created_at")
    date_hierarchy = "checkin_date"
    search_fields = ("user__username",)
    raw_id_fields = ("user",)


class PigerTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "user", "amount", "balance_after", "reason", "work", "created_at"
    )
    list_filter = ("reason",)
    search_fields = ("user__username", "work__title")
    raw_id_fields = ("user", "work")
    list_select_related = ("user", "work")
    ordering = ("-created_at",)


class UnlockAdmin(admin.ModelAdmin):
    list_display = ("user", "work", "created_at")
    search_fields = ("user__username", "work__title")
    raw_id_fields = ("user", "work")
    list_select_related = ("user", "work")
    ordering = ("-created_at",)


woodenpiger_admin_site.register(User, MarketUserAdmin)
woodenpiger_admin_site.register(Tag)
woodenpiger_admin_site.register(Work, WorkAdmin)
woodenpiger_admin_site.register(Category, CategoryAdmin)
woodenpiger_admin_site.register(WorkImage, WorkImageAdmin)
woodenpiger_admin_site.register(CheckIn, CheckInAdmin)
woodenpiger_admin_site.register(PigerTransaction, PigerTransactionAdmin)
woodenpiger_admin_site.register(Unlock, UnlockAdmin)
