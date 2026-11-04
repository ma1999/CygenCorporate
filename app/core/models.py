"""Model classes — each model declares its table/columns and provides
async CRUD helpers on top of Database."""
from .database import Database


class Model:
    table: str = ""
    columns: dict = {}  # name -> SQL definition (registered into SchemaManager)

    def __init__(self, db: Database):
        self.db = db

    @classmethod
    def register(cls, schema):
        schema.register_table(cls.table, cls.columns)

    # ---------- CRUD ----------
    async def all(self, where: str = "", params: tuple = (), limit: int = 100):
        sql = f"SELECT * FROM `{self.table}`"
        if where:
            sql += f" WHERE {where}"
        sql += f" LIMIT {int(limit)}"
        return await self.db.query(sql, params) or []

    async def find(self, mid):
        return await self.db.query(
            f"SELECT * FROM `{self.table}` WHERE id=%s", (mid,), one=True
        )

    async def insert(self, data: dict) -> int:
        cols = ", ".join(f"`{k}`" for k in data)
        ph = ", ".join(["%s"] * len(data))
        return await self.db.execute(
            f"INSERT INTO `{self.table}` ({cols}) VALUES ({ph})", tuple(data.values())
        )

    async def update(self, mid: int, data: dict) -> bool:
        sets = ", ".join(f"`{k}`=%s" for k in data)
        return await self.db.execute(
            f"UPDATE `{self.table}` SET {sets} WHERE id=%s",
            (*data.values(), mid),
        ) >= 0

    async def delete(self, mid: int) -> bool:
        return await self.db.execute(
            f"DELETE FROM `{self.table}` WHERE id=%s", (mid,)
        ) >= 0


class Product(Model):
    table = "products"
    columns = {
        "id": "INT AUTO_INCREMENT PRIMARY KEY",
        "title": "VARCHAR(191) NOT NULL",
        "slug": "VARCHAR(191) UNIQUE",
        "description": "MEDIUMTEXT",
        "price": "DECIMAL(15,2) DEFAULT 0",
        "stock": "INT DEFAULT 0",
        "status": "VARCHAR(20) DEFAULT 'published'",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }


class Category(Model):
    table = "categories"
    columns = {
        "id": "INT AUTO_INCREMENT PRIMARY KEY",
        "title": "VARCHAR(191) NOT NULL",
        "slug": "VARCHAR(191) UNIQUE",
        "parent_id": "INT DEFAULT NULL",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }


class Page(Model):
    table = "pages"
    columns = {
        "id": "INT AUTO_INCREMENT PRIMARY KEY",
        "slug": "VARCHAR(128) UNIQUE NOT NULL",
        "title": "VARCHAR(191)",
        "content": "MEDIUMTEXT",
        "is_default": "TINYINT(1) DEFAULT 0",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }


ALL_MODELS = [Product, Category, Page]
