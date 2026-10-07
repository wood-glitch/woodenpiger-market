from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """源码文件存储：不允许通过公开 URL 直接访问。"""

    def __init__(self, **kwargs):
        super().__init__(
            location=settings.PRIVATE_ROOT,
            base_url=None,
            **kwargs,
        )

    def url(self, name):
        raise ValueError("私有源码文件必须通过授权接口访问")
