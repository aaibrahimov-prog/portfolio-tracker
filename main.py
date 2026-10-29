
def get_price_smart(ticker: str) -> float:
    clean_tk = ticker.replace('-USD', '').replace('-USDT', '').strip().upper()
    crypto_symbols = ['SUI', 'BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOGE', 'AVAX', 'NEAR', 'DOT', 'LINK']
    
    if clean_tk in crypto_symbols or '-USD' in ticker.upper() or 'USDT' in ticker.upper():
        price = get_crypto_price_fallback(clean_tk)
        if price > 0:
            return price
            
    # Если это акция или фондовый рынок — запрашиваем yfinance
    try:
        t = yf.Ticker(ticker)
        return t.info.get('regularMarketPrice') or t.info.get('currentPrice') or 0.0
    except:
        return 0.0

import requests

def get_crypto_price_fallback(ticker: str) -> float:
    clean_tk = ticker.replace('-USD', '').replace('-USDT', '').strip().upper()
    
    # Пробуем Binance (пара со спотового рынка к USDT)
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={clean_tk}USDT"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if "price" in data:
                return float(data["price"])
    except:
        pass

    # Резервный вариант через CoinGecko (поиск по символу)
    try:
        mapping = {"SUI": "sui", "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "AVAX": "avalanche-2", "NEAR": "near"}
        coin_id = mapping.get(clean_tk, clean_tk.lower())
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if coin_id in data and "usd" in data[coin_id]:
                return float(data[coin_id]["usd"])
    except:
        pass
        
    return 0.0


def format_ticker(ticker: str) -> str:
    ticker = str(ticker).strip().upper()
    crypto = ['SUI', 'BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOGE', 'AVAX', 'DOT', 'LINK']
    if ticker in crypto and not ticker.endswith('-USD'):
        return f'{ticker}-USD'
    return ticker

from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import yfinance as yf
import requests
import time
from database import SessionLocal, init_db, Portfolio, Trade
from datetime import datetime

app = FastAPI(title="Personal Portfolio Tracker")
templates = Jinja2Templates(directory="templates")

init_db()

price_cache = {}
CACHE_TTL = 60  # Время жизни кэша в секундах

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def fetch_crypto_price_from_exchanges(symbol: str):
    sym_upper = symbol.upper().replace("-USD", "").replace("USDT", "")
    
    # 1. Bybit API
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={sym_upper}USDT"
        res = requests.get(url, timeout=2).json()
        if res.get("retCode") == 0 and res["result"]["list"]:
            item = res["result"]["list"][0]
            price = float(item["lastPrice"])
            prev_close = float(item.get("prevPrice24h", price))
            return {"price": round(price, 4), "prev_close": round(prev_close, 4)}
    except Exception:
        pass

    # 2. Binance API
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym_upper}USDT"
        res = requests.get(url, timeout=2).json()
        if "lastPrice" in res:
            price = float(res["lastPrice"])
            prev_close = float(res.get("prevClosePrice", price))
            return {"price": round(price, 4), "prev_close": round(prev_close, 4)}
    except Exception:
        pass

    return None

def get_asset_info(ticker: str):
    tk_upper = ticker.upper().strip()
    
    if tk_upper in ["USD", "USDT", "USDC", "FDUSD", "EUR", "AZN"]:
        return {"price": 1.0, "prev_close": 1.0}

    now = time.time()
    if tk_upper in price_cache:
        cached = price_cache[tk_upper]
        if now - cached["time"] < CACHE_TTL:
            return {"price": cached["price"], "prev_close": cached["prev_close"]}

    crypto_data = fetch_crypto_price_from_exchanges(tk_upper)
    if crypto_data and crypto_data["price"] > 0:
        price_cache[tk_upper] = {**crypto_data, "time": now}
        return crypto_data

    # Не ищем крипто-суффиксы для стандартных тикеров акций
    variants = [tk_upper]

    for v in variants:
        try:
            data = yf.Ticker(v)
            price = data.fast_info.last_price
            prev_close = data.fast_info.previous_close

            if price is not None and price > 0:
                if prev_close is None or prev_close <= 0:
                    prev_close = price
                res = {"price": round(float(price), 4), "prev_close": round(float(prev_close), 4)}
                price_cache[tk_upper] = {**res, "time": now}
                return res

            df = data.history(period="2d")
            if not df.empty and len(df) >= 1:
                price = df['Close'].iloc[-1]
                prev_close = df['Close'].iloc[-2] if len(df) >= 2 else price
                if price > 0:
                    res = {"price": round(float(price), 4), "prev_close": round(float(prev_close), 4)}
                    price_cache[tk_upper] = {**res, "time": now}
                    return res
        except Exception:
            continue
    
    res = {"price": 0.0, "prev_close": 0.0}
    price_cache[tk_upper] = {**res, "time": now}
    return res

