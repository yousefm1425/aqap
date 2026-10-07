import hashlib
import shutil
import uuid
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol
from urllib.parse import quote

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from .config import settings

CHUNK = 1024 * 1024


class Storage(Protocol):
    def put(self, key: str, stream: BinaryIO, size: int, content_type: str) -> None: ...
    def remove(self, key: str) -> None: ...
    def download_url(self, key: str, filename: str) -> str: ...


class MinioStorage:
    def __init__(self) -> None:
        from minio import Minio

        self.client = Minio(settings.minio_endpoint, access_key=settings.minio_access_key,
                            secret_key=settings.minio_secret_key, secure=settings.minio_secure)
        self.bucket = settings.minio_bucket
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put(self, key, stream, size, content_type):
        self.client.put_object(self.bucket, key, stream, length=size, content_type=content_type)

    def remove(self, key):
        self.client.remove_object(self.bucket, key)

    def download_url(self, key, filename):
        return self.client.presigned_get_object(
            self.bucket, key, expires=timedelta(seconds=settings.download_url_ttl_seconds),
            response_headers={"response-content-disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


class LocalStorage:
    """للتطوير والاختبارات فقط."""

    def __init__(self) -> None:
        self.root = Path(settings.local_storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key, stream, size, content_type):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as out:
            shutil.copyfileobj(stream, out, CHUNK)

    def remove(self, key):
        (self.root / key).unlink(missing_ok=True)

    def download_url(self, key, filename):
        return f"file://{(self.root / key).resolve()}"


_storage: Storage | None = None


def init_storage() -> None:
    global _storage
    _storage = MinioStorage() if settings.storage_backend == "minio" else LocalStorage()


def storage() -> Storage:
    assert _storage is not None, "storage is not initialised"
    return _storage


async def hash_and_validate(upload: UploadFile) -> tuple[str, int, str]:
    """يحسب SHA-256 والحجم ويتحقق من الامتداد والحد الأقصى، ثم يعيد المؤشر للبداية."""
    ext = PurePosixPath(upload.filename or "").suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(415, f"نوع الملف غير مسموح: {ext or 'بدون امتداد'}")
    limit = settings.max_upload_mb * 1024 * 1024
    digest, size = hashlib.sha256(), 0
    while chunk := await upload.read(CHUNK):
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f"حجم الملف يتجاوز {settings.max_upload_mb} ميجابايت")
        digest.update(chunk)
    if size == 0:
        raise HTTPException(422, "الملف فارغ")
    await upload.seek(0)
    return digest.hexdigest(), size, ext


def build_key(institution_id: int, department_id: int | None, evidence_id: int, ext: str) -> str:
    # المفتاح لا يحمل اسم الملف الأصلي (قد يكون عربياً أو حساساً)؛ الاسم يُحفظ في قاعدة البيانات
    return f"{institution_id}/{department_id or 'inst'}/{evidence_id}/{uuid.uuid4().hex}{ext}"


async def put_upload(key: str, upload: UploadFile, size: int) -> None:
    await run_in_threadpool(storage().put, key, upload.file, size,
                            upload.content_type or "application/octet-stream")


async def remove(key: str) -> None:
    await run_in_threadpool(storage().remove, key)


async def download_url(key: str, filename: str) -> str:
    return await run_in_threadpool(storage().download_url, key, filename)


async def put_bytes(key: str, data: bytes, content_type: str) -> None:
    import io

    await run_in_threadpool(storage().put, key, io.BytesIO(data), len(data), content_type)
