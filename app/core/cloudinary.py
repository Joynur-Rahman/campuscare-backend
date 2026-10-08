import cloudinary
import cloudinary.utils
import cloudinary.uploader
import time

from app.core.config import settings


def configure_cloudinary() -> None:
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


def upload_media(content: bytes, filename: str, user_id: str, folder: str | None = None) -> dict:
    configure_cloudinary()
    upload_folder = folder or settings.cloudinary_upload_folder
    result = cloudinary.uploader.upload(
        content,
        folder=f"{upload_folder}/{user_id}",
        resource_type="auto",
        use_filename=True,
        unique_filename=True,
    )
    return {
        "public_id": result["public_id"],
        "secure_url": result["secure_url"],
        "resource_type": result.get("resource_type"),
        "format": result.get("format"),
        "bytes": result.get("bytes"),
        "original_filename": filename,
    }


def delete_media(public_id: str, resource_type: str | None = None) -> None:
    configure_cloudinary()
    cloudinary.uploader.destroy(
        public_id,
        resource_type=resource_type or "image",
        invalidate=True,
    )


def signed_upload_parameters(user_id: str) -> dict[str, str | int]:
    configure_cloudinary()
    params = {
        "folder": f"{settings.cloudinary_upload_folder}/{user_id}",
        "timestamp": int(time.time()),
        "use_filename": True,
        "unique_filename": True,
    }
    return {
        **params,
        "signature": cloudinary.utils.api_sign_request(params, settings.cloudinary_api_secret),
        "api_key": settings.cloudinary_api_key,
        "cloud_name": settings.cloudinary_cloud_name,
    }