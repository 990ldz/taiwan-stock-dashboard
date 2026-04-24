"""
台股三線決策儀表板 v2.0
════════════════════════════════════════
長線 1年+ · 中線 6-12月 · 短線 7日內 · 自選股分析

分析方法論：
  長線 → Stan Weinstein Stage 2 趨勢分析 + 相對強度 (RS)
  中線 → William O'Neil CANSLIM 精簡版
  短線 → Larry Williams 動能突破 + RSI/MACD 訊號
  停損 → Van Tharp ATR 動態停損（從進場價計算 RR）
  目標 → Fibonacci 延伸 + 前高阻力雙驗證

股票池：台股 15 大產業、130+ 檔
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import time
import warnings
import plotly.graph_objects as go
from plotly.subplots import make_subplots
warnings.filterwarnings("ignore")

# ════════════════════════════════════════════════════════════════
# ① Page Config
# ════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="台股三線決策儀表板 v2",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ════════════════════════════════════════════════════════════════
# ② 全域常數與股票池
# ════════════════════════════════════════════════════════════════
FINMIND_API      = "https://api.finmindtrade.com/api/v4/data"
TRANSACTION_COST = 0.006   # 手續費 0.6%（單邊）
SLIPPAGE         = 0.001   # 滑點 0.1%（單邊）
TOTAL_FRICTION   = (TRANSACTION_COST + SLIPPAGE) * 2

# ── 15 大產業股票池 ────────────────────────────────────────────
SECTOR_STOCKS: dict[str, list[str]] = {
    "半導體":     ["2330","2454","2303","3711","6415","3034","2379","3529","2344","2408"],
    "電子製造":   ["2317","2382","2357","2308","4938","2395","2360","3008","2474","2376"],
    "金融銀行":   ["2881","2882","2884","2885","2886","2887","2891","2892","5880","2883"],
    "保險租賃":   ["2823","5871","2820","2838"],
    "石化塑料":   ["1301","1303","1326","6505","2504"],
    "鋼鐵金屬":   ["2002","2006","2007","2008","2020"],
    "航運物流":   ["2609","2603","2615","2610","2618","2634"],
    "生技醫療":   ["4544","1789","6547","4766","4170","1737","6202"],
    "食品飲料":   ["1216","1217","2912","2915","1227","1264","1218"],
    "電信":       ["2412","3045","4904"],
    "汽車零件":   ["2207","2201","2204","1590","2231"],
    "營建房地產": ["2511","5522","2520","2534","5215"],
    "傳統製造":   ["1101","1102","1402","1434","9910","1504","1514"],
    "觀光零售":   ["2727","2723","2719","5903","2915"],
    "電機機械":   ["1519","1530","2369","2371","1590"],
}

# ── 股票中文名稱 ───────────────────────────────────────────────
STOCK_NAMES: dict[str, str] = {
    # 半導體
    "2330":"台積電","2454":"聯發科","2303":"聯電","3711":"日月光",
    "6415":"矽力KY","3034":"聯詠","2379":"瑞昱","3529":"力旺",
    "2344":"華邦電","2408":"南亞科",
    # 電子製造
    "2317":"鴻海","2382":"廣達","2357":"華碩","2308":"台達電",
    "4938":"和碩","2395":"研華","2360":"致茂","3008":"大立光",
    "2474":"可成","2376":"技嘉",
    # 金融銀行
    "2881":"富邦金","2882":"國泰金","2884":"玉山金","2885":"元大金",
    "2886":"兆豐金","2887":"台新金","2891":"中信金","2892":"第一金",
    "5880":"合庫金","2883":"開發金",
    # 保險租賃
    "2823":"中壽","5871":"中租KY","2820":"華票","2838":"聯邦銀",
    # 石化塑料
    "1301":"台塑","1303":"南亞","1326":"台化","6505":"台塑化","2504":"國產",
    # 鋼鐵金屬
    "2002":"中鋼","2006":"東和鋼鐵","2007":"燁興","2008":"高興昌","2020":"美亞鋼管",
    # 航運物流
    "2609":"陽明","2603":"長榮","2615":"萬海","2610":"華航","2618":"長榮航","2634":"漢翔",
    # 生技醫療
    "4544":"籌碼達人","1789":"神隆","6547":"疫苗","4766":"艾伯維","4170":"永昕","1737":"台鹽","6202":"盛弘",
    # 食品飲料
    "1216":"統一","1217":"愛之味","2912":"統一超","2915":"潤泰全","1227":"佳格","1264":"德麥","1218":"泰山",
    # 電信
    "2412":"中華電","3045":"台灣大","4904":"遠傳",
    # 汽車零件
    "2207":"和泰車","2201":"裕隆","2204":"中華","1590":"亞德客KY","2231":"為升",
    # 營建房地產
    "2511":"太子","5522":"遠雄","2520":"冠德","2534":"宏盛","5215":"科風",
    # 傳統製造
    "1101":"台泥","1102":"亞泥","1402":"遠東新","1434":"福懋","9910":"豐泰",
    "1504":"東元","1514":"亞力",
    # 觀光零售
    "2727":"王品","2723":"美食KY","2719":"燦星旅","5903":"全家","2353":"宏碁",
    # 電機機械
    "1519":"華城","1530":"亞翔","2369":"菱生","2371":"大同","1219":"福壽",
}

def get_all_stocks() -> list[str]:
    """回傳去重後的完整股票列表"""
    seen = set()
    result = []
    for stocks in SECTOR_STOCKS.values():
        for s in stocks:
            if s not in seen:
                seen.add(s)
                result.append(s)
    return result

# ════════════════════════════════════════════════════════════════
# ③ CSS 暗色主題
# ════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Noto+Sans+TC:wght@400;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Noto Sans TC', sans-serif; }

.dash-header {
    background: linear-gradient(135deg, #040d18 0%, #081428 60%, #0a1e38 100%);
    border: 1px solid #1a3a5f; border-radius: 14px;
    padding: 24px 32px; margin-bottom: 20px;
}
.dash-title { font-family:'IBM Plex Mono',monospace; font-size:1.7rem;
              font-weight:600; color:#e8f4f8; letter-spacing:0.04em; }
.dash-sub   { color:#4a7a9a; font-size:0.75rem; margin-top:4px;
              letter-spacing:0.1em; text-transform:uppercase; }

/* 標的卡片 */
.stock-card {
    background: linear-gradient(150deg,#071626,#0a1e34);
    border:1.5px solid #1a3a5a; border-radius:12px;
    padding:18px 20px; height:100%; position:relative;
}
.card-bull { border-color:#00c87a; box-shadow:0 0 16px rgba(0,200,122,0.10); }
.card-bear { border-color:#2a3a50; }
.card-badge { display:inline-block; border-radius:5px; padding:2px 9px;
              font-size:0.7rem; font-weight:700; letter-spacing:0.06em;
              margin-bottom:8px; }
.badge-long  { background:#0e2a1a; color:#00c87a; border:1px solid #00c87a44; }
.badge-mid   { background:#0e1e2e; color:#4ab3ff; border:1px solid #4ab3ff44; }
.badge-short { background:#2a1e0e; color:#f0a500; border:1px solid #f0a50044; }

/* 操作建議盒 */
.zones-box {
    background:#060f1c; border:1px solid #1a3550;
    border-radius:8px; padding:10px 12px; margin-top:10px; font-size:0.74rem;
}
.zones-title { color:#2a6a8a; font-size:0.66rem; letter-spacing:0.1em;
               text-transform:uppercase; margin-bottom:6px; }
.zg { display:grid; grid-template-columns:1fr 1fr; gap:4px 10px; }
.zl { color:#5a8fa8; }
.zv-buy  { font-family:'IBM Plex Mono',monospace; color:#e8f4f8; }
.zv-stop { font-family:'IBM Plex Mono',monospace; color:#ff7878; }
.zv-t1   { font-family:'IBM Plex Mono',monospace; color:#00c87a; }
.zv-t2   { font-family:'IBM Plex Mono',monospace; color:#4ab3ff; }

/* 區塊標題 */
.sec-title {
    font-family:'IBM Plex Mono',monospace; font-size:0.8rem; color:#2a6a8a;
    letter-spacing:0.12em; text-transform:uppercase;
    border-bottom:1px solid #112a40; padding-bottom:7px; margin:24px 0 14px;
}

/* 通知橫幅 */
.warn-bar { background:#1a0808; border:1px solid #ff5c5c33;
            border-left:4px solid #ff5c5c; border-radius:7px;
            padding:12px 18px; margin:10px 0; color:#ffaaaa; font-size:0.86rem; }
.ok-bar   { background:#040f08; border:1px solid #00c87a33;
            border-left:4px solid #00c87a; border-radius:7px;
            padding:12px 18px; margin:10px 0; color:#80e8b0; font-size:0.86rem; }

/* 指標說明徽章 */
.method-tag { display:inline-block; border-radius:4px; padding:1px 7px;
              font-size:0.68rem; background:#0a1a2e; color:#4a8aaa;
              border:1px solid #1a3a5a; margin:2px 2px; }

#MainMenu,footer { visibility:hidden; }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# ④ FinMind API 層
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_price(stock_id: str, start: str, end: str, token: str = "") -> pd.DataFrame:
    params = {"dataset": "TaiwanStockPrice", "data_id": stock_id,
              "start_date": start, "end_date": end}
    if token:
        params["token"] = token
    try:
        r = requests.get(FINMIND_API, params=params, timeout=20)
        r.raise_for_status()
        d = r.json()
        if d.get("status") != 200 or not d.get("data"):
            return pd.DataFrame()
        df = pd.DataFrame(d["data"])
        df = df.rename(columns={"close":"Close","open":"Open","max":"High",
                                 "min":"Low","Trading_Volume":"Volume"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for c in ["Close","Open","High","Low","Volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["Close"])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_taiex(start: str, end: str, token: str = "") -> pd.DataFrame:
    """
    取得加權指數資料。
    嘗試順序：
      ① TaiwanStockMarketIndex（data_id=TAIEX / Y9999 / 空）
      ② 備用：抓 0050（元大台灣50）作為大盤代理
    """
    # ── 方法一：標準大盤指數 API ──────────────────────────────
    for did in ["TAIEX", "Y9999", ""]:
        params = {"dataset": "TaiwanStockMarketIndex", "start_date": start, "end_date": end}
        if did:
            params["data_id"] = did
        if token:
            params["token"] = token
        try:
            r = requests.get(FINMIND_API, params=params, timeout=20)
            d = r.json()
            if d.get("status") != 200 or not d.get("data"):
                continue
            df = pd.DataFrame(d["data"])
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            for col in ["price", "Price", "close", "Close"]:
                if col in df.columns:
                    df["Close"] = pd.to_numeric(df[col], errors="coerce")
                    break
            else:
                nums = df.select_dtypes(include=[np.number]).columns
                if len(nums):
                    df["Close"] = df[nums[-1]]
            df = df.dropna(subset=["Close"])
            if len(df) < 10:
                continue
            df["Volume"] = 1.0
            df["Open"] = df["High"] = df["Low"] = df["Close"]
            return df
        except Exception:
            continue

    # ── 方法二：用 0050 當大盤代理（免 token 也可取）──────────
    try:
        params = {"dataset": "TaiwanStockPrice", "data_id": "0050",
                  "start_date": start, "end_date": end}
        if token:
            params["token"] = token
        r = requests.get(FINMIND_API, params=params, timeout=20)
        d = r.json()
        if d.get("status") == 200 and d.get("data"):
            df = pd.DataFrame(d["data"])
            df = df.rename(columns={"close": "Close", "open": "Open",
                                     "max": "High", "min": "Low",
                                     "Trading_Volume": "Volume"})
            df["date"]  = pd.to_datetime(df["date"])
            df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
            df = df.sort_values("date").dropna(subset=["Close"]).reset_index(drop=True)
            if len(df) >= 10:
                return df
    except Exception:
        pass

    return pd.DataFrame()


# ════════════════════════════════════════════════════════════════
# ⑤ 技術指標計算（完整版）
# ════════════════════════════════════════════════════════════════

def compute_all_indicators(df: pd.DataFrame, taiex_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    計算所有技術指標。
    均線：MA5/10/20/60/120/240
    動能：RSI(14) · MACD(12,26,9) · Bollinger(20,2)
    強度：相對強度 RS vs TAIEX（3個月）
    波動：ATR(14)
    趨勢：季線斜率（線性回歸）
    """
    df = df.copy()
    c = df["Close"].astype(float)

    # ── 均線 ──────────────────────────────────────────────────
    for n in [5, 10, 20, 60, 120, 240]:
        df[f"MA{n}"] = c.rolling(n, min_periods=max(2, n//4)).mean()

    if "Volume" in df.columns:
        df["VolMA20"] = df["Volume"].astype(float).rolling(20, min_periods=5).mean()
    else:
        df["VolMA20"] = np.nan

    # ── RSI(14) ───────────────────────────────────────────────
    delta = c.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=13, adjust=False).mean()
    avg_l = loss.ewm(com=13, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # ── MACD(12,26,9) ─────────────────────────────────────────
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["MACD"]        = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"]   = df["MACD"] - df["MACD_signal"]

    # ── Bollinger Bands(20, 2σ) ───────────────────────────────
    bb_mid    = c.rolling(20, min_periods=10).mean()
    bb_std    = c.rolling(20, min_periods=10).std()
    df["BB_upper"] = bb_mid + 2 * bb_std
    df["BB_mid"]   = bb_mid
    df["BB_lower"] = bb_mid - 2 * bb_std
    df["BB_pct"]   = (c - df["BB_lower"]) / (df["BB_upper"] - df["BB_lower"])

    # ── ATR(14) ───────────────────────────────────────────────
    if "High" in df.columns and "Low" in df.columns:
        hi = df["High"].astype(float)
        lo = df["Low"].astype(float)
        prev_c = c.shift(1)
        tr = pd.concat([hi - lo,
                        (hi - prev_c).abs(),
                        (lo - prev_c).abs()], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14, min_periods=5).mean()
    else:
        df["ATR"] = c * 0.02

    # ── 季線（60MA）斜率 ──────────────────────────────────────
    def _slope(s):
        n = len(s)
        if n < 10: return np.nan
        x = np.arange(n, dtype=float)
        return float(np.polyfit(x, s, 1)[0])

    df["MA60_slope"]  = c.rolling(60,  min_periods=20).apply(_slope, raw=True)
    df["MA120_slope"] = c.rolling(120, min_periods=40).apply(_slope, raw=True)
    df["MA240_slope"] = c.rolling(240, min_periods=80).apply(_slope, raw=True)

    # ── 52 週高低點 ───────────────────────────────────────────
    df["High52W"] = c.rolling(252, min_periods=60).max()
    df["Low52W"]  = c.rolling(252, min_periods=60).min()
    df["Pct_from_52H"] = (c - df["High52W"]) / df["High52W"] * 100

    # ── 相對強度 vs TAIEX（3個月，約 63 交易日）─────────────
    df["RS_3m"] = np.nan
    if taiex_df is not None and not taiex_df.empty and len(df) >= 63:
        # 對齊日期
        merged = df[["date","Close"]].copy()
        tx = taiex_df[["date","Close"]].rename(columns={"Close":"TAIEX"})
        merged = merged.merge(tx, on="date", how="left")
        merged["TAIEX"] = merged["TAIEX"].ffill()

        stock_ret = merged["Close"].pct_change(63)
        taiex_ret = merged["TAIEX"].pct_change(63)
        rs_series = stock_ret - taiex_ret
        df["RS_3m"] = rs_series.values

    # ── 6個月漲幅 ─────────────────────────────────────────────
    df["Gain_6m"] = c.pct_change(126) * 100
    df["Gain_1m"] = c.pct_change(21)  * 100

    return df


# ════════════════════════════════════════════════════════════════
# ⑤-b  FinMind 基本面資料（月營收）
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=86400, show_spinner=False)   # 基本面資料每日更新一次
def fetch_monthly_revenue(sid: str, token: str = "") -> pd.DataFrame:
    """
    取得個股月營收資料（TaiwanStockMonthRevenue）
    回傳欄位：date / revenue（當月） / revenue_year（去年同月）
    用途：計算 YoY 年增率
    """
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=450)).strftime("%Y-%m-%d")
    params = {"dataset": "TaiwanStockMonthRevenue", "data_id": sid,
              "start_date": start, "end_date": end}
    if token:
        params["token"] = token
    try:
        r = requests.get(FINMIND_API, params=params, timeout=15)
        d = r.json()
        if d.get("status") != 200 or not d.get("data"):
            return pd.DataFrame()
        df = pd.DataFrame(d["data"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for col in ["revenue", "Revenue", "revenue_month"]:
            if col in df.columns:
                df["revenue"] = pd.to_numeric(df[col], errors="coerce")
                break
        return df.dropna(subset=["revenue"])
    except Exception:
        return pd.DataFrame()


# ════════════════════════════════════════════════════════════════
# ⑥  G.P.S. 全方位選股評分系統
# ════════════════════════════════════════════════════════════════
#
#  設計哲學：「由大到小，先看環境再選個股」
#  參考：科斯托蘭尼、巴菲特、Mgk、蔣承翰、川銀藏
#
#  ┌──────────────────────────────────────────────────────────┐
#  │  Stage 1  Global Market  大盤環境      20 分             │
#  │  Stage 2  Peer Group     族群動能      25 分             │
#  │  Stage 3  Stock Tech     個股強勢度    35 分             │
#  │  Stage 4  Fundamental    護城河與未來  20 分             │
#  │  ───────────────────────────────────────────────        │
#  │  死亡過濾  大盤跌破 60MA             −40 分             │
#  │  滿分                               100 分             │
#  └──────────────────────────────────────────────────────────┘
#
#  評級行動指令：
#    85-100  AAA 極致強勢 → 全力出擊，波段重倉
#    70-84   AA  穩健進攻 → 分批進場
#    50-69   B   技術反彈 → 嚴禁重倉，小量短線
#    <50     C   高風險區 → 絕對空手
# ════════════════════════════════════════════════════════════════

# 已知具明顯護城河的台股（用於 F2 評分）
MOAT_STOCKS = {
    "2330","2454","2303","3711","6415",   # 半導體龍頭
    "2412","3045","4904",                  # 電信壟斷
    "2882","2881","2886",                  # 大型金融
    "1301","1303","1326","6505",           # 石化整合
    "2317","2382",                         # 供應鏈龍頭
    "2912","5903",                         # 通路護城河
}


def score_gps(
    df: pd.DataFrame,
    market_data: dict,
    sector_stats: dict,
    rev_df: pd.DataFrame = None,
    sid: str = "",
) -> dict:
    """
    G.P.S. 全方位選股評分（100 分制）。

    Parameters
    ----------
    df           : 個股含指標的 DataFrame
    market_data  : get_market_state() 回傳的大盤狀態
    sector_stats : compute_sector_stats() 回傳的族群資料
    rev_df       : fetch_monthly_revenue() 回傳的月營收資料（可為 None）
    sid          : 股票代號（用於護城河判斷）
    """
    if len(df) < 20:
        return _gps_empty("資料不足")

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    close = float(last["Close"])

    def _v(col):
        v = last.get(col)
        return float(v) if v is not None and not pd.isna(v) else np.nan

    breakdown = []
    raw = 0.0

    # ════════════════════════════════════════
    # Stage 1：Global Market 大盤環境（20分）
    # ════════════════════════════════════════

    # G1：大盤站上 20MA（月線）+10
    mkt_above_20 = market_data.get("above_20ma", False)
    pts = 10
    raw += pts if mkt_above_20 else 0
    breakdown.append({
        "stage": "G", "label": "大盤站上 20MA（月線）",
        "pts": pts, "met": mkt_above_20,
        "detail": f"大盤 20MA 濾網：{'✅ 月線多頭' if mkt_above_20 else '❌ 月線偏空'}",
    })

    # G2：市場情緒未過熱（大盤 RSI < 75 且非恐慌）+10
    mkt_rsi = market_data.get("rsi", 50)
    mkt_no_panic = market_data.get("no_panic", True)
    mkt_calm = mkt_rsi < 75 and mkt_no_panic
    pts = 10
    raw += pts if mkt_calm else 0
    breakdown.append({
        "stage": "G", "label": "市場情緒健康（RSI未過熱、無系統恐慌）",
        "pts": pts, "met": mkt_calm,
        "detail": f"大盤 RSI={mkt_rsi:.0f}（>75 代表過熱）",
    })

    # G 死亡過濾：大盤跌破 60MA（季線）→ 強制 -40
    mkt_below_60 = market_data.get("below_60ma", False)
    death_trigger = False
    if mkt_below_60:
        raw -= 40
        death_trigger = True
        breakdown.append({
            "stage": "G", "label": "⚠️ 死亡過濾：大盤跌破 60MA 季線",
            "pts": -40, "met": True,
            "detail": "大盤處於空頭格局，勝率極低，強烈建議空手",
        })

    # ════════════════════════════════════════
    # Stage 2：Peer Group 族群動能（25分）
    # ════════════════════════════════════════

    sector_avg_chg   = sector_stats.get("avg_chg", 0.0)
    sector_strong_cnt= sector_stats.get("strong_count", 0)    # 上漲 >3% 的檔數
    sector_vol_rank  = sector_stats.get("vol_rank", 99)        # 成交值排名（越小越好）

    # P1：龍頭帶領（族群 2 檔以上強勢，或平均漲幅 >3%）+15
    p1_ok = sector_strong_cnt >= 2 or sector_avg_chg > 3.0
    pts = 15
    raw += pts if p1_ok else 0
    breakdown.append({
        "stage": "P", "label": "族群龍頭帶領（≥2檔強勢 或 均漲>3%）",
        "pts": pts, "met": p1_ok,
        "detail": f"族群平均漲 {sector_avg_chg:+.1f}%，強勢股 {sector_strong_cnt} 檔",
    })

    # P2：資金匯集（族群成交值排名前 5）+10
    p2_ok = sector_vol_rank <= 5
    pts = 10
    raw += pts if p2_ok else 0
    breakdown.append({
        "stage": "P", "label": "族群成交值前 5（資金匯集）",
        "pts": pts, "met": p2_ok,
        "detail": f"族群成交值排名第 {sector_vol_rank}（共 {len(SECTOR_STOCKS)} 個產業）",
    })

    # ════════════════════════════════════════
    # Stage 3：Stock Technical 個股強勢度（35分）
    # ════════════════════════════════════════

    # S1：相對強度 RS（大盤跌它不跌，或創高）+15
    rs_3m = _v("RS_3m")
    s1_ok = not np.isnan(rs_3m) and rs_3m > 0
    pts = 15
    raw += pts if s1_ok else 0
    breakdown.append({
        "stage": "S", "label": "相對強度 RS 優於大盤",
        "pts": pts, "met": s1_ok,
        "detail": f"RS（3個月）= {rs_3m*100:+.1f}%" if not np.isnan(rs_3m) else "RS 無大盤資料",
    })

    # S2：量價爆發（量 > 5日均量 1.5×，且收在振幅前 1/3）+10
    vol_today  = float(last.get("Volume", 0))
    vol_5d     = float(df["Volume"].tail(6).iloc[:-1].mean()) if len(df) >= 6 else 0
    vol_burst  = vol_5d > 0 and vol_today > vol_5d * 1.5
    # 收在振幅前 1/3：(Close - Low) / (High - Low) > 2/3
    hi = float(last.get("High", close)); lo = float(last.get("Low", close))
    range_pos  = (close - lo) / (hi - lo) if (hi - lo) > 0 else 0.5
    s2_ok = vol_burst and range_pos > 0.667
    pts = 10
    raw += pts if s2_ok else 0
    breakdown.append({
        "stage": "S", "label": "量價爆發（量>5日均量1.5×，收盤在振幅前1/3）",
        "pts": pts, "met": s2_ok,
        "detail": (f"量比={vol_today/vol_5d:.1f}×，振幅位置={range_pos*100:.0f}%"
                   if vol_5d > 0 else "成交量資料不足"),
    })

    # S3：均線多頭排列 MA5>MA10>MA20>MA60 +10
    ma5 = _v("MA5"); ma10 = _v("MA10"); ma20 = _v("MA20"); ma60 = _v("MA60")
    s3_ok = (not any(np.isnan(x) for x in [ma5,ma10,ma20,ma60]) and
             ma5 > ma10 > ma20 > ma60)
    pts = 10
    raw += pts if s3_ok else 0
    breakdown.append({
        "stage": "S", "label": "均線多頭排列（MA5>MA10>MA20>MA60）",
        "pts": pts, "met": s3_ok,
        "detail": (f"MA5={ma5:.1f} MA10={ma10:.1f} MA20={ma20:.1f} MA60={ma60:.1f}"
                   if not any(np.isnan(x) for x in [ma5,ma10,ma20,ma60]) else "均線資料不足"),
    })

    # ════════════════════════════════════════
    # Stage 4：Fundamental 護城河與未來（20分）
    # ════════════════════════════════════════

    # F1：近一季營收 YoY > 20% +10
    f1_ok = False
    f1_detail = "月營收資料無法取得"
    if rev_df is not None and len(rev_df) >= 14:
        try:
            # 取最新月份 vs 去年同月
            latest    = rev_df.iloc[-1]["revenue"]
            year_ago  = rev_df.iloc[-13]["revenue"]   # 往前推 12 個月
            yoy       = (latest - year_ago) / year_ago * 100 if year_ago > 0 else 0
            f1_ok     = yoy > 20
            f1_detail = f"最新月營收 YoY = {yoy:+.1f}%（需>20%）"
        except Exception:
            f1_detail = "YoY 計算失敗（資料不足）"
    pts = 10
    raw += pts if f1_ok else 0
    breakdown.append({
        "stage": "F", "label": "近一季月營收 YoY > 20%",
        "pts": pts, "met": f1_ok,
        "detail": f1_detail,
    })

    # F2：具備護城河（護城河清單 or 毛利率提升）+10
    is_moat = sid in MOAT_STOCKS
    f2_ok = is_moat   # 基礎：在已知護城河清單中
    f2_detail = ("已知護城河企業（寡占 / 技術領先 / 品牌壟斷）"
                 if is_moat else "非護城河清單，暫以 RS 代替")
    # 若不在護城河清單，但 RS 非常強（>10%），給予部分認可
    if not is_moat and not np.isnan(rs_3m) and rs_3m > 0.10:
        f2_ok = True
        f2_detail = f"非護城河清單，但 RS 極強（+{rs_3m*100:.1f}%），視為市場認可"
    pts = 10
    raw += pts if f2_ok else 0
    breakdown.append({
        "stage": "F", "label": "具備護城河（寡占／技術領先／品牌）",
        "pts": pts, "met": f2_ok,
        "detail": f2_detail,
    })

    # ── 最終計算 ─────────────────────────────────────────────
    final = float(max(0.0, min(100.0, raw)))

    # 評級
    if final >= 85:
        grade = "AAA"; grade_label = "極致強勢"; grade_action = "全力出擊，波段重倉"
        grade_color = "#00c87a"
    elif final >= 70:
        grade = "AA";  grade_label = "穩健進攻"; grade_action = "分批進場"
        grade_color = "#80d840"
    elif final >= 50:
        grade = "B";   grade_label = "技術反彈"; grade_action = "嚴禁重倉，小量短線"
        grade_color = "#f0a500"
    else:
        grade = "C";   grade_label = "高風險區"; grade_action = "絕對空手"
        grade_color = "#ff5c5c"

    # 買進信號：AA 以上 + 無死亡過濾
    signal = final >= 70 and not death_trigger

    # 原因文字（正向條件）
    pos_items = [b["label"] for b in breakdown if b["met"] and b["pts"] > 0]
    neg_items = [b["label"] for b in breakdown if b["met"] and b["pts"] < 0]
    reason_parts = []
    if pos_items:
        reason_parts.append("✅ " + " ｜ ".join(pos_items))
    if neg_items:
        reason_parts.append("🔴 " + " ｜ ".join(neg_items))
    reason = "  ".join(reason_parts) if reason_parts else "⬜ 未達任何條件"

    warning = ""
    if death_trigger:
        warning = "⚠️ 死亡過濾觸發：大盤跌破季線，極度不建議進場"
    elif final < 50:
        warning = f"⚠️ 評分 {final:.0f} 分，屬高風險區（C 級），建議觀望"

    return {
        "signal":      signal,
        "score":       final,
        "grade":       grade,
        "grade_label": grade_label,
        "grade_action":grade_action,
        "grade_color": grade_color,
        "reason":      reason,
        "warning":     warning,
        "breakdown":   breakdown,
        "death_trigger": death_trigger,
        # 各階段分數（用於雷達圖/明細）
        "score_G": sum(b["pts"] for b in breakdown if b["stage"]=="G" and b["met"]),
        "score_P": sum(b["pts"] for b in breakdown if b["stage"]=="P" and b["met"]),
        "score_S": sum(b["pts"] for b in breakdown if b["stage"]=="S" and b["met"]),
        "score_F": sum(b["pts"] for b in breakdown if b["stage"]=="F" and b["met"]),
    }


def _gps_empty(reason: str = "") -> dict:
    return {
        "signal":False,"score":0.0,"grade":"C","grade_label":"資料不足",
        "grade_action":"無法評分","grade_color":"#ff5c5c",
        "reason":reason,"warning":reason,"breakdown":[],
        "death_trigger":False,
        "score_G":0,"score_P":0,"score_S":0,"score_F":0,
    }


# ════════════════════════════════════════════════════════════════
# ⑥-b  族群資料計算（Peer Group Stats）
# ════════════════════════════════════════════════════════════════

def compute_sector_stats(sector_dfs: dict[str, list[float]]) -> dict[str, dict]:
    """
    輸入：{產業名稱: [各股今日漲跌%]} 字典
    輸出：{產業名稱: {avg_chg, strong_count, vol_rank}} 字典

    在掃描開始前輕量計算，供 GPS P 階段使用。
    """
    sector_stats = {}
    sector_volumes = {}   # {產業: 平均成交量（用於排名）}

    for sector, chgs_vols in sector_dfs.items():
        chgs = [cv[0] for cv in chgs_vols]
        vols = [cv[1] for cv in chgs_vols]
        avg_chg      = float(np.mean(chgs)) if chgs else 0.0
        strong_count = sum(1 for c in chgs if c > 3.0)
        avg_vol      = float(np.mean(vols)) if vols else 0.0
        sector_stats[sector]   = {"avg_chg": avg_chg, "strong_count": strong_count}
        sector_volumes[sector] = avg_vol

    # 計算成交值排名
    sorted_sectors = sorted(sector_volumes, key=lambda s: sector_volumes[s], reverse=True)
    for rank, sec in enumerate(sorted_sectors, 1):
        sector_stats[sec]["vol_rank"] = rank

    return sector_stats


# ════════════════════════════════════════════════════════════════
# ⑥-c  大盤狀態（升級版，供 GPS 使用）
# ════════════════════════════════════════════════════════════════

def get_market_state(token: str = "") -> dict:
    """取得大盤狀態，回傳 GPS Stage 1 需要的欄位。"""
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=380)).strftime("%Y-%m-%d")
    df = fetch_taiex(start, end, token)

    base = {
        "signal": "neutral", "status": "無法取得",
        "close": None, "ma20": None, "ma60": None, "ma240": None,
        "rsi": 50.0, "pos_ratio": 0.7, "date": "N/A",
        "above_20ma": False, "below_60ma": False, "no_panic": True,
    }

    if df.empty or len(df) < 60:
        return base

    df = compute_all_indicators(df)
    last = df.iloc[-1]

    cl   = float(last["Close"])
    m20  = float(last["MA20"])  if not pd.isna(last.get("MA20"))  else None
    m60  = float(last["MA60"])  if not pd.isna(last.get("MA60"))  else None
    m240 = float(last["MA240"]) if not pd.isna(last.get("MA240")) else None
    rsi  = float(last["RSI"])   if not pd.isna(last.get("RSI"))   else 50.0

    above_20 = m20  is not None and cl > m20
    above_60 = m60  is not None and cl > m60
    below_60 = m60  is not None and cl < m60
    above_240= m240 is not None and cl > m240

    if above_60 and above_240:
        signal = "bullish"; status = "強多頭"; pos = 1.0
    elif above_60:
        signal = "neutral"; status = "弱多頭"; pos = 0.7
    else:
        signal = "bearish"; status = "空頭警示"; pos = 0.3

    return {
        "signal":     signal, "status":  status,
        "close":      cl,     "ma20":    m20,
        "ma60":       m60,    "ma240":   m240,
        "rsi":        rsi,
        "pos_ratio":  pos,
        "date":       last["date"].strftime("%Y-%m-%d"),
        "above_20ma": above_20,
        "below_60ma": below_60,
        "no_panic":   rsi < 80,   # RSI > 80 視為市場過熱
    }