def get_usd_to_azn_rate() -> float:
    try:
        data = yf.Ticker("USDAZN=X")
        price = data.fast_info.last_price
        if price is not None:
            return round(price, 4)
        df = data.history(period="1d")
        if not df.empty:
            return round(df['Close'].iloc[-1], 4)
    except:
        pass
    return 1.70

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    portfolios = db.query(Portfolio).all()
    return templates.TemplateResponse(request=request, name="index.html", context={"portfolios": portfolios})

@app.get("/api/portfolios_full")
def get_portfolios_full(db: Session = Depends(get_db)):
    portfolios = db.query(Portfolio).all()
    result = []
    global_summary_data = get_global_summary(db)

    for p in portfolios:
        p_data = get_portfolio_data(p.id, db)
        result.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "data": p_data
        })
        
    return {
        "portfolios": result,
        "global": global_summary_data["usd"],
        "rate": global_summary_data["rate"]
    }

@app.post("/create_portfolio")
def create_portfolio(name: str = Form(...), description: str = Form(""), db: Session = Depends(get_db)):
    portfolio = Portfolio(name=name, description=description)
    db.add(portfolio)
    db.commit()
    return {"status": "ok"}

@app.post("/delete_portfolio/{portfolio_id}")
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if portfolio:
        db.delete(portfolio)
        db.commit()
    return {"status": "ok"}

@app.post("/add_trade")
def add_trade(
    portfolio_id: int = Form(...),
    ticker: str = Form(...),
    trade_type: str = Form(...),
    quantity: float = Form(...),
    price: float = Form(...),
    manual_current_price: float = Form(None),
    trade_date: str = Form(None),
    db: Session = Depends(get_db)
):
    dt = datetime.utcnow()
    if trade_date:
        try:
            dt = datetime.strptime(trade_date, "%Y-%m-%d")
        except:
            pass

    trade = Trade(
        portfolio_id=portfolio_id,
        ticker=ticker.upper().strip(),
        trade_type=trade_type.upper(),
        quantity=quantity,
        price=price,
        manual_current_price=manual_current_price if manual_current_price and manual_current_price > 0 else None,
        timestamp=dt
    )
    db.add(trade)
    db.commit()
    return {"status": "ok"}

@app.post("/update_trade/{trade_id}")
def update_trade(
    trade_id: int,
    ticker: str = Form(...),
    trade_type: str = Form(...),
    quantity: float = Form(...),
    price: float = Form(...),
    manual_current_price: float = Form(None),
    trade_date: str = Form(None),
    db: Session = Depends(get_db)
):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade:
        trade.ticker = ticker.upper().strip()
        trade.trade_type = trade_type.upper()
        trade.quantity = quantity
        trade.price = price
        trade.manual_current_price = manual_current_price if manual_current_price and manual_current_price > 0 else None
        if trade_date:
            try:
                trade.timestamp = datetime.strptime(trade_date, "%Y-%m-%d")
            except:
                pass
        db.commit()
    return {"status": "ok"}

@app.post("/delete_trade/{trade_id}")
def delete_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade:
        db.delete(trade)
        db.commit()
    return {"status": "ok"}

