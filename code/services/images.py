from pathlib import Path
class ImagesService:

    def __init__(self, connection):
        self.connection = connection

    def get_images(
        self,
        user_id: str,
        request_id: str | None = None,
        related_event_id: str | None = None,
    ) -> list[dict]:

        query = """
            SELECT
                image_id,
                user_id,
                request_id,
                related_event_id
            FROM images
            WHERE user_id = ?
        """

        params = [user_id]

        if request_id:
            query += """
                AND request_id = ?
            """
            params.append(request_id)

        if related_event_id:
            query += """
                AND related_event_id = ?
            """
            params.append(related_event_id)

        query += """
            ORDER BY image_id
        """

        rows = self.connection.execute(
            query,
            params,
        ).fetchall()

        return [
            self._row_to_dict(row)
            for row in rows
        ]

    @staticmethod
    def _row_to_dict(row) -> dict:

        return {
            "image_id": row[0],
            "user_id": row[1],
            "request_id": row[2],
            "related_event_id": row[3],
        }
    def get_image_path(self, image_id: str) -> str | None:
        """
        Resolve an image ID to the actual file under dataset/media/images.
        """
    
        project_root = Path(__file__).resolve().parents[2]
    
        image_dir = (
            project_root
            / "dataset"
            / "media"
            / "images"
        )
    
        extensions = [
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        ]
    
        for extension in extensions:
            path = image_dir / f"{image_id}{extension}"
    
            if path.exists():
                return str(path)
    
        return None