# ── 保留三個原始評分函式以供向下相容（自選股三線分析仍需要）──────
def score_longterm(df, **_):  return _compat_score(df, "long")
def score_midterm(df,  **_):  return _compat_score(df, "mid")
def score_shortterm(df,**_):  return _compat_score(df, "short")

def _compat_score(df, mode):
    """快速模式：提供向下相容的分數，供舊版 analyze_custom_stock 使用"""
    if len(df) < 20: return {"signal":False,"score":0,"reason":"資料不足","breakdown":[],"warning":""}
    last = df.iloc[-1]
    def _v(c): return float(last[c]) if not pd.isna(last.get(c)) else np.nan
    close=float(last["Close"]); ma20=_v("MA20"); ma60=_v("MA60"); ma240=_v("MA240")
    rsi=_v("RSI"); macd_h=_v("MACD_hist"); rs=_v("RS_3m")
    sl60=_v("MA60_slope"); sl240=_v("MA240_slope")
    vol=float(last.get("Volume",0)); p_vol=float(df.iloc[-2].get("Volume",1) if len(df)>=2 else 1)
    score=0; bd=[]; sig=False
    if mode=="short":
        c1=not np.isnan(ma20) and close>ma20;   score+=25 if c1 else 0; bd.append(("站上20MA",25,c1,""))
        c2=not np.isnan(rsi) and 50<=rsi<=70;   score+=25 if c2 else 0; bd.append((f"RSI甜蜜區{rsi:.0f}",25,c2,""))
        c3=not np.isnan(macd_h) and macd_h>0;   score+=25 if c3 else 0; bd.append(("MACD向上",25,c3,""))
        c4=p_vol>0 and vol>p_vol*1.5;            score+=25 if c4 else 0; bd.append(("今日爆量",25,c4,""))
        sig=score>=70 and c1
    elif mode=="mid":
        c1=not np.isnan(ma60) and close>ma60 and not np.isnan(sl60) and sl60>0; score+=50 if c1 else 0; bd.append(("季線多頭",50,c1,""))
        c2=not np.isnan(rs) and rs>0;            score+=30 if c2 else 0; bd.append(("RS優於大盤",30,c2,""))
        c3=not np.isnan(ma20) and close>ma20;    score+=20 if c3 else 0; bd.append(("站上月線",20,c3,""))
        sig=score>=60 and c1
    else:
        c1=not np.isnan(ma240) and close>ma240 and not np.isnan(sl240) and sl240>0; score+=55 if c1 else 0; bd.append(("年線多頭",55,c1,""))
        c2=not np.isnan(rs) and rs>0;            score+=25 if c2 else 0; bd.append(("RS優於大盤",25,c2,""))
        c3=not np.isnan(ma20) and close>ma20;    score+=20 if c3 else 0; bd.append(("站上月線",20,c3,""))
        sig=score>=65 and c1
    pos=[b[0] for b in bd if b[2] and b[1]>0]
    return {"signal":sig,"score":float(min(100,score)),"reason":"✅ "+" ｜ ".join(pos) if pos else "⬜ 未達條件",
            "breakdown":bd,"warning":""}

