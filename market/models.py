from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models

from .storages import PrivateStorage


class User(AbstractUser):
    """网站用户，piger 余额保存在这里，明细看 PigerTransaction。"""

    piger_balance = models.PositiveIntegerField("piger 余额", default=0)
    avatar = models.ImageField(
        "头像", upload_to="avatars/%Y/%m/", blank=True, null=True
    )
    bio = models.CharField("一句话介绍", max_length=160, blank=True, default="")
    skills = models.ManyToManyField(
        "Tag", blank=True, related_name="users", verbose_name="技能标签"
    )

    class Meta(AbstractUser.Meta):
        verbose_name = "用户"
        verbose_name_plural = "用户"


class Tag(models.Model):
    name = models.CharField("标签名", max_length=30, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "标签"
        verbose_name_plural = "标签"

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField("分类名", max_length=50, unique=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "分类"
        verbose_name_plural = "分类"

    def __str__(self):
        return self.name


class Work(models.Model):
    """作品：可以是源码项目、工具、文档或其他数字资源。"""

    STATUS = [
        ("draft", "草稿"),
        ("published", "已发布"),
        ("archived", "已归档"),
    ]

    title = models.CharField("标题", max_length=150)
    summary = models.TextField("简介", blank=True, default="")
    content = models.TextField("详细说明", blank=True, default="")
    cost_piger = models.PositiveIntegerField(
        "解锁价格", default=0, validators=[MinValueValidator(0)]
    )
    status = models.CharField("状态", max_length=12, choices=STATUS, default="draft")
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="works",
        verbose_name="作者",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="works",
        verbose_name="分类",
    )
    tags = models.ManyToManyField(
        Tag, related_name="works", verbose_name="作品标签", blank=False
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "作品"
        verbose_name_plural = "作品"

    def __str__(self):
        return self.title


class WorkVersion(models.Model):
    """作品版本更新记录，只保存版本号和更新说明。"""

    work = models.ForeignKey(
        Work,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="作品",
    )
    version = models.CharField("版本号", max_length=50)
    changelog = models.TextField("更新说明", blank=True, default="")
    released_at = models.DateTimeField("发布时间", auto_now_add=True)

    class Meta:
        ordering = ["-released_at", "-id"]
        verbose_name = "版本更新"
        verbose_name_plural = "版本更新"
        constraints = [
            models.UniqueConstraint(fields=["work", "version"], name="unique_work_version")
        ]

    def __str__(self):
        return f"{self.work.title} {self.version}"


class WorkImage(models.Model):
    """公开展示的封面或截图，不能当成付费源码文件。"""

    work = models.ForeignKey(
        Work,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name="作品",
    )
    image = models.ImageField("图片", upload_to="works/%Y/%m/")
    uploaded_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        verbose_name = "作品图片"
        verbose_name_plural = "作品图片"

    def __str__(self):
        return f"{self.work.title} 的图片"


class WorkSourceFile(models.Model):
    """从 ZIP 解包出来的源码文件，文件本体放在私有目录。"""

    work = models.ForeignKey(
        Work,
        on_delete=models.CASCADE,
        related_name="source_files",
        verbose_name="作品",
    )
    path = models.CharField("项目内路径", max_length=512)
    file = models.FileField(
        "源码文件", storage=PrivateStorage(), upload_to="work-sources/%Y/%m/"
    )
    size = models.PositiveBigIntegerField("文件大小", default=0)
    is_text = models.BooleanField("是否可在线阅读", default=False)
    uploaded_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        ordering = ["path"]
        verbose_name = "源码文件"
        verbose_name_plural = "源码文件"
        constraints = [
            models.UniqueConstraint(fields=["work", "path"], name="unique_work_source_path")
        ]

    def __str__(self):
        return f"{self.work.title}/{self.path}"


class CheckIn(models.Model):
    """每日手动签到记录。"""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="checkins",
        verbose_name="用户",
    )
    checkin_date = models.DateField("签到日期")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-checkin_date", "-id"]
        verbose_name = "签到记录"
        verbose_name_plural = "签到记录"
        constraints = [
            models.UniqueConstraint(fields=["user", "checkin_date"], name="unique_daily_checkin")
        ]

    def __str__(self):
        return f"{self.user.username} {self.checkin_date}"


class PigerTransaction(models.Model):
    """piger 流水：注册赠送、签到、解锁都会记录一条。"""

    REASONS = [
        ("register", "注册赠送"),
        ("checkin", "每日签到"),
        ("unlock", "解锁作品"),
        ("admin_grant", "管理员调整"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="piger_transactions",
        verbose_name="用户",
    )
    amount = models.IntegerField("变动数量")
    balance_after = models.PositiveIntegerField("变动后余额")
    reason = models.CharField("原因", max_length=20, choices=REASONS)
    work = models.ForeignKey(
        Work,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="piger_transactions",
        verbose_name="相关作品",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "piger 流水"
        verbose_name_plural = "piger 流水"

    def __str__(self):
        return f"{self.user.username} {self.amount} piger ({self.reason})"


class Unlock(models.Model):
    """用户对作品的永久解锁记录。"""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="unlocks",
        verbose_name="用户",
    )
    work = models.ForeignKey(
        Work,
        on_delete=models.CASCADE,
        related_name="unlocks",
        verbose_name="作品",
    )
    created_at = models.DateTimeField("解锁时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "解锁记录"
        verbose_name_plural = "解锁记录"
        constraints = [
            models.UniqueConstraint(fields=["user", "work"], name="unique_user_work_unlock")
        ]

    def __str__(self):
        return f"{self.user.username} 解锁 {self.work.title}"
