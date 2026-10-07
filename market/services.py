import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from .models import (
    CheckIn,
    PigerTransaction,
    Unlock,
    User,
    Work,
    WorkSourceFile,
)


REGISTER_BONUS_PIGER = 5
DAILY_CHECKIN_PIGER = 1
MAX_SOURCE_FILES = 500
MAX_SOURCE_TOTAL_SIZE = 500 * 1024 * 1024
MAX_SOURCE_FILE_SIZE = 500 * 1024 * 1024
MAX_TEXT_FILE_SIZE = 512 * 1024

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
}
IGNORED_FILE_SUFFIXES = {".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib"}
IGNORED_TOP_DIRECTORY_NAMES = {"__MACOSX"}
TEXT_FILE_NAMES = {"dockerfile", "makefile", "license", "readme"}
MARKDOWN_FILE_SUFFIXES = {".md", ".markdown"}
MARKDOWN_SUMMARY_STEMS = {"readme", "index", "intro", "简介"}
PREFERRED_MARKDOWN_DIRECTORIES = {"docs", "doc", "markdown", "md"}
TEXT_SUMMARY_SUFFIXES = {".txt"}
TEXT_SUMMARY_STEMS = {"readme", "index", "intro", "简介", "说明", "description"}
TEXT_FILE_SUFFIXES = {
    ".asp", ".bash", ".bat", ".c", ".cc", ".cfg", ".conf", ".cpp", ".cs",
    ".css", ".env", ".go", ".h", ".hpp", ".htm", ".html", ".ini", ".java",
    ".js", ".json", ".jsx", ".kt", ".less", ".md", ".php", ".ps1", ".py",
    ".rb", ".rs", ".scss", ".sh", ".sql", ".svg", ".toml", ".ts", ".tsx",
    ".txt", ".vue", ".xml", ".yaml", ".yml",
}


class ServiceError(Exception):
    """业务规则不满足时抛出，由接口转换成 400/409。"""


def create_registered_user(username, password):
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            password=password,
            piger_balance=REGISTER_BONUS_PIGER,
        )
        PigerTransaction.objects.create(
            user=user,
            amount=REGISTER_BONUS_PIGER,
            balance_after=REGISTER_BONUS_PIGER,
            reason="register",
        )
    return user


def daily_checkin(user):
    today = timezone.localdate()
    with transaction.atomic():
        current_user = User.objects.select_for_update().get(id=user.id)
        if CheckIn.objects.filter(user=current_user, checkin_date=today).exists():
            raise ServiceError("今天已经签到过了")

        CheckIn.objects.create(user=current_user, checkin_date=today)
        current_user.piger_balance += DAILY_CHECKIN_PIGER
        current_user.save(update_fields=["piger_balance"])
        PigerTransaction.objects.create(
            user=current_user,
            amount=DAILY_CHECKIN_PIGER,
            balance_after=current_user.piger_balance,
            reason="checkin",
        )
        return current_user


def unlock_work(user, work):
    with transaction.atomic():
        current_user = User.objects.select_for_update().get(id=user.id)
        current_work = Work.objects.select_for_update().get(id=work.id)
        unlock = Unlock.objects.filter(user=current_user, work=current_work).first()
        if unlock:
            return current_user, unlock, False

        if current_work.cost_piger == 0:
            unlock = Unlock.objects.create(user=current_user, work=current_work)
            return current_user, unlock, True

        if current_user.piger_balance < current_work.cost_piger:
            raise ServiceError("piger 余额不足")

        current_user.piger_balance -= current_work.cost_piger
        current_user.save(update_fields=["piger_balance"])
        PigerTransaction.objects.create(
            user=current_user,
            amount=-current_work.cost_piger,
            balance_after=current_user.piger_balance,
            reason="unlock",
            work=current_work,
        )
        unlock = Unlock.objects.create(user=current_user, work=current_work)
        return current_user, unlock, True


def user_can_manage_work(user, work):
    return user.is_authenticated and (
        user.is_superuser or work.author_id == user.id
    )


def user_can_view_source(user, work):
    if work.cost_piger == 0:
        return True
    return user.is_authenticated and (
        user.is_superuser
        or work.author_id == user.id
        or Unlock.objects.filter(user=user, work=work).exists()
    )


def _normalize_zip_path(raw_path):
    try:
        raw_path = raw_path.encode("cp437").decode("utf-8")
    except UnicodeEncodeError:
        pass
    except UnicodeDecodeError:
        try:
            raw_path = raw_path.encode("cp437").decode("gbk")
        except UnicodeDecodeError:
            pass

    path = PurePosixPath(raw_path.replace("\\", "/"))
    if path.is_absolute() or not path.parts:
        return None
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ServiceError("ZIP 内包含不安全路径")
    return path.parts


def _strip_common_root(paths):
    if len(paths) < 2:
        return paths
    roots = {path[0] for path in paths}
    if len(roots) == 1 and all(len(path) > 1 for path in paths):
        return [path[1:] for path in paths]
    return paths