#
# Stage 2 = 股票進入主升段
# 必要條件：
#   ① 收盤 > 240MA（年線）
#   ② 240MA 斜率向上
#   ③ 120MA > 240MA（中長線多頭排列）
# 加分項：
#   RS vs 大盤正值（領先大盤）
#   收盤距 52 週高點在 5% 以內（強勢）
#   RSI > 50（動能偏多）
# 懲罰：跌破 120MA 強制扣分

def score_longterm(df: pd.DataFrame) -> dict:
    """
    長線評分（1 年以上持有）
    參考：Stan Weinstein Stage Analysis
    滿分 100，買進門檻 60
    """
    if len(df) < 240 or "MA240" not in df.columns:
        return _empty_score("長線", "資料不足（需 240 日以上歷史）")

    last = df.iloc[-1]
    close   = float(last["Close"])

    def _v(col): return float(last[col]) if not pd.isna(last.get(col)) else np.nan

    ma120 = _v("MA120"); ma240 = _v("MA240")
    sl240 = _v("MA240_slope"); sl120 = _v("MA120_slope")
    rs    = _v("RS_3m");   rsi = _v("RSI")
    pct52 = _v("Pct_from_52H")
    gain6 = _v("Gain_6m")

    breakdown = []
    raw = 0.0

    # 必要條件 ① 站上年線 +30
    c1 = not np.isnan(ma240) and close > ma240
    pts = 30
    raw += pts if c1 else 0
    breakdown.append(("站上 240MA 年線", pts, c1,
                       f"收 {close:.1f} / 年線 {ma240:.1f}" if not np.isnan(ma240) else "N/A"))

    # 必要條件 ② 年線斜率向上 +25
    c2 = not np.isnan(sl240) and sl240 > 0
    pts = 25
    raw += pts if c2 else 0
    breakdown.append(("年線（240MA）斜率向上", pts, c2,
                       f"斜率 {sl240:+.3f}" if not np.isnan(sl240) else "N/A"))

    # 必要條件 ③ 120MA > 240MA（多頭排列）+20
    c3 = not np.isnan(ma120) and not np.isnan(ma240) and ma120 > ma240
    pts = 20
    raw += pts if c3 else 0
    breakdown.append(("120MA > 240MA（半年線凌駕年線）", pts, c3,
                       f"120MA {ma120:.1f} / 240MA {ma240:.1f}" if not np.isnan(ma120) else "N/A"))

    # 加分 ④ 相對強度正值（領先大盤）+15
    c4 = not np.isnan(rs) and rs > 0
    pts = 15
    raw += pts if c4 else 0
    breakdown.append(("RS 相對強度優於大盤", pts, c4,
                       f"RS {rs*100:+.1f}%" if not np.isnan(rs) else "無大盤資料"))

    # 加分 ⑤ 距 52 週高點 10% 以內（強勢股）+10
    c5 = not np.isnan(pct52) and pct52 >= -10
    pts = 10
    raw += pts if c5 else 0
    breakdown.append(("距 52 週高點 10% 以內", pts, c5,
                       f"距高點 {pct52:.1f}%" if not np.isnan(pct52) else "N/A"))

    # 懲罰：跌破 120MA → 長線趨勢動搖 -25
    below_120 = not np.isnan(ma120) and close < ma120
    if below_120:
        raw -= 25
        breakdown.append(("跌破 120MA 半年線（懲罰）", -25, True,
                           f"收 {close:.1f} < 半年線 {ma120:.1f}"))

    final = float(max(0.0, min(100.0, raw)))
    signal = (final >= 60) and c1 and c2 and (not below_120)

    return _build_result("長線", final, signal, breakdown, last)


