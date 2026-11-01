from __future__ import annotations
import asyncio
from dataclasses import dataclass

@dataclass
class FunPayProfile:
    username: str
    user_id: str = ""
    balance: str = "не найдено"
    sales: int = 0
    active_lots: int = 0
    profile_url: str = ""

def _connect(token):
    from FunPayAPI import Account
    return Account(token).get()

async def verify_token(token):
    try:
        account=await asyncio.to_thread(_connect,token)
        username=str(getattr(account,"username","") or getattr(account,"name","") or "")
        uid=str(getattr(account,"id","") or "")
        return True, username or (f"FunPay ID {uid}" if uid else "Аккаунт подключён"), uid
    except Exception:
        return False,"",""

async def get_profile(token):
    account=await asyncio.to_thread(_connect,token)
    username=str(getattr(account,"username","") or getattr(account,"name","") or "не найдено")
    uid=str(getattr(account,"id","") or "")
    bal=getattr(account,"balance",None)
    return FunPayProfile(username,uid,f"{bal} ₽" if bal is not None else "не найдено",
                         profile_url=f"https://funpay.com/users/{uid}/" if uid else "")

async def get_lots(token):
    account=await asyncio.to_thread(_connect,token)
    getter=getattr(account,"get_sells",None)
    if not callable(getter): return []
    try: return await asyncio.to_thread(getter)
    except Exception: return []

async def get_market_prices(category,subcategory=""):
    raise NotImplementedError("Нужен проверенный парсер конкретной категории FunPay; цены не подменяются вымышленными.")

async def change_lot_price(token,lot_id,price):
    raise NotImplementedError("Редактирование цены отключено до проверки API-метода и безопасных ограничений.")
