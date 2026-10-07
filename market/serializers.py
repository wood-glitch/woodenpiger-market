from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    Category,
    PigerTransaction,
    Tag,
    Work,
    WorkImage,
    WorkVersion,
    Unlock,
)
from .services import (
    build_source_tree,
    create_registered_user,
    user_can_manage_work,
    user_can_view_source,
)

User = get_user_model()


class TagNamesField(serializers.Field):
    """把前端传来的标签数组同步成 Tag 关联。"""

    def __init__(self, *args, **kwargs):
        self.allow_empty = kwargs.pop("allow_empty", False)
        super().__init__(*args, **kwargs)

    default_error_messages = {
        "invalid": "标签必须是数组，例如 [\"Django\", \"Python\"]。",
        "empty": "至少填写一个标签。",
    }

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = [name.strip() for name in data.split(",") if name.strip()]
        if not isinstance(data, list):
            self.fail("invalid")
        if not data:
            if self.allow_empty:
                return []
            self.fail("empty")

        names = []
        for name in data:
            if not isinstance(name, str):
                self.fail("invalid")
            name = name.strip()
            if not name:
                self.fail("invalid")
            if len(name) > 30:
                raise serializers.ValidationError(f"标签不能超过 30 个字符: {name}")
            if name not in names:
                names.append(name)
        if len(names) > 8:
            raise serializers.ValidationError("标签数量不能超过 8 个")
        return names

    def to_representation(self, value):
        tags = value.all() if hasattr(value, "all") else value
        return [tag.name for tag in tags]


def sync_tags(instance, names, relation_name="tags"):
    if not names:
        getattr(instance, relation_name).clear()
        return

    # 1. 查出已经存在的标签名称
    existing_names = set(Tag.objects.filter(name__in=names).values_list("name", flat=True))
    
    # 2. 找出缺失的标签并批量创建
    missing_names = [name for name in names if name not in existing_names]
    if missing_names:
        Tag.objects.bulk_create([Tag(name=name) for name in missing_names], ignore_conflicts=True)
    
    # 3. 重新获取所有相关的标签对象并设置关联
    tags = Tag.objects.filter(name__in=names)
    getattr(instance, relation_name).set(tags)


class AuthorProfileSerializer(serializers.ModelSerializer):
    skills = TagNamesField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "avatar", "bio", "skills"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "username", "password", "piger_balance"]
        read_only_fields = ["piger_balance"]

    def validate(self, attrs):
        user = User(username=attrs.get("username"))
        try:
            validate_password(attrs.get("password"), user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages})
        return attrs

    def create(self, validated_data):
        return create_registered_user(
            username=validated_data["username"],
            password=validated_data["password"],
        )


class UserSerializer(serializers.ModelSerializer):
    skills = TagNamesField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "username", "piger_balance", "avatar", "bio", "skills",
            "is_staff", "is_superuser",
        ]


class ProfileUpdateSerializer(serializers.ModelSerializer):
    skills = TagNamesField(required=False, allow_empty=True)

    class Meta:
        model = User
        fields = ["username", "avatar", "bio", "skills"]
        extra_kwargs = {
            "username": {"required": False},
            "bio": {"required": False},
        }

    def update(self, instance, validated_data):
        skills = validated_data.pop("skills", None)
        instance = super().update(instance, validated_data)
        if skills is not None:
            sync_tags(instance, skills, "skills")
        return instance


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class WorkImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkImage
        fields = ["id", "image", "uploaded_at"]


class WorkVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkVersion
        fields = ["id", "version", "changelog", "released_at"]


class WorkListSerializer(serializers.ModelSerializer):
    author = AuthorProfileSerializer(read_only=True)
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        allow_null=True,
        required=False,
    )
    images = WorkImageSerializer(many=True, read_only=True)
    tags = TagNamesField()
    source_file_count = serializers.IntegerField(read_only=True)
    is_unlocked = serializers.SerializerMethodField()
    can_view_source = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = Work
        fields = [
            "id", "title", "summary", "cost_piger", "status", "author",
            "category", "tags", "images", "source_file_count", "is_unlocked",
            "can_view_source", "can_manage", "created_at", "updated_at",
        ]

    def create(self, validated_data):
        tags = validated_data.pop("tags")
        work = super().create(validated_data)
        sync_tags(work, tags)
        return work

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        work = super().update(instance, validated_data)
        if tags is not None:
            sync_tags(work, tags)
        return work

    def get_is_unlocked(self, work):
        if work.cost_piger == 0:
            return True
        
        # 使用 views.py 中提前 annotate 的字段，避免 N+1 查询
        if hasattr(work, 'is_unlocked_by_user'):
            return work.is_unlocked_by_user

        request = self.context.get("request")
        user = request.user if request else None
        return (
            user is not None
            and user.is_authenticated
            and Unlock.objects.filter(user=user, work=work).exists()
        )

    def get_can_view_source(self, work):
        request = self.context.get("request")
        user = request.user if request else None
        
        # 优化：优先使用提前查询的解锁状态，避免在列表中调用产生 N+1 查询
        if hasattr(work, 'is_unlocked_by_user') and user and user.is_authenticated:
            if work.cost_piger == 0:
                return True
            return user.is_superuser or work.author_id == user.id or work.is_unlocked_by_user

        return user_can_view_source(user, work)

    def get_can_manage(self, work):
        request = self.context.get("request")
        user = request.user if request else None
        return user_can_manage_work(user, work)


class WorkSerializer(WorkListSerializer):
    source_tree = serializers.SerializerMethodField()
    source_download_url = serializers.SerializerMethodField()
    versions = WorkVersionSerializer(many=True, read_only=True)

    class Meta(WorkListSerializer.Meta):
        fields = WorkListSerializer.Meta.fields + [
            "content", "source_tree", "source_download_url", "versions",
        ]

    def get_source_tree(self, work):
        return build_source_tree(work.source_files.all())

    def get_source_download_url(self, work):
        request = self.context.get("request")
        user = request.user if request else None
        if not user_can_view_source(user, work):
            return None
        return f"/api/works/{work.id}/source/download/"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not data["can_view_source"]:
            data["content"] = None
        return data


class PigerTransactionSerializer(serializers.ModelSerializer):
    work = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = PigerTransaction
        fields = [
            "id", "amount", "balance_after", "reason", "work", "created_at",
        ]