# ── 6-B 中線：CANSLIM 精簡版（O'Neil）────────────────────────
#
# N = 新高突破（股價接近 52 週高點）
# S = 供需（量能放大驗證）
# L = 領導股（RS 勝大盤）
# I = 法人認同（用量能趨勢近似）
# M = 市場方向（大盤 60MA 濾網）

def score_midterm(df: pd.DataFrame) -> dict:
    """
    中線評分（6-12 個月持有）
    參考：William O'Neil CANSLIM
    滿分 100，買進門檻 55
    """
    if len(df) < 65 or "MA60" not in df.columns:
        return _empty_score("中線", "資料不足（需 65 日以上）")

    last = df.iloc[-1]
    close = float(last["Close"])

    def _v(col): return float(last[col]) if not pd.isna(last.get(col)) else np.nan

    ma20 = _v("MA20"); ma60 = _v("MA60")
    sl60 = _v("MA60_slope")
    rs   = _v("RS_3m"); rsi = _v("RSI")
    pct52 = _v("Pct_from_52H")
    gain6 = _v("Gain_6m"); gain1 = _v("Gain_1m")
    vol   = float(last["Volume"]) if not pd.isna(last.get("Volume")) else 0
    volma = float(last["VolMA20"]) if not pd.isna(last.get("VolMA20")) else 0

    breakdown = []
    raw = 0.0

    # N：站上 60MA 季線 +25
    c1 = not np.isnan(ma60) and close > ma60
    pts = 25
    raw += pts if c1 else 0
    breakdown.append(("站上 60MA 季線（N-新）", pts, c1,
                       f"收 {close:.1f} / 季線 {ma60:.1f}" if not np.isnan(ma60) else "N/A"))

    # 季線斜率向上 +20
    c2 = not np.isnan(sl60) and sl60 > 0
    pts = 20
    raw += pts if c2 else 0
    breakdown.append(("季線斜率向上（趨勢確立）", pts, c2,
                       f"斜率 {sl60:+.3f}" if not np.isnan(sl60) else "N/A"))

    # L：RS 相對強度 +20
    c3 = not np.isnan(rs) and rs > 0
    pts = 20
    raw += pts if c3 else 0
    breakdown.append(("RS 相對強度優於大盤（L-領導）", pts, c3,
                       f"RS {rs*100:+.1f}%" if not np.isnan(rs) else "無大盤資料"))

    # S：量能 > 均量（需求浮現）+20
    c4 = volma > 0 and vol > volma * 1.2
    pts = 20
    raw += pts if c4 else 0
    vol_r = vol / volma if volma > 0 else 0
    breakdown.append((f"量能放大（S-需求，量比 {vol_r:.1f}×）", pts, c4, ""))

    # 站上 20MA +10
    c5 = not np.isnan(ma20) and close > ma20
    pts = 10
    raw += pts if c5 else 0
    breakdown.append(("站上 20MA 月線", pts, c5,
                       f"月線 {ma20:.1f}" if not np.isnan(ma20) else "N/A"))

    # 懲罰：跌破 60MA 季線 -30
    below_60 = not np.isnan(ma60) and close < ma60
    if below_60:
        raw -= 30
        breakdown.append(("跌破 60MA 季線（懲罰）", -30, True, f"收 {close:.1f} < 季線 {ma60:.1f}"))

    final = float(max(0.0, min(100.0, raw)))
    signal = (final >= 55) and c1 and c2 and (not below_60)

    return _build_result("中線", final, signal, breakdown, last)


# ── 6-C 短線：Williams 動能 + RSI/MACD ───────────────────────
#
# 參考 Larry Williams「買在力量，賣在強勢」
# RSI 50-70 甜蜜區（動能健康，未過熱）
# MACD 金叉或柱狀圖轉正
# 爆量突破（今日量 > 昨日 × 1.5）
# 價格 > 20MA（短線趨勢向上）

def score_shortterm(df: pd.DataFrame) -> dict:
    """
    短線評分（7 日內進出）
    參考：Larry Williams Momentum + RSI/MACD
    滿分 100，買進門檻 60
    """
    if len(df) < 26 or "RSI" not in df.columns:
        return _empty_score("短線", "資料不足（需 26 日以上）")

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close  = float(last["Close"])
    p_close = float(prev["Close"])

    def _v(col): return float(last[col]) if not pd.isna(last.get(col)) else np.nan
    def _p(col): return float(prev[col]) if not pd.isna(prev.get(col)) else np.nan

    ma5   = _v("MA5");  ma20 = _v("MA20")
    rsi   = _v("RSI")
    macd  = _v("MACD"); macd_s = _v("MACD_signal"); macd_h = _v("MACD_hist")
    p_macd_h = _p("MACD_hist")
    bb_pct   = _v("BB_pct")

    vol    = float(last["Volume"]) if not pd.isna(last.get("Volume")) else 0
    p_vol  = float(prev["Volume"]) if not pd.isna(prev.get("Volume")) else 0
    vol_r  = vol / p_vol if p_vol > 0 else 0

    breakdown = []
    raw = 0.0

    # ① RSI 甜蜜區 50-70 +25
    rsi_ok = not np.isnan(rsi) and 50 <= rsi <= 70
    pts = 25
    raw += pts if rsi_ok else 0
    rsi_lbl = f"RSI={rsi:.1f}（{'✅ 甜蜜區 50-70' if rsi_ok else '⚠️ 偏高' if rsi > 70 else '偏低'}）"
    breakdown.append((rsi_lbl, pts, rsi_ok, ""))

    # ② MACD 動能向上（柱狀圖 > 0 或剛轉正）+25
    macd_bull = (not np.isnan(macd_h) and macd_h > 0) or \
                (not np.isnan(macd_h) and not np.isnan(p_macd_h) and
                 macd_h > p_macd_h and macd_h > -0.5)
    pts = 25
    raw += pts if macd_bull else 0
    breakdown.append(("MACD 柱狀圖向上（動能偏多）", pts, macd_bull,
                       f"MACD={macd:.3f}, 訊號線={macd_s:.3f}" if not np.isnan(macd) else "N/A"))

    # ③ 今日量 > 昨日量 1.5× +25
    vol_surge = vol_r >= 1.5
    pts = 25
    raw += pts if vol_surge else 0
    breakdown.append((f"爆量確認（今日量 {vol_r:.1f}× 昨日）", pts, vol_surge, ""))

    # ④ 站上 5MA + 20MA +15（各 7.5）
    c5ma  = not np.isnan(ma5)  and close > ma5
    c20ma = not np.isnan(ma20) and close > ma20
    pts5 = 8; pts20 = 7
    raw += pts5  if c5ma  else 0
    raw += pts20 if c20ma else 0
    breakdown.append(("站上 5MA（短線多頭）", pts5,  c5ma,  f"5MA={ma5:.1f}"  if not np.isnan(ma5)  else "N/A"))
    breakdown.append(("站上 20MA（月線支撐）",pts20, c20ma, f"20MA={ma20:.1f}" if not np.isnan(ma20) else "N/A"))

    # ⑤ 當日上漲（動能方向）+5（bonus，不影響 signal）
    up_day = close > p_close
    raw += 5 if up_day else 0

    # 懲罰：RSI > 75 過熱 -20
    overbought = not np.isnan(rsi) and rsi > 75
    if overbought:
        raw -= 20
        breakdown.append(("RSI 過熱 > 75（懲罰，追高風險）", -20, True, f"RSI={rsi:.1f}"))


# ════════════════════════════════════════════════════════════════
# ⑦ 改良版買賣建議（Van Tharp ATR × Fibonacci 雙驗證）
# ════════════════════════════════════════════════════════════════
#
# 核心改良：RR 從「進場價（entry price）」計算，不從現價算
#   進場價  = 建議買進區間中點
#   停損    = 進場價 - 1.5×ATR（短線）/ 2.0×ATR（中長線）
#   目標一  = 進場價 + 2.0×ATR（RR ≥ 1:1.3）
#   目標二  = 前高阻力 × 98%（Fibonacci 61.8% 或前高）
#   最終 RR = (目標一 - 進場) / (進場 - 停損)