@app.get("/api/global_summary")
def get_global_summary(db: Session = Depends(get_db)):
    portfolios = db.query(Portfolio).all()
    total_val_usd = 0.0
    total_cost_usd = 0.0
    total_day_change_usd = 0.0
    rate = get_usd_to_azn_rate()

    for p in portfolios:
        trades = db.query(Trade).filter(Trade.portfolio_id == p.id).all()
        positions = {}
        for t in trades:
            tk = t.ticker
            if tk not in positions:
                positions[tk] = {"quantity": 0.0, "total_cost": 0.0, "manual_price": t.manual_current_price}
            
            if t.manual_current_price:
                positions[tk]["manual_price"] = t.manual_current_price

            if t.trade_type == "BUY":
                positions[tk]["quantity"] += t.quantity
                positions[tk]["total_cost"] += t.quantity * t.price
            elif t.trade_type == "SELL":
                positions[tk]["quantity"] -= t.quantity
                positions[tk]["total_cost"] -= t.quantity * t.price

        for tk, data in positions.items():
            qty = data["quantity"]
            if qty <= 0:
                continue
            avg_buy = data["total_cost"] / qty if qty > 0 else 0.0
            
            info = get_asset_info(tk)
            if data["manual_price"]:
                curr_price = data["manual_price"]
                prev_close = curr_price
            else:
                curr_price = info["price"]
                if curr_price == 0:
                    curr_price = avg_buy
                prev_close = info["prev_close"]
                if prev_close == 0:
                    prev_close = curr_price

            val = qty * curr_price
            prev_val = qty * prev_close
            day_chg = val - prev_val

            if tk == "AZN":
                val_in_usd = val / rate
                cost_in_usd = data["total_cost"] / rate
                day_chg_usd = day_chg / rate
            else:
                val_in_usd = val
                cost_in_usd = data["total_cost"]
                day_chg_usd = day_chg

            total_val_usd += val_in_usd
            total_cost_usd += cost_in_usd
            total_day_change_usd += day_chg_usd

    total_pnl_usd = total_val_usd - total_cost_usd
    total_pnl_pct = (total_pnl_usd / total_cost_usd * 100) if total_cost_usd > 0 else 0.0
    prev_total_val_usd = total_val_usd - total_day_change_usd
    total_day_change_pct = (total_day_change_usd / prev_total_val_usd * 100) if prev_total_val_usd > 0 else 0.0

    return {
        "usd": {
            "total_value": round(total_val_usd, 2),
            "total_cost": round(total_cost_usd, 2),
            "total_pnl": round(total_pnl_usd, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "day_change": round(total_day_change_usd, 2),
            "day_change_pct": round(total_day_change_pct, 2)
        },
        "azn": {
            "total_value": round(total_val_usd * rate, 2),
            "total_cost": round(total_cost_usd * rate, 2),
            "total_pnl": round(total_pnl_usd * rate, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "day_change": round(total_day_change_usd * rate, 2),
            "day_change_pct": round(total_day_change_pct, 2)
        },
        "rate": rate
    }

@app.get("/api/portfolio/{portfolio_id}")
def get_portfolio_data(portfolio_id: int, db: Session = Depends(get_db)):
    trades = db.query(Trade).filter(Trade.portfolio_id == portfolio_id).order_by(Trade.timestamp.desc()).all()
    
    positions = {}
    for t in trades:
        tk = t.ticker
        if tk not in positions:
            positions[tk] = {"quantity": 0.0, "total_cost": 0.0, "manual_price": t.manual_current_price}
        
        if t.manual_current_price:
            positions[tk]["manual_price"] = t.manual_current_price

        if t.trade_type == "BUY":
            positions[tk]["quantity"] += t.quantity
            positions[tk]["total_cost"] += t.quantity * t.price
        elif t.trade_type == "SELL":
            positions[tk]["quantity"] -= t.quantity
            positions[tk]["total_cost"] -= t.quantity * t.price

    summary = []
    total_portfolio_value = 0.0
    total_portfolio_cost = 0.0
    total_portfolio_day_change = 0.0

    for tk, data in positions.items():
        qty = data["quantity"]
        if qty <= 0:
            continue
        
        avg_price = data["total_cost"] / qty if qty > 0 else 0
        info = get_asset_info(tk)
        
        if data["manual_price"]:
            current_price = data["manual_price"]
            prev_close = current_price
        else:
            tk_formatted = format_ticker(tk)
    # Перезапрашиваем info с отформатированным тикером если нужно
    try:
        current_price = yf.Ticker(tk_formatted).info.get("regularMarketPrice") or yf.Ticker(tk_formatted).info.get("currentPrice") or info.get("price", 0)
    except:
        current_price = info.get("price", 0)
            if current_price == 0:
                current_price = avg_price
            prev_close = info["prev_close"]
            if prev_close == 0:
                prev_close = current_price

        current_val = qty * current_price
        prev_val = qty * prev_close
        day_change = current_val - prev_val

        profit_loss = current_val - data["total_cost"]
        profit_loss_pct = (profit_loss / data["total_cost"] * 100) if data["total_cost"] > 0 else 0.0

        total_portfolio_value += current_val
        total_portfolio_cost += data["total_cost"]
        total_portfolio_day_change += day_change

        summary.append({
            "ticker": tk,
            "quantity": qty,
            "avg_price": round(avg_price, 2),
            "current_price": round(current_price, 4),
            "current_value": round(current_val, 2),
            "profit_loss": round(profit_loss, 2),
            "profit_loss_pct": round(profit_loss_pct, 2),
            "day_change": round(day_change, 2),
            "day_change_pct": round(((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0, 2)
        })

    total_pnl = total_portfolio_value - total_portfolio_cost
    total_pnl_pct = (total_pnl / total_portfolio_cost * 100) if total_portfolio_cost > 0 else 0.0
    prev_port_val = total_portfolio_value - total_portfolio_day_change
    total_port_day_change_pct = (total_portfolio_day_change / prev_port_val * 100) if prev_port_val > 0 else 0.0

    trades_list = [{
        "id": t.id,
        "ticker": t.ticker,
        "trade_type": t.trade_type,
        "quantity": t.quantity,
        "price": t.price,
        "manual_current_price": t.manual_current_price or "",
        "date": t.timestamp.strftime("%Y-%m-%d")
    } for t in trades]

    return {
        "positions": summary,
        "trades": trades_list,
        "total_value": round(total_portfolio_value, 2),
        "total_cost": round(total_portfolio_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "day_change": round(total_portfolio_day_change, 2),
        "day_change_pct": round(total_port_day_change_pct, 2)
    }
