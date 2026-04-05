import hashlib


class EnvHashingService:
    @staticmethod
    def hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def hash_bytes(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()