def compute_trade_zones(df: pd.DataFrame, mode: str = "short") -> dict:
    if len(df) < 20:
        return {}

    last   = df.iloc[-1]
    close  = float(last["Close"])
    atr    = float(last["ATR"])  if not pd.isna(last.get("ATR"))  else close * 0.02
    ma20   = float(last["MA20"]) if not pd.isna(last.get("MA20")) else close
    ma60   = float(last["MA60"]) if not pd.isna(last.get("MA60")) else close
    ma120  = float(last["MA120"])if not pd.isna(last.get("MA120")) else close
    ma240  = float(last["MA240"])if not pd.isna(last.get("MA240")) else close
    hi52w  = float(last["High52W"]) if not pd.isna(last.get("High52W")) else close * 1.15
    lo52w  = float(last["Low52W"])  if not pd.isna(last.get("Low52W"))  else close * 0.85

    # Fibonacci 延伸（從 52 週低點到 52 週高點）
    fib_range  = hi52w - lo52w
    fib_61_ext = hi52w + fib_range * 0.618   # 突破後的 61.8% 延伸

    if mode == "short":
        # 短線：等回踩 20MA 附近買
        # 進場區：MA20 ± 0.5%，若現價已在此範圍直接買
        entry_low  = round(ma20 * 0.998, 1)
        entry_high = round(ma20 * 1.015, 1)
        entry_mid  = round((entry_low + entry_high) / 2, 1)
        stop_atr   = 1.5
        target_atr = 2.5
        stop_loss  = round(entry_mid - stop_atr * atr, 1)
        target1    = round(entry_mid + target_atr * atr, 1)
        # 目標二：前高阻力（近 60 日高點下方 2%）
        recent_high = float(df["High"].tail(60).max()) if "High" in df.columns else close * 1.08
        target2 = round(recent_high * 0.98, 1)
        stop_note = f"跌破 20MA 下方 1.5×ATR（{stop_loss:.1f}）"

    elif mode == "mid":
        # 中線：回測季線附近買
        entry_low  = round(ma60 * 0.998, 1)
        entry_high = round(ma60 * 1.025, 1)
        entry_mid  = round((entry_low + entry_high) / 2, 1)
        stop_atr   = 2.0
        stop_loss  = round(entry_mid - stop_atr * atr, 1)
        target1    = round(entry_mid + 3.0 * atr, 1)
        target2    = round(hi52w * 0.97, 1)   # 接近 52 週高點前保守出場
        stop_note  = f"跌破 60MA 季線下方 2×ATR（{stop_loss:.1f}）"

    else:  # long
        # 長線：回測年線或半年線附近買
        anchor = ma120 if close > ma240 else ma240
        entry_low  = round(anchor * 0.99, 1)
        entry_high = round(anchor * 1.03, 1)
        entry_mid  = round((entry_low + entry_high) / 2, 1)
        stop_atr   = 2.5
        stop_loss  = round(entry_mid - stop_atr * atr, 1)
        target1    = round(entry_mid + 4.0 * atr, 1)
        target2    = round(fib_61_ext, 1)   # Fibonacci 61.8% 延伸目標
        stop_note  = f"跌破半年線/年線下方 2.5×ATR（{stop_loss:.1f}）"

    # 從「進場中點」計算 RR
    risk   = max(entry_mid - stop_loss, atr * 0.5)
    reward = target1 - entry_mid
    rr     = round(reward / risk, 2) if risk > 0 else 0.0

    # 現價 vs 進場區判斷
    if close <= entry_high:
        entry_note = "✅ 現價已在建議買進區間內，可考慮進場"
    elif close <= entry_high * 1.05:
        entry_note = "⚠️ 現價略高於建議區間，可小量試單，等回踩再加碼"
    else:
        gap_pct = (close - entry_high) / entry_high * 100
        entry_note = f"❌ 現價高於建議區間 {gap_pct:.1f}%，建議等待回踩再進場"

    return {
        "entry_low":   entry_low,
        "entry_high":  entry_high,
        "entry_mid":   entry_mid,
        "stop_loss":   stop_loss,
        "target1":     target1,
        "target2":     target2,
        "risk_reward": rr,
        "atr":         round(atr, 2),
        "stop_note":   stop_note,
        "entry_note":  entry_note,
    }


# ════════════════════════════════════════════════════════════════
# ⑧ 回測引擎（簡易版，供統計用）
# ════════════════════════════════════════════════════════════════

def quick_backtest(df: pd.DataFrame, mode: str = "mid") -> dict:
    df = df.copy().reset_index(drop=True)
    if len(df) < 20:
        return {"return": 0.0, "win_rate": 0.0, "mdd": 0.0, "trades": 0}

    in_pos = False; entry_p = 0.0; trades = []; equity = [1.0]

    for i in range(1, len(df)):
        r = df.iloc[i]
        p = df.iloc[i-1]
        ma20 = r.get("MA20", np.nan); ma60 = r.get("MA60", np.nan)
        rsi  = r.get("RSI",  np.nan); macd_h = r.get("MACD_hist", np.nan)
        vol  = float(r.get("Volume", 0)); p_vol = float(p.get("Volume", 1))
        cl   = float(r["Close"])

        if mode == "short":
            buy_sig  = (not np.isnan(ma20) and cl > ma20 and
                        not np.isnan(rsi) and 50 <= rsi <= 70 and
                        not np.isnan(macd_h) and macd_h > 0 and
                        p_vol > 0 and vol > p_vol * 1.5)
            sell_sig = not np.isnan(ma20) and cl < ma20
        elif mode == "mid":
            buy_sig  = (not np.isnan(ma60) and cl > ma60 and
                        not np.isnan(r.get("MA60_slope")) and r["MA60_slope"] > 0)
            sell_sig = not np.isnan(ma60) and cl < ma60
        else:
            ma240 = r.get("MA240", np.nan)
            buy_sig  = (not np.isnan(ma240) and cl > ma240 and
                        not np.isnan(r.get("MA240_slope")) and r["MA240_slope"] > 0)
            sell_sig = not np.isnan(ma240) and cl < ma240

        if not in_pos and buy_sig:
            entry_p = cl * (1 + SLIPPAGE + TRANSACTION_COST); in_pos = True
        elif in_pos and sell_sig:
            ex = cl * (1 - SLIPPAGE - TRANSACTION_COST)
            ret = (ex - entry_p) / entry_p; trades.append(ret)
            equity.append(equity[-1] * (1 + ret)); in_pos = False

    if in_pos:
        ex = float(df.iloc[-1]["Close"]) * (1 - SLIPPAGE - TRANSACTION_COST)
        ret = (ex - entry_p) / entry_p; trades.append(ret)
        equity.append(equity[-1] * (1 + ret))

    if not trades:
        return {"return": 0.0, "win_rate": 0.0, "mdd": 0.0, "trades": 0}

    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    mdd  = float(((eq - peak) / peak).min() * 100)

    return {
        "return":   round((eq[-1] - 1) * 100, 2),
        "win_rate": round(sum(1 for t in trades if t > 0) / len(trades) * 100, 1),
        "mdd":      round(mdd, 2),
        "trades":   len(trades),
    }


# ════════════════════════════════════════════════════════════════
# ⑨ 大盤狀態
# ════════════════════════════════════════════════════════════════

def get_market_state(token: str = "") -> dict:
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=380)).strftime("%Y-%m-%d")
    df = fetch_taiex(start, end, token)
    if df.empty or len(df) < 60:
        return {"signal": "neutral", "status": "無法取得", "close": None,
                "ma60": None, "ma240": None, "pos_ratio": 1.0, "date": "N/A"}
    df = compute_all_indicators(df)
    last = df.iloc[-1]
    cl   = float(last["Close"])
    m60  = float(last["MA60"])  if not pd.isna(last.get("MA60"))  else None
    m240 = float(last["MA240"]) if not pd.isna(last.get("MA240")) else None

    above_60  = m60  is not None and cl > m60
    above_240 = m240 is not None and cl > m240

    if above_60 and above_240:
        signal = "bullish"; status = "強多頭"; pos = 1.0
    elif above_60:
        signal = "neutral"; status = "弱多頭"; pos = 0.7
    else:
        signal = "bearish"; status = "空頭警示"; pos = 0.3

    return {"signal": signal, "status": status, "close": cl,
            "ma60": m60, "ma240": m240, "pos_ratio": pos,
            "date": last["date"].strftime("%Y-%m-%d")}


# ════════════════════════════════════════════════════════════════
# ⑩ 掃描引擎（按產業掃描）
# ════════════════════════════════════════════════════════════════

def scan_sector(sector: str, token: str, taiex_df: pd.DataFrame,
                start: str, end: str, max_per_sector: int,
                market_data: dict, sector_stats: dict,
                scan_mode: str = "mid") -> list[dict]:
    stocks  = SECTOR_STOCKS.get(sector, [])[:max_per_sector]
    results = []
    mode_label = {"short":"短線 7日","mid":"中線 6-12月","long":"長線 1年+"}[scan_mode]

    for sid in stocks:
        df = fetch_price(sid, start, end, token)
        if df.empty or len(df) < 30:
            time.sleep(0.2); continue

        df      = compute_all_indicators(df, taiex_df)
        rev_df  = fetch_monthly_revenue(sid, token)
        sec_st  = sector_stats.get(sector, {"avg_chg":0,"strong_count":0,"vol_rank":99})

        gps   = score_gps(df, market_data, sec_st, rev_df, sid)

        # 低分跳過（門檻依模式調整）
        min_threshold = {"short": 45, "mid": 45, "long": 40}[scan_mode]
        if gps["score"] < min_threshold:
            time.sleep(0.15); continue

        bt    = quick_backtest(df, scan_mode)
        zones = compute_trade_zones(df, scan_mode)
        last  = df.iloc[-1]
        prev  = df.iloc[-2] if len(df) >= 2 else last
        chg   = (float(last["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100

        results.append({
            "代號":       sid,
            "名稱":       STOCK_NAMES.get(sid, sid),
            "產業":       sector,
            "模式":       mode_label,
            "收盤價":     round(float(last["Close"]), 1),
            "漲跌%":      round(chg, 2),
            "信號":       "✅ 買進" if gps["signal"] else "⬜ 觀察",
            "評分":       round(gps["score"], 1),
            "評級":       gps["grade"],
            "評級標籤":   gps["grade_label"],
            "行動":       gps["grade_action"],
            "評級色":     gps["grade_color"],
            "原因":       gps["reason"],
            "警告":       gps["warning"],
            "G分":        gps["score_G"],
            "P分":        gps["score_P"],
            "S分":        gps["score_S"],
            "F分":        gps["score_F"],
            "回測報酬%":  bt["return"],
            "勝率%":      bt["win_rate"],
            "MDD%":       bt["mdd"],
            "_mode":      scan_mode,
            "_zones":     zones,
            "_gps":       gps,
        })
        time.sleep(0.3)

    return results


@st.cache_data(ttl=1800, show_spinner=False)
def run_full_scan(sectors: list, token: str, max_per_sector: int,
                  scan_mode: str = "mid") -> pd.DataFrame:
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=380)).strftime("%Y-%m-%d")

    taiex_df    = fetch_taiex(start, end, token)
    market_data = get_market_state(token)

    prog = st.progress(0.0)
    stat = st.empty()

    # ── Phase 1：輕量預掃描（族群動能）──────────────────────
    stat.markdown(
        "<span style='color:#4a8aaa;font-size:0.8rem;'>⚡ 預掃描族群動能…</span>",
        unsafe_allow_html=True
    )
    sector_raw: dict[str, list] = {}
    pre_start = (datetime.today() - timedelta(days=10)).strftime("%Y-%m-%d")

    for i, sector in enumerate(sectors):
        prog.progress((i + 1) / len(sectors) * 0.3)
        chgs_vols = []
        for sid in SECTOR_STOCKS.get(sector, [])[:4]:
            try:
                df_tmp = fetch_price(sid, pre_start, end, token)
                if df_tmp.empty or len(df_tmp) < 2: continue
                chg = (float(df_tmp.iloc[-1]["Close"]) - float(df_tmp.iloc[-2]["Close"])) \
                      / float(df_tmp.iloc[-2]["Close"]) * 100
                vol = float(df_tmp.iloc[-1].get("Volume", 0))
                chgs_vols.append((chg, vol))
                time.sleep(0.15)
            except Exception:
                continue
        sector_raw[sector] = chgs_vols

    sector_stats = compute_sector_stats(sector_raw)

    # ── Phase 2：GPS 評分 ────────────────────────────────────
    all_results = []
    for i, sector in enumerate(sectors):
        stat.markdown(
            f"<span style='color:#4a8aaa;font-size:0.8rem;'>📊 {sector}…"
            f"（{i+1}/{len(sectors)}）</span>",
            unsafe_allow_html=True
        )
        prog.progress(0.3 + (i + 1) / len(sectors) * 0.7)
        rows = scan_sector(sector, token, taiex_df, start, end,
                           max_per_sector, market_data, sector_stats, scan_mode)
        all_results.extend(rows)

    prog.empty(); stat.empty()

    if not all_results:
        return pd.DataFrame()

    df = pd.DataFrame(all_results)
    df = df.sort_values("評分", ascending=False).reset_index(drop=True)
    return df


# ════════════════════════════════════════════════════════════════
# ⑪ 自選股分析
# ════════════════════════════════════════════════════════════════

def analyze_custom_stock(stock_id: str, token: str) -> dict:
    """
    對單一股票做三線全面分析。
    回傳：{short, mid, long, zones_short, zones_mid, zones_long, df, market}
    """
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=380)).strftime("%Y-%m-%d")

    df = fetch_price(stock_id, start, end, token)
    if df.empty:
        return {}

    taiex_df = fetch_taiex(start, end, token)
    df = compute_all_indicators(df, taiex_df)

    return {
        "short":       score_shortterm(df),
        "mid":         score_midterm(df),
        "long":        score_longterm(df),
        "zones_short": compute_trade_zones(df, "short"),
        "zones_mid":   compute_trade_zones(df, "mid"),
        "zones_long":  compute_trade_zones(df, "long"),
        "bt_short":    quick_backtest(df, "short"),
        "bt_mid":      quick_backtest(df, "mid"),
        "bt_long":     quick_backtest(df, "long"),
        "df":          df,
        "name":        STOCK_NAMES.get(stock_id, stock_id),
    }


