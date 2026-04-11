from pathlib import Path


class EnvFileDetectorService:
    PRIORITY = {
        ".env": 0,
        ".env.local": 1,
        ".env.development": 2,
        ".env.production": 3,
        ".env.test": 4,
        ".env.example": 5,
    }

    def detect(self, file_tree: list[str]) -> list[dict[str, str | int]]:
        env_files = []
        for rel_path in file_tree:
            name = Path(rel_path).name.lower()
            if not name.startswith(".env"):
                continue
            env_files.append(
                {
                    "path": rel_path,
                    "name": name,
                    "priority": self.PRIORITY.get(name, 50),
                }
            )

        return sorted(
            env_files,
            key=lambda item: (int(item["priority"]), str(item["path"])),
        )