def _is_text_source(path, size):
    name = PurePosixPath(path).name.lower()
    suffix = PurePosixPath(path).suffix.lower()
    return size <= MAX_TEXT_FILE_SIZE and (
        suffix in TEXT_FILE_SUFFIXES or name in TEXT_FILE_NAMES
    )


def _summary_file_priority(parts, suffixes, stems):
    name = parts[-1].lower()
    stem = PurePosixPath(name).stem
    if PurePosixPath(name).suffix.lower() not in suffixes:
        return None
    if not any(marker in stem for marker in stems):
        return None

    directory = parts[-2].lower() if len(parts) > 1 else ""
    is_readme = "readme" in stem
    is_preferred_directory = directory in PREFERRED_MARKDOWN_DIRECTORIES
    if is_readme and len(parts) == 1:
        rank = 0
    elif is_readme and is_preferred_directory:
        rank = 1
    elif is_readme:
        rank = 2
    elif is_preferred_directory:
        rank = 3
    else:
        rank = 4
    return rank, len(parts), "/".join(parts).lower()


def _decode_summary_text(data):
    if not data or len(data) > MAX_TEXT_FILE_SIZE or b"\0" in data:
        return ""
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return ""


def _find_work_summary(prepared):
    markdown_named = []
    text_named = []
    markdown_files = []
    text_files = []

    for path, data, _info in prepared:
        parts = tuple(path.split("/"))
        markdown_priority = _summary_file_priority(
            parts, MARKDOWN_FILE_SUFFIXES, MARKDOWN_SUMMARY_STEMS
        )
        text_priority = _summary_file_priority(
            parts, TEXT_SUMMARY_SUFFIXES, TEXT_SUMMARY_STEMS
        )
        if markdown_priority is not None:
            markdown_named.append((markdown_priority, data))
        if text_priority is not None:
            text_named.append((text_priority, data))

        suffix = PurePosixPath(path).suffix.lower()
        if suffix in MARKDOWN_FILE_SUFFIXES:
            markdown_files.append(data)
        if suffix in TEXT_SUMMARY_SUFFIXES:
            text_files.append(data)

    if markdown_named:
        data = min(markdown_named, key=lambda item: item[0])[1]
    elif len(markdown_files) == 1:
        data = markdown_files[0]
    elif text_named:
        data = min(text_named, key=lambda item: item[0])[1]
    elif len(text_files) == 1:
        data = text_files[0]
    else:
        data = None
    return _decode_summary_text(data) if data is not None else ""


def _size_mb(size):
    return size / (1024 * 1024)


def validate_source_archive(uploaded_file):
    if not uploaded_file.name.lower().endswith(".zip"):
        raise ServiceError("目前只支持上传 .zip 源码包")

    uploaded_size = getattr(uploaded_file, "size", None)
    if uploaded_size is not None and uploaded_size > MAX_SOURCE_TOTAL_SIZE:
        limit_mb = MAX_SOURCE_TOTAL_SIZE // (1024 * 1024)
        raise ServiceError(
            f"源码包压缩文件不能超过 {limit_mb}MB，"
            f"当前 {_size_mb(uploaded_size):.1f}MB"
        )

    try:
        archive = zipfile.ZipFile(uploaded_file)
    except zipfile.BadZipFile as exc:
        raise ServiceError("这不是有效的 ZIP 文件") from exc

    with archive:
        file_count = 0
        total_size = 0
        for info in archive.infolist():
            if info.is_dir() or info.flag_bits & 0x1:
                continue

            parts = _normalize_zip_path(info.filename)
            if parts is None:
                continue
            if parts[0] in IGNORED_TOP_DIRECTORY_NAMES:
                continue
            if any(part in IGNORED_DIRECTORY_NAMES for part in parts):
                continue
            if PurePosixPath(*parts).suffix.lower() in IGNORED_FILE_SUFFIXES:
                continue

            file_count += 1
            if file_count > MAX_SOURCE_FILES:
                raise ServiceError(
                    f"源码文件数量不能超过 {MAX_SOURCE_FILES} 个"
                )
            if info.file_size > MAX_SOURCE_FILE_SIZE:
                limit_mb = MAX_SOURCE_FILE_SIZE // (1024 * 1024)
                raise ServiceError(
                    f"单个文件超过 {limit_mb}MB: {info.filename}，"
                    f"当前 {_size_mb(info.file_size):.1f}MB"
                )

            total_size += info.file_size
            if total_size > MAX_SOURCE_TOTAL_SIZE:
                limit_mb = MAX_SOURCE_TOTAL_SIZE // (1024 * 1024)
                raise ServiceError(
                    f"解压后源码总大小超过 {limit_mb}MB，"
                    f"当前 {_size_mb(total_size):.1f}MB"
                )