# ════════════════════════════════════════════════════════════════
# ⑫ K 線圖（含 RSI / MACD）
# ════════════════════════════════════════════════════════════════

_BG  = "#050e1a"; _PAPER = "#030b14"; _GRID = "#0e2035"
_UP  = "#00c87a"; _DN    = "#ff5c5c"
_MA5 = "#f0c040"; _MA20  = "#4ab3ff"; _MA60 = "#c084fc"
_M120= "#ff9060"; _M240  = "#80ffcc"


def build_chart(df: pd.DataFrame, sid: str, name: str) -> go.Figure:
    df = df.tail(180).reset_index(drop=True)

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.50, 0.18, 0.16, 0.16],
        vertical_spacing=0.02,
        subplot_titles=("", "成交量", "RSI(14)", "MACD(12,26,9)"),
    )

    # ── Row 1: K 線 + 均線 ──────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="K線",
        increasing_line_color=_UP, increasing_fillcolor=_UP,
        decreasing_line_color=_DN, decreasing_fillcolor=_DN,
        line=dict(width=1), whiskerwidth=0.3,
    ), row=1, col=1)

    for col, clr, w, dash in [
        ("MA5",  _MA5, 1.0, "dot"),  ("MA20", _MA20, 1.6, "solid"),
        ("MA60", _MA60,1.8, "solid"),("MA120",_M120, 1.8, "dash"),
        ("MA240",_M240,2.0, "dash"),
    ]:
        if col in df.columns and df[col].notna().any():
            fig.add_trace(go.Scatter(
                x=df["date"], y=df[col], name=col,
                line=dict(color=clr, width=w, dash=dash),
                hovertemplate=f"{col}: %{{y:.1f}}<extra></extra>",
            ), row=1, col=1)

    # Bollinger Bands（填色帶）
    if "BB_upper" in df.columns:
        fig.add_trace(go.Scatter(x=df["date"], y=df["BB_upper"],
            line=dict(color="rgba(74,179,255,0.3)", width=0.8, dash="dot"),
            name="BB Upper", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["BB_lower"],
            fill="tonexty", fillcolor="rgba(74,179,255,0.04)",
            line=dict(color="rgba(74,179,255,0.3)", width=0.8, dash="dot"),
            name="BB Lower", showlegend=False), row=1, col=1)

    # ── Row 2: 成交量 ────────────────────────────────────────
    if "Volume" in df.columns:
        vol_c = [_UP if float(c) >= float(o) else _DN
                 for c, o in zip(df["Close"], df["Open"])]
        # 使用 rgba 格式，不用 8 位 hex（Plotly 不接受 #rrggbbaa 格式）
        vol_rgba = ["rgba(0,200,122,0.45)" if c == _UP else "rgba(255,92,92,0.45)"
                    for c in vol_c]
        fig.add_trace(go.Bar(x=df["date"], y=df["Volume"],
            marker_color=vol_rgba,
            showlegend=False,
            hovertemplate="量：%{y:,.0f}<extra></extra>"), row=2, col=1)

    # ── Row 3: RSI ───────────────────────────────────────────
    if "RSI" in df.columns and df["RSI"].notna().any():
        fig.add_trace(go.Scatter(x=df["date"], y=df["RSI"], name="RSI",
            line=dict(color="#f0a500", width=1.5),
            hovertemplate="RSI: %{y:.1f}<extra></extra>"), row=3, col=1)
        for lvl, clr in [(70,"#ff5c5c44"), (50,"#4ab3ff44"), (30,"#00c87a44")]:
            fig.add_hline(y=lvl, row=3, col=1,
                line=dict(color=clr.replace("44",""), width=0.8, dash="dot"))

    # ── Row 4: MACD ──────────────────────────────────────────
    if "MACD" in df.columns and df["MACD"].notna().any():
        hist_c    = [_UP if v > 0 else _DN for v in df["MACD_hist"].fillna(0)]
        hist_rgba = ["rgba(0,200,122,0.55)" if c == _UP else "rgba(255,92,92,0.55)"
                     for c in hist_c]
        fig.add_trace(go.Bar(x=df["date"], y=df["MACD_hist"],
            marker_color=hist_rgba,
            name="MACD 柱", showlegend=False), row=4, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["MACD"],
            line=dict(color="#4ab3ff", width=1.4), name="MACD"), row=4, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["MACD_signal"],
            line=dict(color="#f0a500", width=1.2), name="訊號線"), row=4, col=1)
        fig.add_hline(y=0, row=4, col=1,
            line=dict(color="#2a4a6a", width=0.8, dash="dot"))

    last_c = float(df.iloc[-1]["Close"]) if len(df) else 0
    fig.update_layout(
        title=dict(
            text=f"<b>{sid} {name}</b>  "
                 f"<span style='font-size:13px;color:#4a8aaa;'>收盤 {last_c:,.1f}</span>",
            font=dict(size=16, color="#e8f4f8"), x=0.01,
        ),
        paper_bgcolor=_PAPER, plot_bgcolor=_BG,
        font=dict(family="IBM Plex Mono,Noto Sans TC,monospace", color="#8aabb8", size=10),
        legend=dict(orientation="h", x=0.01, y=1.02,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=9)),
        margin=dict(l=8, r=8, t=60, b=8), height=760, hovermode="x unified",
        xaxis_rangeslider_visible=False,
    )

    for r in [1,2,3,4]:
        fig.update_xaxes(row=r, col=1, gridcolor=_GRID, zeroline=False,
                         showspikes=True, spikecolor="#2a5a7a", spikethickness=1)
    fig.update_yaxes(row=1, gridcolor=_GRID, zeroline=False)
    fig.update_yaxes(row=2, gridcolor=_GRID, tickformat=".2s")
    fig.update_yaxes(row=3, gridcolor=_GRID, range=[0, 100], dtick=20)
    fig.update_yaxes(row=4, gridcolor=_GRID, zeroline=True, zerolinecolor="#2a4a6a")

    return fig


# ════════════════════════════════════════════════════════════════
# ⑬ UI 輔助元件
# ════════════════════════════════════════════════════════════════

def score_color(v: float) -> str:
    return "#00c87a" if v >= 70 else ("#f0a500" if v >= 50 else "#ff5c5c")

def rr_color(rr: float) -> str:
    return "#00c87a" if rr >= 2 else ("#f0a500" if rr >= 1 else "#ff5c5c")


def render_zones(zones: dict, signal: bool) -> str:
    if not zones or not signal:
        return ""
    el = zones.get("entry_low",  0)
    eh = zones.get("entry_high", 0)
    sl = zones.get("stop_loss",  0)
    t1 = zones.get("target1",    0)
    t2 = zones.get("target2",    0)
    rr = zones.get("risk_reward",0)
    atr= zones.get("atr",        0)
    note = zones.get("entry_note","")
    rc = rr_color(rr)
    rr_lbl = "優秀 ✅" if rr >= 2 else ("尚可 ⚠️" if rr >= 1 else "偏低 ❌")

    note_cls = ("color:#00c87a" if note.startswith("✅")
                else "color:#f0a500" if note.startswith("⚠️") else "color:#ff7878")

    return f"""
    <div class="zones-box">
      <div class="zones-title">💡 操作建議價位</div>
      <div class="zg">
        <div><span class="zl">📥 建議買進</span><br>
             <span class="zv-buy">{el:,.1f} ~ {eh:,.1f}</span></div>
        <div><span class="zl">🛑 停損價</span><br>
             <span class="zv-stop">{sl:,.1f}</span></div>
        <div><span class="zl">🎯 目標一（保守）</span><br>
             <span class="zv-t1">{t1:,.1f}</span></div>
        <div><span class="zl">🚀 目標二（積極）</span><br>
             <span class="zv-t2">{t2:,.1f}</span></div>
      </div>
      <div style="margin-top:6px;padding-top:6px;border-top:1px solid #112a40;font-size:0.72rem;">
        <span class="zl">⚖️ 風報比：</span>
        <span style="color:{rc};font-family:'IBM Plex Mono',monospace;">
          1:{rr:.1f} {rr_lbl}
        </span>
        &nbsp;｜&nbsp;<span class="zl">ATR：</span>
        <span style="color:#8aabb8;font-family:'IBM Plex Mono',monospace;">{atr:.2f}</span>
      </div>
      <div style="margin-top:5px;font-size:0.71rem;{note_cls};">{note}</div>
    </div>"""


def render_card(row: dict | pd.Series) -> str:
    signal   = row.get("信號","") == "✅ 買進"
    card_cls = "card-bull" if signal else "card-bear"
    sc       = float(row.get("評分", 0))
    grade    = row.get("評級", "C")
    g_lbl    = row.get("評級標籤", "")
    g_act    = row.get("行動", "")
    g_color  = row.get("評級色", "#ff5c5c")

    chg     = float(row.get("漲跌%", 0))
    chg_sym = "▲" if chg >= 0 else "▼"
    chg_cls = "#00c87a" if chg >= 0 else "#ff5c5c"
    ret     = float(row.get("回測報酬%", 0))
    ret_c   = "#00c87a" if ret >= 0 else "#ff5c5c"
    ret_sym = "+" if ret >= 0 else ""

    # GPS 四階段分數條
    sg = float(row.get("G分", 0)); sp = float(row.get("P分", 0))
    ss = float(row.get("S分", 0)); sf = float(row.get("F分", 0))
    def _seg(val, mx, clr, lbl):
        pct = min(val / mx * 100, 100)
        return (f'<div style="flex:1;margin:0 2px;">'
                f'<div style="font-size:0.58rem;color:#3a6a8a;margin-bottom:2px;">{lbl}</div>'
                f'<div style="background:#0e2030;border-radius:3px;height:5px;">'
                f'<div style="width:{pct:.0f}%;height:100%;border-radius:3px;background:{clr};"></div></div>'
                f'<div style="font-size:0.6rem;color:{clr};text-align:center;">{val:.0f}</div>'
                f'</div>')

    stage_bars = (
        f'<div style="display:flex;margin:6px 0 10px;gap:2px;">'
        f'{_seg(sg,20,"#4ab3ff","G大盤")}'
        f'{_seg(sp,25,"#c084fc","P族群")}'
        f'{_seg(ss,35,"#f0c040","S個股")}'
        f'{_seg(sf,20,"#00c87a","F基本面")}'
        f'</div>'
    )

    warn = str(row.get("警告",""))
    warn_html = (
        f'<div style="background:#1a0808;border-left:3px solid #ff5c5c;'
        f'border-radius:5px;padding:6px 9px;margin:7px 0;'
        f'font-size:0.7rem;color:#ffaaaa;">{warn}</div>'
    ) if warn else ""

    zones    = row.get("_zones", {}) or {}
    zones_html = render_zones(zones, signal)
    reason_html= str(row.get("原因","")).replace(" ｜ ","<br>&nbsp;·&nbsp;")

    return f"""
    <div class="stock-card {card_cls}">
      <div style="position:absolute;top:12px;right:14px;text-align:right;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:1.4rem;
                    font-weight:700;color:{g_color};">{sc:.0f}</div>
        <div style="background:{g_color}22;border:1px solid {g_color}55;border-radius:4px;
                    padding:1px 6px;font-size:0.65rem;font-weight:700;color:{g_color};">
          {grade} {g_lbl}</div>
      </div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;color:#3a7a9a;">
        {row.get('代號','')} &nbsp;·&nbsp; {row.get('產業','')}
      </div>
      <div style="font-size:1.1rem;font-weight:700;color:#e8f4f8;margin:2px 0 4px;">
        {row.get('名稱','')}
      </div>
      <div style="font-size:0.7rem;color:#2a6a8a;margin-bottom:4px;">📋 {g_act}</div>
      {stage_bars}
      <span style="font-family:'IBM Plex Mono',monospace;font-size:1.5rem;
                   font-weight:600;color:#e8f4f8;">
        {float(row.get('收盤價',0)):,.1f}
      </span>
      <span style="color:{chg_cls};font-size:0.9rem;">&nbsp;{chg_sym} {abs(chg):.2f}%</span>
      {warn_html}
      <div style="margin-top:7px;font-size:0.70rem;color:#6a9ab0;line-height:1.7;">
        {reason_html}
      </div>
      {zones_html}
      <hr style="border:none;border-top:1px solid #0e2030;margin:9px 0 7px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;color:#8aabb8;">
        回測<span style="color:{ret_c};">&nbsp;{ret_sym}{ret:.1f}%</span>
        &ensp;勝率&nbsp;{float(row.get('勝率%',0)):.0f}%
        &ensp;MDD&nbsp;<span style="color:#ff7878;">{float(row.get('MDD%',0)):.1f}%</span>
      </div>
    </div>"""


