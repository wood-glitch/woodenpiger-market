from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.http import FileResponse
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from pathlib import PurePosixPath
import shutil
import zipfile
from tempfile import SpooledTemporaryFile
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

from .models import Category, Work, WorkImage, WorkSourceFile
from .serializers import (
    CategorySerializer,
    PigerTransactionSerializer,
    AuthorProfileSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    UserSerializer,
    WorkImageSerializer,
    WorkListSerializer,
    WorkSerializer,
)
from .services import (
    ServiceError,
    daily_checkin,
    delete_work_source,
    replace_work_source,
    unlock_work,
    user_can_manage_work,
    user_can_view_source,
)

User = get_user_model()


def _work_base_queryset():
    return (
        Work.objects
        .select_related("author", "category")
        .prefetch_related("images", "tags", "author__skills", "versions")
        .annotate(source_file_count=Count("source_files"))
        .order_by("-created_at")
    )


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]


class WorkViewSet(viewsets.ModelViewSet):
    queryset = _work_base_queryset()
    filterset_fields = ["category"]
    search_fields = ["title", "summary"]
    ordering_fields = ["cost_piger", "created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return WorkListSerializer
        return WorkSerializer

    def get_permissions(self):
        if self.action == "create":
            return [permissions.IsAdminUser()]
        if self.action in {"update", "partial_update", "destroy"}:
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # 优化：批量获取用户解锁状态，防止列表接口出现 N+1 查询
        if self.request.user.is_authenticated:
            from django.db.models import Exists, OuterRef
            from .models import Unlock
            unlocked = Unlock.objects.filter(user=self.request.user, work=OuterRef('pk'))
            queryset = queryset.annotate(is_unlocked_by_user=Exists(unlocked))

        if self.action == "list":
            queryset = queryset.filter(status="published")
            tag_name = self.request.query_params.get("tag")
            if tag_name:
                queryset = queryset.filter(tags__name=tag_name).distinct()
            return queryset
        if self.action == "retrieve":
            if self.request.user.is_authenticated:
                return queryset.filter(
                    Q(status="published") | Q(author=self.request.user)
                )
            return queryset.filter(status="published")
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def perform_update(self, serializer):
        if not user_can_manage_work(self.request.user, serializer.instance):
            raise PermissionDenied("只能修改自己发布的作品")
        serializer.save()

    def perform_destroy(self, instance):
        if not user_can_manage_work(self.request.user, instance):
            raise PermissionDenied("只能删除自己发布的作品")
        delete_work_source(instance)
        for image in instance.images.all():
            image.image.delete(save=False)
        instance.delete()


class WorkImageView(generics.CreateAPIView):
    serializer_class = WorkImageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        work = get_object_or_404(Work, id=self.kwargs["work_id"])
        if not user_can_manage_work(self.request.user, work):
            raise PermissionDenied("只能上传自己作品的图片")
        serializer.save(work=work)


class WorkImageDeleteView(generics.DestroyAPIView):
    serializer_class = WorkImageSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "image_id"

    def get_queryset(self):
        return WorkImage.objects.filter(
            work_id=self.kwargs["work_id"]
        ).select_related("work__author")

    def perform_destroy(self, instance):
        if not user_can_manage_work(self.request.user, instance.work):
            raise PermissionDenied("只能删除自己作品的图片")
        instance.image.delete(save=False)
        instance.delete()


class MeWorkListView(generics.ListAPIView):
    serializer_class = WorkListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        from django.db.models import Exists, OuterRef
        from .models import Unlock
        unlocked = Unlock.objects.filter(user=self.request.user, work=OuterRef('pk'))
        
        return _work_base_queryset().filter(author=self.request.user).annotate(
            is_unlocked_by_user=Exists(unlocked)
        )


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # Bypass SessionAuthentication to prevent CSRF error for anonymous users


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class MeProfileUpdateView(generics.UpdateAPIView):
    serializer_class = ProfileUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_object(self):
        return self.request.user


class SiteOverviewView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        owner = (
            User.objects.filter(is_superuser=True, is_active=True)
            .prefetch_related("skills")
            .order_by("id")
            .first()
        )
        return Response(
            {
                "profile": (
                    AuthorProfileSerializer(owner, context={"request": request}).data
                    if owner
                    else None
                ),
                "work_count": Work.objects.filter(status="published").count(),
                "source_file_count": WorkSourceFile.objects.filter(
                    work__status="published"
                ).count(),
            }
        )


class CheckInStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        return Response(
            {
                "date": today,
                "has_checked_in": request.user.checkins.filter(
                    checkin_date=today
                ).exists(),
                "piger_balance": request.user.piger_balance,
            }
        )


class CheckInView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            user = daily_checkin(request.user)
        except ServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(UserSerializer(user).data)


class WalletView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        transactions = request.user.piger_transactions.select_related("work")[:20]
        return Response(
            {
                **UserSerializer(request.user).data,
                "transactions": PigerTransactionSerializer(
                    transactions, many=True
                ).data,
            }
        )


class WorkUnlockView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, work_id):
        work = get_object_or_404(_work_base_queryset(), id=work_id)
        if work.status != "published" and not user_can_manage_work(request.user, work):
            raise PermissionDenied("作品不存在")
        try:
            user, _unlock, _created = unlock_work(request.user, work)
        except ServiceError as exc:
            raise ValidationError({"detail": str(exc)})
        request.user = user
        return Response(WorkSerializer(work, context={"request": request}).data)


class WorkSourceUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, work_id):
        work = get_object_or_404(_work_base_queryset(), id=work_id)
        if not user_can_manage_work(request.user, work):
            raise PermissionDenied("只能上传自己作品的源码")

        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            raise ValidationError({"file": "请上传 ZIP 源码包"})
        try:
            replace_work_source(work, uploaded_file)
        except ServiceError as exc:
            raise ValidationError({"file": str(exc)})
        work.refresh_from_db()
        queryset = _work_base_queryset().get(id=work.id)
        return Response(
            WorkSerializer(queryset, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class WorkSourceDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, work_id):
        work = get_object_or_404(Work, id=work_id)
        if not user_can_manage_work(request.user, work):
            raise PermissionDenied("只能删除自己作品的源码")
        delete_work_source(work)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkSourceFileContentView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, work_id, source_file_id):
        work = get_object_or_404(_work_base_queryset(), id=work_id)
        if work.status != "published" and not user_can_manage_work(request.user, work):
            raise PermissionDenied("作品不存在")
        source_file = get_object_or_404(
            WorkSourceFile, id=source_file_id, work=work
        )
        if not user_can_view_source(request.user, work):
            raise PermissionDenied("需要解锁后才能查看源码")

        content = None
        if source_file.is_text:
            with source_file.file.open("rb") as file_object:
                raw_content = file_object.read()
            
            for encoding in ("utf-8-sig", "gb18030", "utf-16"):
                try:
                    content = raw_content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                source_file.is_text = False
                source_file.save(update_fields=["is_text"])

        return Response(
            {
                "id": source_file.id,
                "path": source_file.path,
                "size": source_file.size,
                "is_text": source_file.is_text,
                "content": content,
                "download_url": (
                    f"/api/works/{work.id}/source-files/{source_file.id}/download/"
                ),
            }
        )


class WorkSourceFileDownloadView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, work_id, source_file_id):
        work = get_object_or_404(_work_base_queryset(), id=work_id)
        if work.status != "published" and not user_can_manage_work(request.user, work):
            raise PermissionDenied("作品不存在")
        source_file = get_object_or_404(
            WorkSourceFile, id=source_file_id, work=work
        )
        if not user_can_view_source(request.user, work):
            raise PermissionDenied("需要解锁后才能下载源码")

        response = FileResponse(
            source_file.file.open("rb"),
            as_attachment=True,
            filename=PurePosixPath(source_file.path).name,
        )
        response["Content-Length"] = source_file.size
        return response


class WorkSourceArchiveDownloadView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, work_id):
        work = get_object_or_404(_work_base_queryset(), id=work_id)
        if work.status != "published" and not user_can_manage_work(request.user, work):
            raise PermissionDenied("作品不存在")
        if not user_can_view_source(request.user, work):
            raise PermissionDenied("需要解锁后才能下载源码")

        source_files = list(work.source_files.order_by("path"))
        if not source_files:
            raise Http404("这个作品还没有源码文件")

        archive_file = SpooledTemporaryFile(
            max_size=8 * 1024 * 1024, mode="w+b"
        )
        try:
            with zipfile.ZipFile(
                archive_file, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for source_file in source_files:
                    with source_file.file.open("rb") as file_object, archive.open(
                        source_file.path, "w"
                    ) as archive_member:
                        shutil.copyfileobj(
                            file_object, archive_member, length=1024 * 1024
                        )

            archive_size = archive_file.seek(0, 2)
            archive_file.seek(0)
        except Exception:
            archive_file.close()
            raise

        response = FileResponse(
            archive_file,
            as_attachment=True,
            filename=f"{work.title}.zip",
            content_type="application/zip",
        )
        response["Content-Length"] = archive_size
        return response
