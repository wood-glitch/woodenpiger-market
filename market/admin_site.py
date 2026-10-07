from django.contrib import admin
from django.db.models import Count, Q
from django.utils import timezone

from .models import CheckIn, Unlock, User, Work, WorkSourceFile


class WoodenpigerAdminSite(admin.AdminSite):
    site_header = "Woodenpiger 作品站管理后台"
    site_title = "Woodenpiger 后台"
    index_title = "数据概览"
    index_template = "admin/woodenpiger/index.html"

    def index(self, request, extra_context=None):
        today = timezone.localdate()
        work_counts = Work.objects.aggregate(
            total=Count("id"),
            published=Count("id", filter=Q(status="published")),
            draft=Count("id", filter=Q(status="draft")),
        )
        checkin_counts = CheckIn.objects.aggregate(
            today=Count("id", filter=Q(checkin_date=today)),
            total=Count("id"),
        )
        context = {
            "wp_stats": {
                "total_users": User.objects.count(),
                "total_works": work_counts["total"],
                "published_works": work_counts["published"],
                "draft_works": work_counts["draft"],
                "source_files": WorkSourceFile.objects.count(),
                "today_checkins": checkin_counts["today"],
                "total_checkins": checkin_counts["total"],
                "total_unlocks": Unlock.objects.count(),
            },
            "wp_recent_works": Work.objects.select_related(
                "author", "category"
            ).order_by("-created_at")[:8],
        }
        if extra_context:
            context.update(extra_context)
        return super().index(request, extra_context=context)
