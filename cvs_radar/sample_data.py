"""Offline sample data for reproducible demos and tests."""

from __future__ import annotations

from datetime import datetime

from .models import Comment, Post


def load_sample() -> list[Post]:
    """載入離線範例貼文。"""
    return [
        Post(
            id="sample-711-fuhang",
            source="PTT",
            board="CVS",
            url="https://www.ptt.cc/bbs/CVS/M.sample.html",
            title="[商品] 711 阜杭豆漿饅頭夾豬排蛋",
            brand="7-11",
            product_name="阜杭豆漿饅頭夾豬排蛋",
            price="65",
            author="foodie001",
            author_score=85,
            review_text="饅頭香,豬排蛋份量夠,會回購。",
            posted_at=datetime(2026, 6, 1, 12, 0, 0),
            push_count=12,
            comments=[
                Comment("推", "alice", "好吃,饅頭很香", datetime(2026, 6, 1, 12, 10)),
                Comment("推", "bob", "這個我會回購", datetime(2026, 6, 1, 12, 11)),
                Comment("推", "carol", "蛋跟豬排搭起來不錯", datetime(2026, 6, 1, 12, 12)),
                Comment("→", "dave", "價格有點貴但可以", datetime(2026, 6, 1, 12, 13)),
                Comment("噓", "erin", "太乾,踩雷", datetime(2026, 6, 1, 12, 14)),
                Comment("推", "frank", "比想像中嫩", datetime(2026, 6, 1, 12, 15)),
                Comment("→", "gina", "普通,但份量夠", datetime(2026, 6, 1, 12, 16)),
                Comment("推", "hank", "推薦早餐買這個", datetime(2026, 6, 1, 12, 17)),
                Comment("噓", "ivy", "很鹹", datetime(2026, 6, 1, 12, 18)),
                Comment("推", "jane", "不錯,會再買", datetime(2026, 6, 1, 12, 19)),
                Comment("推", "alice", "真的香,再推一次", datetime(2026, 6, 1, 12, 20)),
                Comment("推", "foodie001", "補充:熱熱吃更好吃", datetime(2026, 6, 1, 12, 21)),
            ],
        ),
        Post(
            id="sample-family-salad",
            source="PTT",
            board="CVS",
            url="https://www.ptt.cc/bbs/CVS/M.sample2.html",
            title="[商品] 全家 健身G肉餐盒",
            brand="全家",
            product_name="健身G肉餐盒",
            price="99",
            author="gymfan",
            author_score=72,
            review_text="雞肉不柴,但調味普通。",
            posted_at=datetime(2026, 6, 5, 18, 0, 0),
            comments=[
                Comment("推", "fit01", "雞肉不錯,蛋白質夠", datetime(2026, 6, 5, 18, 5)),
                Comment("→", "alice", "普通但方便", datetime(2026, 6, 5, 18, 6)),
                Comment("噓", "erin", "太貴,飯很乾", datetime(2026, 6, 5, 18, 7)),
                Comment("推", "marketer", "全家這款超好吃推薦", datetime(2026, 6, 5, 18, 8)),
                Comment("推", "marketer", "全家這款超好吃推薦", datetime(2026, 6, 5, 18, 9)),
            ],
        ),
        Post(
            id="sample-hilife",
            source="PTT",
            board="CVS",
            title="[商品] 萊爾富 起司雞肉捲",
            brand="萊爾富",
            product_name="起司雞肉捲",
            author="snackfan",
            author_score=None,
            review_text="純圖心得。",
            posted_at=datetime(2026, 6, 7, 9, 0, 0),
            comments=[
                Comment("→", "viewer1", "", datetime(2026, 6, 7, 9, 5)),
                Comment("噓", "viewer2", "沒味道,不推", datetime(2026, 6, 7, 9, 6)),
            ],
        ),
    ]
