# /home/cwj/code/finace_stock/web/models.py
from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    uid: str = Field(index=True, unique=True)          # 对应 users.yaml 的 id
    name: str
    password_hash: str
    timezone: str = "Asia/Shanghai"
    channel: str = "serverchan"                        # serverchan/telegram/wecom

    # 推送密钥（直接存明文；仅本机可读，务必设置权限600）
    sct_sendkey: Optional[str] = None
    tg_bot_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    wecom_webhook: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    watchlist: List["Watch"] = Relationship(back_populates="user")
    rss: List["Rss"] = Relationship(back_populates="user")

class Watch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    code: str                                     # 建议写 sh600519
    user: Optional[User] = Relationship(back_populates="watchlist")

class Rss(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    url: str
    user: Optional[User] = Relationship(back_populates="rss")
