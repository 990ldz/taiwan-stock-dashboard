#!/usr/bin/env python3
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
            for col in ["price","Price","close","Close"]:
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
# ⑥ 三大策略評分函式
# ════════════════════════════════════════════════════════════════

# ── 6-A 長線：Stan Weinstein Stage 2 ─────────────────────────
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

    final = float(max(0.0, min(100.0, raw)))
    signal = (final >= 60) and (rsi_ok or macd_bull) and (c5ma or c20ma) and (not overbought)

    return _build_result("短線", final, signal, breakdown, last, extra={"vol_ratio": vol_r})


# ── 共用輔助函式 ───────────────────────────────────────────────

def _empty_score(mode: str, reason: str) -> dict:
    return {"mode": mode, "signal": False, "score": 0.0,
            "reason": reason, "breakdown": [], "warning": "",
            "last": {}}

def _build_result(mode: str, score: float, signal: bool,
                  breakdown: list, last: pd.Series, extra: dict = None) -> dict:
    pos = [f"✅ {lbl}" for lbl, pts, met, detail in breakdown if met and pts > 0]
    neg = [f"🔴 {lbl}" for lbl, pts, met, detail in breakdown if met and pts < 0]
    parts = []
    if pos: parts.append(" ｜ ".join(pos))
    if neg: parts.append(" ｜ ".join(neg))
    reason = "  ".join(parts) if parts else "⬜ 未達任何條件"

    warning = ""
    for lbl, pts, met, detail in breakdown:
        if met and pts < 0:
            warning = f"⚠️ {lbl}（{detail}）" if detail else f"⚠️ {lbl}"
            break

    result = {"mode": mode, "signal": signal, "score": score,
              "reason": reason, "breakdown": breakdown,
              "warning": warning, "last": dict(last)}
    if extra:
        result.update(extra)
    return result


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
                start: str, end: str, max_per_sector: int = 5) -> list[dict]:
    stocks  = SECTOR_STOCKS.get(sector, [])[:max_per_sector]
    results = []

    for sid in stocks:
        df = fetch_price(sid, start, end, token)
        if df.empty or len(df) < 30:
            time.sleep(0.2); continue

        df = compute_all_indicators(df, taiex_df)

        for mode, score_fn, bt_mode in [
            ("short", score_shortterm, "short"),
            ("mid",   score_midterm,   "mid"),
            ("long",  score_longterm,  "long"),
        ]:
            sc = score_fn(df)
            if sc["score"] < 40:
                continue   # 太低的跳過，節省後面運算

            bt = quick_backtest(df, bt_mode)
            zones = compute_trade_zones(df, mode)
            last  = df.iloc[-1]
            prev  = df.iloc[-2] if len(df) >= 2 else last
            chg   = (float(last["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100

            results.append({
                "代號":      sid,
                "名稱":      STOCK_NAMES.get(sid, sid),
                "產業":      sector,
                "持有週期":  {"short":"短線 7日","mid":"中線 6-12月","long":"長線 1年+"}[mode],
                "收盤價":    round(float(last["Close"]), 1),
                "漲跌%":     round(chg, 2),
                "信號":      "✅ 買進" if sc["signal"] else "⬜ 觀察",
                "評分":      round(sc["score"], 1),
                "原因":      sc["reason"],
                "警告":      sc.get("warning", ""),
                "回測報酬%": bt["return"],
                "勝率%":     bt["win_rate"],
                "MDD%":      bt["mdd"],
                "_mode":     mode,
                "_zones":    zones,
                "_score_obj":sc,
            })

        time.sleep(0.25)

    return results


@st.cache_data(ttl=1800, show_spinner=False)
def run_full_scan(sectors: list, token: str, max_per_sector: int) -> pd.DataFrame:
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=380)).strftime("%Y-%m-%d")

    taiex_df = fetch_taiex(start, end, token)

    all_results = []
    prog = st.progress(0.0)
    stat = st.empty()

    for i, sector in enumerate(sectors):
        stat.markdown(
            f"<span style='color:#4a8aaa;font-size:0.8rem;'>📡 掃描 {sector} 產業…"
            f"（{i+1}/{len(sectors)}）</span>",
            unsafe_allow_html=True
        )
        prog.progress((i + 1) / len(sectors))
        rows = scan_sector(sector, token, taiex_df, start, end, max_per_sector)
        all_results.extend(rows)

    prog.empty(); stat.empty()

    if not all_results:
        return pd.DataFrame()

    df = pd.DataFrame(all_results)
    df = df.sort_values(["信號","評分"], ascending=[False, False]).reset_index(drop=True)
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
        fig.add_trace(go.Bar(x=df["date"], y=df["Volume"],
            marker_color=[c.replace(")", ",0.5)").replace("rgb","rgba") if c.startswith("rgb") else c + "80"
                           for c in vol_c],
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
        hist_c = [_UP if v > 0 else _DN for v in df["MACD_hist"].fillna(0)]
        fig.add_trace(go.Bar(x=df["date"], y=df["MACD_hist"],
            marker_color=[c + "90" for c in hist_c],
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
    mode = row.get("_mode", "mid")
    badge_map = {"short": ("badge-short","⚡ 短線 7日"),
                 "mid":   ("badge-mid",  "📊 中線 6-12M"),
                 "long":  ("badge-long", "🔭 長線 1年+")}
    badge_cls, badge_lbl = badge_map.get(mode, ("badge-mid","中線"))

    signal = row.get("信號","") == "✅ 買進"
    card_cls = "card-bull" if signal else "card-bear"
    sc   = float(row.get("評分", 0))
    sc_c = score_color(sc)
    bar  = int(sc)

    chg     = float(row.get("漲跌%", 0))
    chg_sym = "▲" if chg >= 0 else "▼"
    chg_cls = "#00c87a" if chg >= 0 else "#ff5c5c"

    ret     = float(row.get("回測報酬%", 0))
    ret_sym = "+" if ret >= 0 else ""
    ret_c   = "#00c87a" if ret >= 0 else "#ff5c5c"

    reason_html = str(row.get("原因","")).replace(" ｜ ","<br>&nbsp;·&nbsp;")

    warn = str(row.get("警告",""))
    warn_html = (
        f'<div style="background:#1a0808;border-left:3px solid #ff5c5c;'
        f'border-radius:5px;padding:6px 9px;margin:7px 0;'
        f'font-size:0.7rem;color:#ffaaaa;">{warn}</div>'
    ) if warn else ""

    zones = row.get("_zones", {}) or {}
    zones_html = render_zones(zones, signal)

    return f"""
    <div class="stock-card {card_cls}">
      <div style="position:absolute;top:14px;right:16px;">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:1.4rem;
                     font-weight:700;color:{sc_c};">{sc:.0f}</span>
        <span style="color:#2a4a60;font-size:0.65rem;">/100</span>
      </div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:0.75rem;color:#3a7a9a;">
        {row.get('代號','')} &nbsp;·&nbsp; {row.get('產業','')}
      </div>
      <div style="font-size:1.1rem;font-weight:700;color:#e8f4f8;margin:2px 0 6px;">
        {row.get('名稱','')}
      </div>
      <span class="card-badge {badge_cls}">{badge_lbl}</span>
      <div style="background:#112030;border-radius:3px;height:4px;margin:5px 0 10px;">
        <div style="width:{bar}%;height:100%;border-radius:3px;background:{sc_c};"></div>
      </div>
      <span style="font-family:'IBM Plex Mono',monospace;font-size:1.5rem;
                   font-weight:600;color:#e8f4f8;">
        {float(row.get('收盤價',0)):,.1f}
      </span>
      <span style="color:{chg_cls};font-size:0.9rem;">&nbsp;{chg_sym} {abs(chg):.2f}%</span>
      {warn_html}
      <div style="margin-top:7px;font-size:0.72rem;color:#7aacb8;line-height:1.7;">
        {reason_html}
      </div>
      {zones_html}
      <hr style="border:none;border-top:1px solid #0e2030;margin:9px 0 7px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:0.79rem;color:#8aabb8;">
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
            st.success("快取已清除")

        st.divider()
        st.markdown(
            '<div style="font-size:0.72rem;color:#3a5a70;line-height:1.6;">'
            '<span class="method-tag">Weinstein</span> 長線趨勢<br>'
            '<span class="method-tag">CANSLIM</span> 中線動能<br>'
            '<span class="method-tag">Williams</span> 短線爆發<br>'
            '<span class="method-tag">ATR×Fib</span> 價位計算<br>'
            '</div>', unsafe_allow_html=True
        )
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

    cls   = mkt["signal"]
    cl_s  = mkt["close"]
    m60_s = mkt.get("ma60")
    m240_s= mkt.get("ma240")
    pos_s = f"{mkt['pos_ratio']*100:.0f}%"
    bar_cls = "ok-bar" if cls == "bullish" else ("warn-bar" if cls == "bearish" else "ok-bar")
    cl_str  = f"{cl_s:,.2f}" if cl_s else "N/A"
    m60_str = f"{m60_s:,.1f}"  if m60_s else "N/A"
    m240_str= f"{m240_s:,.1f}" if m240_s else "N/A"

    st.markdown(
        f'<div class="{bar_cls}">'
        f'加權指數 {mkt["date"]}：<b>{cl_str}</b>'
        f'&nbsp;｜&nbsp; 60MA {m60_str} &nbsp; 240MA {m240_str}'
        f'&nbsp;｜&nbsp; 大盤狀態：<b>{mkt["status"]}</b>'
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

        if run_btn:
            if not sel_sectors:
                st.warning("請至少勾選一個產業")
            else:
                with st.spinner("掃描中，請稍候…"):
                    st.session_state["scan_df"] = run_full_scan(
                        sel_sectors, token, max_per
                    )

        scan_df = st.session_state.get("scan_df")

        if scan_df is None:
            st.info("👈 點左側「🔍 開始掃描」啟動全市場篩選")
            return

        if scan_df.empty:
            st.error("掃描結果為空，請確認 API Token 或網路連線")
            return

        # 篩選器
        f1, f2, f3, f4 = st.columns([2, 2, 1.5, 1.5])
        with f1:
            period_filter = st.multiselect("持有週期",
                ["短線 7日","中線 6-12月","長線 1年+"],
                default=["短線 7日","中線 6-12月","長線 1年+"])
        with f2:
            sector_filter = st.multiselect("產業",
                options=sorted(scan_df["產業"].unique().tolist()),
                default=[])
        with f3:
            buy_only = st.checkbox("只看買進信號", value=True)
        with f4:
            min_score = st.slider("最低評分", 0, 100, 50, 5)

        view = scan_df.copy()
        if period_filter:
            view = view[view["持有週期"].isin(period_filter)]
        if sector_filter:
            view = view[view["產業"].isin(sector_filter)]
        if buy_only:
            view = view[view["信號"] == "✅ 買進"]
        view = view[view["評分"] >= min_score]

        # 今日精選置頂（三個週期各取 top 1）
        st.markdown('<div class="sec-title">今日最佳標的</div>', unsafe_allow_html=True)

        top_cards = []
        for period in ["短線 7日","中線 6-12月","長線 1年+"]:
            sub = view[view["持有週期"] == period]
            sub = sub[sub["信號"] == "✅ 買進"]
            if not sub.empty:
                top_cards.append(sub.iloc[0])

        if not top_cards:
            st.markdown('<div class="warn-bar">目前無任何買進信號，市場偏弱，建議持盈保泰。</div>',
                        unsafe_allow_html=True)
        else:
            tcols = st.columns(min(3, len(top_cards)))
            for i, row in enumerate(top_cards):
                tcols[i].markdown(render_card(row), unsafe_allow_html=True)

        # 完整排行榜
        st.markdown(f'<div class="sec-title">完整排行榜（{len(view)} 筆）</div>',
                    unsafe_allow_html=True)

        disp_cols = ["代號","名稱","產業","持有週期","收盤價","漲跌%","信號",
                     "評分","回測報酬%","勝率%","MDD%"]
        disp = view[[c for c in disp_cols if c in view.columns]].copy()

        def _cn(v): return "color:#00c87a" if isinstance(v,(int,float)) and v>0 else ("color:#ff5c5c" if isinstance(v,(int,float)) and v<0 else "")
        def _cs(v): return f"color:{score_color(v)};font-weight:bold" if isinstance(v,(int,float)) else ""

        styled = (disp.style
                  .map(_cn, subset=["漲跌%","回測報酬%"])
                  .map(_cs, subset=["評分"])
                  .map(lambda v: "color:#ff5c5c", subset=["MDD%"])
                  .format({"收盤價":"{:.1f}","漲跌%":"{:+.2f}%","評分":"{:.0f}",
                           "回測報酬%":"{:+.1f}%","勝率%":"{:.1f}%","MDD%":"{:.1f}%"})
                  .set_properties(**{"font-size":"0.83rem"}))

        st.dataframe(styled, use_container_width=True, height=440, hide_index=True)

        csv = disp.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("⬇️ 匯出 CSV", csv,
                           f"scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                           "text/csv")

        # K 線圖
        st.markdown('<div class="sec-title">個股 K 線圖</div>', unsafe_allow_html=True)
        ticker_opts = [f"{r['代號']} {r['名稱']} ({r['持有週期']})" for _, r in view.iterrows()]

        if ticker_opts:
            sel_opt = st.selectbox("選擇股票", ticker_opts, index=0)
            sel_id  = sel_opt.split()[0]
            sel_name= STOCK_NAMES.get(sel_id, sel_id)
            end_dt  = datetime.today().strftime("%Y-%m-%d")
            start_dt= (datetime.today() - timedelta(days=380)).strftime("%Y-%m-%d")
            with st.spinner(f"載入 {sel_id}…"):
                cdf = fetch_price(sel_id, start_dt, end_dt, token)
            if not cdf.empty:
                tdf = fetch_taiex(start_dt, end_dt, token)
                cdf = compute_all_indicators(cdf, tdf)
                st.plotly_chart(build_chart(cdf, sel_id, sel_name),
                                use_container_width=True,
                                config={"displayModeBar":True,
                                        "toImageButtonOptions":{"filename":f"{sel_id}_chart","scale":2}})

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