def replace_work_source(work, uploaded_file, auto_summary=False):
    if not uploaded_file.name.lower().endswith(".zip"):
        raise ServiceError("目前只支持上传 .zip 源码包")
    uploaded_size = getattr(uploaded_file, "size", None)
    if uploaded_size is not None and uploaded_size > MAX_SOURCE_TOTAL_SIZE:
        limit_mb = MAX_SOURCE_TOTAL_SIZE // (1024 * 1024)
        raise ServiceError(
            f"源码包压缩文件不能超过 {limit_mb}MB，"
            f"当前 {_size_mb(uploaded_size):.1f}MB"
        )

    try:
        archive = zipfile.ZipFile(uploaded_file)
    except zipfile.BadZipFile as exc:
        raise ServiceError("这不是有效的 ZIP 文件") from exc

    with archive:
        candidates = []
        seen_paths = set()
        total_size = 0

        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                raise ServiceError("不支持加密 ZIP 文件")

            parts = _normalize_zip_path(info.filename)
            if parts is None:
                continue
            if parts[0] in IGNORED_TOP_DIRECTORY_NAMES:
                continue
            if any(part in IGNORED_DIRECTORY_NAMES for part in parts):
                continue
            if PurePosixPath(*parts).suffix.lower() in IGNORED_FILE_SUFFIXES:
                continue

            candidates.append((parts, info))

        if not candidates:
            raise ServiceError("ZIP 里没有可导入的源码文件")
        if len(candidates) > MAX_SOURCE_FILES:
            raise ServiceError(f"源码文件数量不能超过 {MAX_SOURCE_FILES} 个")

        paths = _strip_common_root([parts for parts, _ in candidates])
        prepared = []
        for parts, (_, info) in zip(paths, candidates):
            path = "/".join(parts)
            if not path or path in seen_paths:
                raise ServiceError("ZIP 内存在重复文件路径")
            seen_paths.add(path)

            size = info.file_size
            if size > MAX_SOURCE_FILE_SIZE:
                limit_mb = MAX_SOURCE_FILE_SIZE // (1024 * 1024)
                raise ServiceError(
                    f"单个文件超过 {limit_mb}MB: {path}，"
                    f"当前 {_size_mb(size):.1f}MB"
                )
            total_size += size
            if total_size > MAX_SOURCE_TOTAL_SIZE:
                max_size_mb = MAX_SOURCE_TOTAL_SIZE // (1024 * 1024)
                raise ServiceError(
                    f"解包后源码总大小超过 {max_size_mb}MB，"
                    f"当前 {_size_mb(total_size):.1f}MB"
                )

            try:
                data = archive.read(info)
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                raise ServiceError(f"读取 ZIP 文件失败: {path}") from exc
            if len(data) != size:
                raise ServiceError(f"ZIP 文件大小异常: {path}")

            prepared.append((path, data, info))

        created = []
        try:
            with transaction.atomic():
                if auto_summary and not work.summary:
                    summary = _find_work_summary(prepared)
                    if summary:
                        work.summary = summary
                        work.save(update_fields=["summary"])

                old_files = list(work.source_files.all())
                work.source_files.all().delete()

                records_to_create = []
                for path, data, info in prepared:
                    suffix = PurePosixPath(path).suffix.lower()
                    stored_name = uuid4().hex + (suffix or ".bin")
                    record = WorkSourceFile(
                        work=work,
                        path=path,
                        size=len(data),
                        is_text=_is_text_source(path, len(data)),
                    )
                    record.file.save(
                        stored_name,
                        BytesIO(data),
                        save=False,
                    )
                    records_to_create.append(record)
                
                if records_to_create:
                    WorkSourceFile.objects.bulk_create(records_to_create)
                    created.extend(records_to_create)
        except Exception:
            for record in created:
                record.file.delete(save=False)
            raise

        for old_file in old_files:
            old_file.file.delete(save=False)

    return work


def delete_work_source(work):
    files = list(work.source_files.all())
    work.source_files.all().delete()
    for source_file in files:
        source_file.file.delete(save=False)


def _sort_tree(nodes):
    nodes.sort(key=lambda node: (node["type"] != "directory", node["name"].lower()))
    for node in nodes:
        if node["type"] == "directory":
            _sort_tree(node["children"])
    return nodes


def build_source_tree(source_files):
    root = []
    directories = {}

    for source_file in source_files:
        parts = source_file.path.split("/")
        current = root
        current_path = []

        for part in parts[:-1]:
            current_path.append(part)
            directory_path = "/".join(current_path)
            if directory_path not in directories:
                node = {
                    "name": part,
                    "path": directory_path,
                    "type": "directory",
                    "children": [],
                }
                directories[directory_path] = node
                current.append(node)
            current = directories[directory_path]["children"]

        current.append(
            {
                "name": parts[-1],
                "path": source_file.path,
                "type": "file",
                "file_id": source_file.id,
                "size": source_file.size,
                "is_text": source_file.is_text,
            }
        )

    return _sort_tree(root)