# ════════════════════════════════════════════════════════════════
# ⑭ 自選股分析 UI
# ════════════════════════════════════════════════════════════════

def render_analysis_panel(result: dict, sid: str):
    """顯示自選股三線分析結果"""
    name = result.get("name", sid)
    df   = result.get("df", pd.DataFrame())

    # 分數總覽
    sc_map = {"short":"短線 7日", "mid":"中線 6-12M", "long":"長線 1年+"}
    cols = st.columns(3)
    for i, (mode, label) in enumerate(sc_map.items()):
        sc_obj = result.get(mode, {})
        sc_val = sc_obj.get("score", 0)
        sig    = sc_obj.get("signal", False)
        sc_c   = score_color(sc_val)
        bt     = result.get(f"bt_{mode}", {})
        with cols[i]:
            st.markdown(
                f'<div class="stock-card {"card-bull" if sig else "card-bear"}">'
                f'<div style="font-size:0.78rem;color:#3a7a9a;font-family:\'IBM Plex Mono\';">{label}</div>'
                f'<div style="font-size:2.0rem;font-weight:700;color:{sc_c};">{sc_val:.0f}</div>'
                f'<div style="font-size:0.9rem;color:{"#00c87a" if sig else "#5a7a8a"};">'
                f'{"✅ 可考慮買進" if sig else "⬜ 建議觀望"}</div>'
                f'<hr style="border:none;border-top:1px solid #0e2030;margin:8px 0 6px;">'
                f'<div style="font-size:0.75rem;color:#7aacb8;">'
                f'回測 {bt.get("return",0):+.1f}%  '
                f'勝率 {bt.get("win_rate",0):.0f}%  '
                f'MDD {bt.get("mdd",0):.1f}%</div>'
                f'</div>', unsafe_allow_html=True
            )

    # 評分明細
    st.markdown('<div class="sec-title">評分明細</div>', unsafe_allow_html=True)
    for mode, label in sc_map.items():
        sc_obj = result.get(mode, {})
        bd     = sc_obj.get("breakdown", [])
        zones  = result.get(f"zones_{mode}", {})
        signal = sc_obj.get("signal", False)
        if not bd:
            continue

        with st.expander(f"{'✅' if signal else '⬜'} {label}　評分 {sc_obj.get('score',0):.0f}/100", expanded=signal):
            # 條件明細表
            rows_data = []
            for lbl, pts, met, detail in bd:
                rows_data.append({
                    "條件": lbl,
                    "分值": f"{pts:+d}" if pts != 0 else "0",
                    "達標": "✅" if (met and pts > 0) else ("🔴" if (met and pts < 0) else "❌"),
                    "數據": detail,
                })
            st.dataframe(pd.DataFrame(rows_data), use_container_width=True,
                         hide_index=True, height=min(200, len(rows_data) * 42 + 40))

            # 操作建議
            if signal and zones:
                el = zones.get("entry_low", 0);  eh = zones.get("entry_high", 0)
                sl = zones.get("stop_loss", 0);  t1 = zones.get("target1", 0)
                t2 = zones.get("target2", 0);    rr = zones.get("risk_reward", 0)
                atr= zones.get("atr", 0);        note = zones.get("entry_note", "")
                rc = rr_color(rr)
                st.markdown(
                    f'<div class="zones-box">'
                    f'<div class="zones-title">💡 {label} 操作建議</div>'
                    f'<div class="zg">'
                    f'<div><span class="zl">📥 建議買進</span><br>'
                    f'<span class="zv-buy" style="font-size:1rem;">{el:,.1f} ~ {eh:,.1f}</span></div>'
                    f'<div><span class="zl">🛑 停損價</span><br>'
                    f'<span class="zv-stop" style="font-size:1rem;">{sl:,.1f}</span></div>'
                    f'<div><span class="zl">🎯 目標一</span><br>'
                    f'<span class="zv-t1" style="font-size:1rem;">{t1:,.1f}</span></div>'
                    f'<div><span class="zl">🚀 目標二</span><br>'
                    f'<span class="zv-t2" style="font-size:1rem;">{t2:,.1f}</span></div>'
                    f'</div>'
                    f'<div style="margin-top:6px;font-size:0.75rem;">'
                    f'風報比 <span style="color:{rc};">1:{rr:.1f}</span> &nbsp;｜&nbsp; ATR {atr:.2f}'
                    f'</div>'
                    f'<div style="margin-top:5px;font-size:0.72rem;">{note}</div>'
                    f'</div>', unsafe_allow_html=True
                )
                st.caption(zones.get("stop_note", ""))


# ════════════════════════════════════════════════════════════════
# ⑮ 主程式
# ════════════════════════════════════════════════════════════════

