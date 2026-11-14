"""Small offline reference catalogue; no book downloads or tokenization at runtime."""
from functools import lru_cache
import json,sys
from pathlib import Path

@lru_cache(maxsize=1)
def catalog():
    from platform_paths import app_root
    root=app_root()/'app'
    return json.loads((root/'book_catalog.json').read_text(encoding='utf-8'))

def analogy(total,index=0):
    book=catalog()['books'][index%len(catalog()['books'])]
    books=max(0,total)/book['tokens'];quantity=f'{books:,.1f}' if books<100 else f'{books:,.0f}'
    return dict(book=book,quantity=quantity,sentence=f'你的累计 Token 用量相当于约 {quantity} 本《{book["title"]}》。',
                estimate=f'英文版每本约 {book["tokens"]:,} Token · 原文估算')