def main():
    # ── Sidebar ──────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ 設定")

        token = st.text_input("FinMind Token（選填）", type="password",
                              placeholder="貼上 token 速度更快",
                              help="[免費申請](https://finmindtrade.com/)")

        st.divider()
        st.markdown("**🎯 選股模式**")

        scan_mode = st.radio(
            "選擇你的投資週期",
            options=["short", "mid", "long"],
            format_func=lambda x: {
                "short": "⚡ 短線（7日內）",
                "mid":   "📊 中線（6-12個月）",
                "long":  "🔭 長線（1年以上）",
            }[x],
            index=1,
            help="不同週期使用不同專家方法論與評分邏輯",
        )

        # 對應專家說明
        expert_map = {
            "short": [
                ("Mark Minervini", "VCP 壓縮突破、RS 相對強度"),
                ("Larry Williams", "波動率突破、威廉%R"),
                ("Dan Zanger",     "杯狀帶柄、爆量確認"),
            ],
            "mid": [
                ("William O'Neil", "CANSLIM 成長選股"),
                ("蔣承翰 / Mgk",   "族群動能、籌碼追蹤"),
                ("Stan Weinstein", "Stage 2 趨勢分析"),
            ],
            "long": [
                ("Warren Buffett", "護城河、ROE 品質"),
                ("Cathie Wood",    "破壞式創新、成長估值"),
                ("科斯托蘭尼",      "大週期判斷、耐心持有"),
            ],
        }
        expert_color = {"short":"#f0c040","mid":"#4ab3ff","long":"#00c87a"}
        ec = expert_color[scan_mode]
        expert_html = "".join([
            f'<div style="display:flex;justify-content:space-between;padding:3px 0;'
            f'border-bottom:1px solid #0e2030;font-size:0.71rem;">'
            f'<span style="color:{ec};font-weight:600;">{n}</span>'
            f'<span style="color:#4a6a80;">{m}</span></div>'
            for n, m in expert_map[scan_mode]
        ])
        st.markdown(
            f'<div style="background:#060f1c;border:1px solid #1a3050;border-radius:8px;'
            f'padding:10px 12px;margin:6px 0;">'
            f'<div style="font-size:0.65rem;color:#2a6a8a;letter-spacing:0.1em;margin-bottom:6px;">'
            f'參考專家</div>{expert_html}</div>',
            unsafe_allow_html=True
        )

        st.divider()
        st.markdown("**📡 掃描設定**")

        all_sectors = list(SECTOR_STOCKS.keys())
        sel_sectors = st.multiselect(
            "選擇掃描產業",
            options=all_sectors,
            default=all_sectors,
            help="可只勾選特定產業，減少掃描時間"
        )

        max_per = st.slider("每產業掃描檔數", 2, 10, 4, 1,
                            help="建議 4 檔，兼顧速度與廣度")

        total_stocks = sum(min(len(SECTOR_STOCKS[s]), max_per) for s in sel_sectors)
        api_est = total_stocks + 1
        api_c = "#00c87a" if (token or api_est <= 30) else ("#f0a500" if api_est <= 60 else "#ff7878")
        st.markdown(
            f'<div style="background:#060f1c;border:1px solid #1a3050;border-radius:7px;'
            f'padding:9px 11px;font-size:0.74rem;">'
            f'<span style="color:{api_c};">預計掃描 {total_stocks} 檔</span>'
            f'<span style="color:#3a5a70;"> / 約消耗 {api_est} 次 API</span></div>',
            unsafe_allow_html=True
        )

        st.divider()
        col1, col2 = st.columns(2)
        run_btn = col1.button("🔍 開始掃描", type="primary", use_container_width=True)
        clr_btn = col2.button("🗑️ 清快取", use_container_width=True)
        if clr_btn:
            st.cache_data.clear()
            st.session_state.pop("scan_df", None)
            st.session_state.pop("scan_mode_used", None)
            st.success("快取已清除")

        st.divider()
        st.caption("⚠️ 僅供研究，不構成投資建議")

    # ── Header ───────────────────────────────────────────────
    st.markdown("""
    <div class="dash-header">
      <div class="dash-title">📊 台股三線決策儀表板 v2.0</div>
      <div class="dash-sub">
        15 大產業 · 長線 / 中線 / 短線 · 自選股分析 · Weinstein × CANSLIM × Williams
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 大盤狀態 ─────────────────────────────────────────────
    with st.spinner("載入大盤…"):
        mkt = get_market_state(token)

    cls    = mkt["signal"]
    cl_s   = mkt["close"]
    m60_s  = mkt.get("ma60")
    m240_s = mkt.get("ma240")
    pos_s  = f"{mkt['pos_ratio']*100:.0f}%"
    cl_str   = f"{cl_s:,.1f}"  if cl_s   else "—"
    m60_str  = f"{m60_s:,.1f}" if m60_s  else "—"
    m240_str = f"{m240_s:,.1f}" if m240_s else "—"

    if cl_s is None:
        # 大盤無法取得：給清楚提示，不顯示 N/A
        st.markdown(
            '<div class="warn-bar">'
            '⚠️ <b>大盤資料暫時無法取得</b>（FinMind 免費 Token 不支援大盤指數 API）。'
            '建議：① 在左側填入 FinMind Token，或 ② 手動確認台股加權指數位置。'
            '&nbsp; 選股功能不受影響，可正常使用。'
            '</div>',
            unsafe_allow_html=True
        )
    else:
        bar_cls = "ok-bar" if cls == "bullish" else ("warn-bar" if cls == "bearish" else "ok-bar")
        proxy_note = "（以 0050 代理）" if m240_s and m240_s < 200 else ""
        st.markdown(
            f'<div class="{bar_cls}">'
            f'大盤 {mkt["date"]}{proxy_note}：<b>{cl_str}</b>'
            f'&nbsp;｜&nbsp; 60MA {m60_str}&nbsp; 240MA {m240_str}'
            f'&nbsp;｜&nbsp; 狀態：<b>{mkt["status"]}</b>'
            f'&nbsp;｜&nbsp; 建議最大倉位：<b>{pos_s}</b>'
            f'</div>',
            unsafe_allow_html=True
        )

    # ── Tabs ─────────────────────────────────────────────────
    tab_scan, tab_custom, tab_method = st.tabs([
        "📊 全市場掃描", "🔍 自選股分析", "📖 方法說明"
    ])

    # ════════════════════════════════════════
    # Tab 1：全市場掃描
    # ════════════════════════════════════════
    with tab_scan:
        if "scan_df" not in st.session_state:
            st.session_state["scan_df"] = None
            st.session_state["scan_mode_used"] = None

        if run_btn:
            if not sel_sectors:
                st.warning("請至少勾選一個產業")
            else:
                with st.spinner("掃描中，請稍候…"):
                    st.session_state["scan_df"]        = run_full_scan(
                        sel_sectors, token, max_per, scan_mode
                    )
                    st.session_state["scan_mode_used"] = scan_mode

        scan_df   = st.session_state.get("scan_df")
        mode_used = st.session_state.get("scan_mode_used") or scan_mode
        mode_lbl  = {"short":"⚡ 短線 7日","mid":"📊 中線 6-12月","long":"🔭 長線 1年+"}[mode_used]

        if scan_df is None:
            st.info("👈 左側選擇投資週期後，點「🔍 開始掃描」啟動篩選")
            return

        if scan_df.empty:
            st.markdown(
                '<div class="warn-bar">掃描結果為空。可能原因：<br>'
                '① GPS 門檻目前無符合股票（市場偏弱）<br>'
                '② API Token 未生效（請確認 token 已填入）<br>'
                '③ 請點「清快取」後重新掃描</div>',
                unsafe_allow_html=True
            )
            return

        # ── 篩選器（移除持有週期，改用評級）────────────────
        f1, f2, f3 = st.columns([2, 2, 2])
        with f1:
            grade_filter = st.multiselect(
                "GPS 評級篩選",
                options=["AAA","AA","B"],
                default=["AAA","AA","B"],
            )
        with f2:
            sector_filter = st.multiselect(
                "產業",
                options=sorted(scan_df["產業"].unique().tolist()),
                default=[],
            )
        with f3:
            buy_only  = st.checkbox("只看買進信號", value=True)

        view = scan_df.copy()
        if grade_filter:
            view = view[view["評級"].isin(grade_filter)]
        if sector_filter:
            view = view[view["產業"].isin(sector_filter)]
        if buy_only:
            view = view[view["信號"] == "✅ 買進"]

        # ── 今日最佳 Top 5 ──────────────────────────────────
        st.markdown(
            f'<div class="sec-title">今日最佳標的 Top 5 &nbsp;'
            f'<span style="font-size:0.75rem;color:#3a6a8a;">模式：{mode_lbl}</span></div>',
            unsafe_allow_html=True
        )

        top_cards = (view[view["信號"] == "✅ 買進"]
                     .sort_values("評分", ascending=False)
                     .head(5))

        if top_cards.empty:
            st.markdown(
                '<div class="warn-bar">目前無買進信號。市場可能偏弱，或 GPS 篩選門檻較嚴，'
                '可嘗試取消「只看買進信號」查看觀察清單。</div>',
                unsafe_allow_html=True
            )
        else:
            for chunk in [top_cards.iloc[:3], top_cards.iloc[3:]]:
                if chunk.empty: continue
                cols = st.columns(len(chunk))
                for i, (_, row) in enumerate(chunk.iterrows()):
                    cols[i].markdown(render_card(row), unsafe_allow_html=True)

        # ── 完整排行榜 ────────────────────────────────────────
        st.markdown(f'<div class="sec-title">完整排行榜（{len(view)} 筆）</div>',
                    unsafe_allow_html=True)

        disp_cols = ["代號","名稱","產業","模式","收盤價","漲跌%","信號",
                     "評分","評級","G分","P分","S分","F分","回測報酬%","勝率%","MDD%"]
        disp = view[[c for c in disp_cols if c in view.columns]].copy()

        def _cn(v): return "color:#00c87a" if isinstance(v,(int,float)) and v>0 else ("color:#ff5c5c" if isinstance(v,(int,float)) and v<0 else "")
        def _cs(v): return f"color:{score_color(v)};font-weight:bold" if isinstance(v,(int,float)) else ""

        styled = (disp.style
                  .map(_cn, subset=[c for c in ["漲跌%","回測報酬%"] if c in disp.columns])
                  .map(_cs, subset=[c for c in ["評分"] if c in disp.columns])
                  .map(lambda v: "color:#ff5c5c", subset=[c for c in ["MDD%"] if c in disp.columns])
                  .format({k:v for k,v in {
                      "收盤價":"{:.1f}","漲跌%":"{:+.2f}%","評分":"{:.0f}",
                      "回測報酬%":"{:+.1f}%","勝率%":"{:.1f}%","MDD%":"{:.1f}%",
                      "G分":"{:.0f}","P分":"{:.0f}","S分":"{:.0f}","F分":"{:.0f}",
                  }.items() if k in disp.columns})
                  .set_properties(**{"font-size":"0.83rem"}))

        st.dataframe(styled, use_container_width=True, height=440, hide_index=True)

        csv = disp.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("⬇️ 匯出 CSV", csv,
                           f"gps_{mode_used}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                           "text/csv")

        # ── K 線圖（修正 KeyError：不再使用持有週期欄位）───────
        st.markdown('<div class="sec-title">個股 K 線圖</div>', unsafe_allow_html=True)

        all_view = scan_df.copy()   # 用全部掃描結果，不受篩選器限制
        if all_view.empty:
            st.caption("掃描結果為空，無法顯示 K 線圖")
        else:
            ticker_opts = [
                f"{row['代號']}  {row['名稱']}  ({row['評級']} {row['評分']:.0f}分)"
                for _, row in all_view.iterrows()
            ]
            sel_opt  = st.selectbox("選擇股票查看 K 線圖", ticker_opts, index=0)
            sel_id   = sel_opt.strip().split()[0]
            sel_name = STOCK_NAMES.get(sel_id, sel_id)

            end_dt   = datetime.today().strftime("%Y-%m-%d")
            start_dt = (datetime.today() - timedelta(days=380)).strftime("%Y-%m-%d")
            with st.spinner(f"載入 {sel_id} {sel_name}…"):
                cdf = fetch_price(sel_id, start_dt, end_dt, token)
            if cdf.empty:
                st.warning(f"無法取得 {sel_id} 資料")
            else:
                tdf = fetch_taiex(start_dt, end_dt, token)
                cdf = compute_all_indicators(cdf, tdf)
                # 取得該股的 zones
                matched = all_view[all_view["代號"] == sel_id]
                zones   = matched.iloc[0]["_zones"] if not matched.empty else {}
                st.plotly_chart(
                    build_chart(cdf, sel_id, sel_name),
                    use_container_width=True,
                    config={"displayModeBar": True,
                            "toImageButtonOptions": {"filename": f"{sel_id}_chart", "scale": 2}}
                )

    # ════════════════════════════════════════
    # Tab 2：自選股分析
    # ════════════════════════════════════════
    with tab_custom:
        st.markdown('<div class="sec-title">輸入股票代號進行三線分析</div>',
                    unsafe_allow_html=True)

        col_in, col_btn = st.columns([3, 1])
        custom_id = col_in.text_input(
            "股票代號",
            placeholder="例如：2330（台積電）、0050（元大台灣50）",
            help="輸入 4 位數台股代號"
        ).strip()
        analyze_btn = col_btn.button("🔬 分析", type="primary", use_container_width=True)

        if "custom_result" not in st.session_state:
            st.session_state["custom_result"] = {}
            st.session_state["custom_id"] = ""

        if analyze_btn and custom_id:
            with st.spinner(f"分析 {custom_id} 中…"):
                res = analyze_custom_stock(custom_id, token)
            if not res:
                st.error(f"❌ 找不到 {custom_id} 的資料。請確認代號是否正確，或稍後再試。")
            else:
                st.session_state["custom_result"] = res
                st.session_state["custom_id"]     = custom_id

        res = st.session_state.get("custom_result", {})
        cid = st.session_state.get("custom_id", "")

        if res and cid:
            name = res.get("name", cid)
            st.markdown(f'<div class="sec-title">{cid} {name} · 三線分析報告</div>',
                        unsafe_allow_html=True)
            render_analysis_panel(res, cid)

            # K 線圖
            st.markdown('<div class="sec-title">K 線圖 + 指標</div>', unsafe_allow_html=True)
            df_chart = res.get("df", pd.DataFrame())
            if not df_chart.empty:
                st.plotly_chart(build_chart(df_chart, cid, name),
                                use_container_width=True,
                                config={"displayModeBar":True,
                                        "toImageButtonOptions":{"filename":f"{cid}_analysis","scale":2}})
        else:
            st.markdown("""
            <div style="background:#060f1c;border:1px dashed #1a3050;border-radius:10px;
                        padding:30px;text-align:center;color:#3a6a8a;margin:20px 0;">
              <div style="font-size:2rem;">🔍</div>
              <div style="font-size:1rem;margin-top:8px;">輸入任意台股代號，即可取得</div>
              <div style="font-size:0.85rem;margin-top:4px;color:#2a5a7a;">
                短線 · 中線 · 長線 三種週期的評分、買賣建議、K線圖
              </div>
            </div>""", unsafe_allow_html=True)

    # ════════════════════════════════════════
    # Tab 3：方法說明
    # ════════════════════════════════════════
    with tab_method:
        st.markdown("""
## 📖 分析方法論說明

---

### 🔭 長線策略（1 年以上）
**參考：Stan Weinstein《Secrets for Profiting in Bull and Bear Markets》**

Stan Weinstein 把股票分為四個 Stage（階段），只在 **Stage 2（主升段）** 買入。

| 條件 | 配分 | 說明 |
|------|:---:|------|
| 收盤 > 240MA 年線 | **+30** | 最核心條件，年線代表機構成本 |
| 240MA 斜率向上 | **+25** | 趨勢確立，年線本身在上漲 |
| 120MA > 240MA | **+20** | 半年線凌駕年線，多頭排列確認 |
| RS 相對強度優於大盤 | **+15** | 同漲跌市場下，此股更強 |
| 距 52 週高點 10% 以內 | **+10** | 強勢股特徵，弱勢股在 52 週低區 |
| 跌破 120MA（懲罰） | **-25** | 趨勢動搖，長線邏輯破壞 |

**買進門檻：60 分以上，且必要條件①②成立**

---

### 📊 中線策略（6-12 個月）
**參考：William O'Neil《How to Make Money in Stocks》CANSLIM**

CANSLIM 是選出市場龍頭股的方法，每個字母代表一個篩選條件。

| 條件 | 配分 | CANSLIM 對應 |
|------|:---:|-------------|
| 站上 60MA 季線 | **+25** | N（新高附近）|
| 季線斜率向上 | **+20** | 趨勢確立 |
| RS 相對強度正值 | **+20** | L（領導股）|
| 量能 > 均量 1.2× | **+20** | S（供需有利）|
| 站上 20MA 月線 | **+10** | 短期也站穩 |
| 跌破 60MA（懲罰） | **-30** | 趨勢破壞 |

**買進門檻：55 分以上，且季線多頭**

---

### ⚡ 短線策略（7 日內）
**參考：Larry Williams《Long-Term Secrets to Short-Term Trading》**

Larry Williams 強調「動能＋量能」的配合，避免追高和過熱區。

| 條件 | 配分 | 說明 |
|------|:---:|------|
| RSI 50-70（甜蜜區） | **+25** | 動能健康，非超買 |
| MACD 柱狀圖向上 | **+25** | 近期動能轉多 |
| 今日量 > 昨日 1.5× | **+25** | 爆量確認，主力介入 |
| 站上 5MA + 20MA | **+15** | 短線與月線均站穩 |
| 當日上漲（bonus） | **+5** | 方向確認 |
| RSI > 75（懲罰） | **-20** | 過熱，避免追高 |

**買進門檻：60 分以上，且非 RSI 過熱**

---

### 💹 操作建議價位計算
**參考：Van Tharp《Trade Your Way to Financial Freedom》**

> 核心原則：**風險報酬比（RR）必須從「進場價」計算，不從現價算**

| 項目 | 短線公式 | 中線公式 | 長線公式 |
|------|---------|---------|---------|
| 進場區 | MA20 ± 0.5% | MA60 ± 1.5% | MA120/240 ± 2% |
| 停損 | 進場 - 1.5×ATR | 進場 - 2.0×ATR | 進場 - 2.5×ATR |
| 目標一 | 進場 + 2.5×ATR | 進場 + 3.0×ATR | 進場 + 4.0×ATR |
| 目標二 | 近60日前高 ×98% | 52週高點 ×97% | Fibonacci 61.8%延伸 |

**ATR（Average True Range）**= 近 14 日平均真實波動幅度

---

### ⚖️ 風險報酬比判讀

| RR | 評級 | 建議 |
|:--:|:----:|------|
| ≥ 2.0 | ✅ 優秀 | 值得進場 |
| 1.0~2.0 | ⚠️ 尚可 | 謹慎小量 |
| < 1.0 | ❌ 偏低 | 等待更好位置 |

---

### 🛡️ 新手操作守則

1. **永遠先設好停損**，再決定買進數量
2. **每筆交易最多虧 2% 本金**（根據停損距離算出買幾張）
3. **大盤空頭時**（指數跌破 60MA），倉位降至 30%
4. **RR < 1 時不進場**，耐心等待
5. **分批建倉**：先買一半，確認股票方向對了再加碼

---

> 📌 **免責聲明**：本系統所有分析均基於歷史技術指標，不保證未來績效，不構成投資建議。投資有風險，請自行評估風險承受能力。
        """)


if __name__ == "__main__":
    main()
