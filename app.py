"""
台股法人追蹤 × 盤前 VWAP 決策系統 v3.0
══════════════════════════════════════════════════════
核心理念：跟著大錢走，而不是跟著指標走

選股邏輯（由重到輕）：
  1. 外資持續買超  → 30分  （最重要，外資控制台股 40% 籌碼）
  2. 投信持續買超  → 20分  （長線護盤，主力建倉訊號）
  3. 三大法人共識  → 15分  （三方同向，最強訊號）
  4. 技術面確認    → 20分  （MA均線、量能）
  5. 新聞情緒正面  → 15分  （Claude API 語意分析）

盤前 VWAP 模組（Ross Cameron + Larry Williams）：
  - 昨日 VWAP 計算（成交量加權均價）
  - 開盤區間識別（前 30 分鐘高低點）
  - 今日關鍵價位標注
  - 盤前監控清單

股票宇宙：
  - 0050 + 0051 成分股（市值大、流動性高）
  - 主動型 ETF 重倉股
  - 外資長期持有名單
  共約 120 檔高品質標的
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
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
    page_title="台股法人追蹤系統 v3",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ════════════════════════════════════════════════════════════════
# ② 常數與股票宇宙
# ════════════════════════════════════════════════════════════════
FINMIND_API      = "https://api.finmindtrade.com/api/v4/data"
TRANSACTION_COST = 0.006
SLIPPAGE         = 0.001

# ── 股票宇宙（高品質選股池）─────────────────────────────────
# 0050 成分股（前 50 大市值）
ETF_0050 = [
    "2330","2317","2454","2308","2382","2412","2303","3711",
    "2357","2002","1301","2881","2882","2886","2891","2892",
    "5880","2884","2885","2887","2888","2883","2379","3034",
    "6415","3529","2344","2408","1303","1326","6505","2609",
    "2603","2615","2610","4904","3045","1216","2912","5871",
    "2207","4938","2395","2474","2376","2353","1102","1101",
    "2618","2634",
]
# 0051 中型股
ETF_0051 = [
    "2360","3008","2301","2327","3037","4544","1789","6547",
    "2369","2371","1590","2231","2201","2204","1402","9910",
    "1504","2727","2723","5903","2511","5522","1217","1264",
    "2820","5871","6202","2823","2838","4170",
]
# 外資長期重倉 + 主動 ETF 重倉
INST_FAVORITES = [
    "2330","2454","2317","3711","6415","2308","2382","2303",
    "2379","3034","3529","2344","2412","4904","3045","2881",
    "2882","2886","5871","2207","2912","5903","2603","2609",
]

def get_universe() -> list[str]:
    seen = set(); result = []
    for sid in ETF_0050 + ETF_0051 + INST_FAVORITES:
        if sid not in seen:
            seen.add(sid); result.append(sid)
    return result

STOCK_NAMES: dict[str, str] = {
    "2330":"台積電","2317":"鴻海","2454":"聯發科","2308":"台達電",
    "2382":"廣達","2412":"中華電","2303":"聯電","3711":"日月光",
    "2357":"華碩","2002":"中鋼","1301":"台塑","2881":"富邦金",
    "2882":"國泰金","2886":"兆豐金","2891":"中信金","2892":"第一金",
    "5880":"合庫金","2884":"玉山金","2885":"元大金","2887":"台新金",
    "2888":"新光金","2883":"開發金","2379":"瑞昱","3034":"聯詠",
    "6415":"矽力KY","3529":"力旺","2344":"華邦電","2408":"南亞科",
    "1303":"南亞","1326":"台化","6505":"台塑化","2609":"陽明",
    "2603":"長榮","2615":"萬海","2610":"華航","4904":"遠傳",
    "3045":"台灣大","1216":"統一","2912":"統一超","5871":"中租KY",
    "2207":"和泰車","4938":"和碩","2395":"研華","2474":"可成",
    "2376":"技嘉","2353":"宏碁","1102":"亞泥","1101":"台泥",
    "2618":"長榮航","2634":"漢翔","2360":"致茂","3008":"大立光",
    "2301":"光寶科","2327":"國巨","3037":"欣興","4544":"帆宣",
    "1789":"神隆","6547":"高端疫苗","2369":"菱生","2371":"大同",
    "1590":"亞德客KY","2231":"為升","2201":"裕隆","2204":"中華汽車",
    "1402":"遠東新","9910":"豐泰","1504":"東元","2727":"王品",
    "2723":"美食KY","5903":"全家","2511":"太子","5522":"遠雄",
    "1217":"愛之味","1264":"德麥","2820":"華票","5871":"中租KY",
    "6202":"盛弘","2823":"中壽","2838":"聯邦銀","4170":"永昕",
}

SECTOR_MAP: dict[str, str] = {
    "2330":"半導體","2454":"半導體","2303":"半導體","3711":"半導體",
    "6415":"半導體","3034":"半導體","2379":"半導體","3529":"半導體",
    "2344":"半導體","2408":"半導體","2317":"電子製造","2382":"電子製造",
    "2357":"電子製造","2308":"電子製造","4938":"電子製造","2395":"電子製造",
    "2360":"電子製造","3008":"電子製造","2474":"電子製造","2376":"電子製造",
    "2881":"金融","2882":"金融","2884":"金融","2885":"金融",
    "2886":"金融","2887":"金融","2891":"金融","2892":"金融",
    "5880":"金融","2883":"金融","2823":"金融","2838":"金融",
    "1301":"石化","1303":"石化","1326":"石化","6505":"石化",
    "2002":"鋼鐵","2609":"航運","2603":"航運","2615":"航運",
    "2610":"航運","2618":"航運","2634":"航運","1789":"生技",
    "6547":"生技","6202":"生技","4170":"生技","1216":"食品",
    "1217":"食品","2912":"零售","2727":"餐飲","2723":"餐飲",
    "5903":"零售","2412":"電信","3045":"電信","4904":"電信",
    "2207":"汽車","2231":"汽車","1101":"水泥","1102":"水泥",
    "1402":"紡織","9910":"製造","2353":"電腦","5871":"租賃",
}

# ════════════════════════════════════════════════════════════════
# ③ CSS
# ════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Noto+Sans+TC:wght@400;600;700&display=swap');
html,body,[class*="css"]{ font-family:'Noto Sans TC',sans-serif; }

.header {
    background:linear-gradient(135deg,#040a14 0%,#081625 60%,#091e35 100%);
    border:1px solid #1a3a5f; border-radius:14px; padding:22px 30px; margin-bottom:18px;
}
.h-title { font-family:'IBM Plex Mono',monospace; font-size:1.6rem;
           font-weight:600; color:#e8f4f8; letter-spacing:0.04em; }
.h-sub   { color:#3a7a9a; font-size:0.72rem; margin-top:4px;
           letter-spacing:0.1em; text-transform:uppercase; }

/* ── 法人追蹤卡片 ── */
.inst-card {
    background:linear-gradient(150deg,#060f1c,#091828);
    border:1.5px solid #1a3050; border-radius:12px;
    padding:16px 18px; height:100%; position:relative;
}
.ic-buy  { border-color:#00c87a; box-shadow:0 0 14px rgba(0,200,122,0.10); }
.ic-sell { border-color:#ff5c5c44; }
.ic-neut { border-color:#1a2a3a; }

/* ── 分數環 ── */
.score-ring {
    width:60px; height:60px; border-radius:50%; display:flex;
    align-items:center; justify-content:center;
    font-family:'IBM Plex Mono',monospace; font-weight:700; font-size:1.15rem;
}

/* ── 法人流向條 ── */
.flow-bar { display:flex; align-items:center; gap:8px;
            font-size:0.75rem; padding:4px 0; }
.fb-label { color:#4a7a9a; width:40px; flex-shrink:0; }
.fb-bar   { flex:1; height:6px; background:#0e2030; border-radius:3px;
            overflow:hidden; }
.fb-fill  { height:100%; border-radius:3px; }
.fb-val   { font-family:'IBM Plex Mono',monospace; font-size:0.72rem;
            width:70px; text-align:right; }

/* ── VWAP 監控卡片 ── */
.vwap-card {
    background:#060f1c; border:1px solid #1a3050;
    border-radius:10px; padding:14px 16px; margin:6px 0;
}
.vc-signal { font-size:0.7rem; letter-spacing:0.08em; text-transform:uppercase; }
.vc-stock  { font-size:1.05rem; font-weight:700; color:#e8f4f8; }
.vc-grid   { display:grid; grid-template-columns:repeat(3,1fr); gap:8px;
             margin-top:10px; }
.vg-item   { background:#0a1a2a; border-radius:6px; padding:8px 10px; }
.vg-label  { font-size:0.64rem; color:#3a6a8a; margin-bottom:3px; }
.vg-value  { font-family:'IBM Plex Mono',monospace; font-size:0.9rem; }

/* ── 區塊標題 ── */
.sec-title { font-family:'IBM Plex Mono',monospace; font-size:0.78rem;
             color:#2a6a8a; letter-spacing:0.12em; text-transform:uppercase;
             border-bottom:1px solid #0e2030; padding-bottom:6px; margin:22px 0 12px; }

/* ── 警示橫幅 ── */
.warn-bar { background:#180808; border-left:3px solid #ff5c5c;
            border-radius:6px; padding:10px 14px; margin:8px 0;
            color:#ffaaaa; font-size:0.82rem; }
.ok-bar   { background:#040e08; border-left:3px solid #00c87a;
            border-radius:6px; padding:10px 14px; margin:8px 0;
            color:#80e8b0; font-size:0.82rem; }
.info-bar { background:#060e18; border-left:3px solid #4ab3ff;
            border-radius:6px; padding:10px 14px; margin:8px 0;
            color:#90c8f8; font-size:0.82rem; }

/* ── 進場建議盒 ── */
.entry-box { background:#030c16; border:1px solid #1a3050;
             border-radius:10px; padding:12px 14px; margin-top:10px; }
.entry-grid { display:grid; grid-template-columns:1fr 1fr; gap:6px 14px; }
.eg-label { font-size:0.68rem; color:#3a6a8a; margin-bottom:2px; }
.eg-val   { font-family:'IBM Plex Mono',monospace; font-size:0.95rem; font-weight:600; }

#MainMenu,footer{visibility:hidden;}
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# ④ FinMind API 層
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_price(sid: str, start: str, end: str, token: str = "") -> pd.DataFrame:
    params = {"dataset":"TaiwanStockPrice","data_id":sid,
              "start_date":start,"end_date":end}
    if token: params["token"] = token
    try:
        r = requests.get(FINMIND_API, params=params, timeout=20)
        d = r.json()
        if d.get("status") != 200 or not d.get("data"): return pd.DataFrame()
        df = pd.DataFrame(d["data"])
        df = df.rename(columns={"close":"Close","open":"Open","max":"High",
                                 "min":"Low","Trading_Volume":"Volume"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for c in ["Close","Open","High","Low","Volume"]:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["Close"])
    except Exception: return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_minute(sid: str, date_str: str, token: str = "") -> pd.DataFrame:
    """取得分鐘 K 線（用於 VWAP 計算）"""
    params = {"dataset":"TaiwanStockPriceMinute","data_id":sid,
              "start_date":date_str,"end_date":date_str}
    if token: params["token"] = token
    try:
        r = requests.get(FINMIND_API, params=params, timeout=20)
        d = r.json()
        if d.get("status") != 200 or not d.get("data"): return pd.DataFrame()
        df = pd.DataFrame(d["data"])
        df = df.rename(columns={"close":"Close","open":"Open","max":"High",
                                 "min":"Low","volume":"Volume"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for c in ["Close","Open","High","Low","Volume"]:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["Close"])
    except Exception: return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_institutional(sid: str, token: str = "") -> pd.DataFrame:
    """三大法人買賣超"""
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    params = {"dataset":"TaiwanStockInstitutionalInvestors",
              "data_id":sid,"start_date":start,"end_date":end}
    if token: params["token"] = token
    try:
        r = requests.get(FINMIND_API, params=params, timeout=15)
        d = r.json()
        if d.get("status") != 200 or not d.get("data"): return pd.DataFrame()
        df = pd.DataFrame(d["data"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        if "name" in df.columns and "buy" in df.columns:
            df["net"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0) - \
                        pd.to_numeric(df["sell"], errors="coerce").fillna(0)
            pivot = df.pivot_table(index="date", columns="name",
                                   values="net", aggfunc="sum").reset_index()
            rename = {}
            for col in pivot.columns:
                cs = str(col)
                if "外資" in cs or "Foreign" in cs: rename[col] = "外資"
                elif "投信" in cs or "Investment_Trust" in cs: rename[col] = "投信"
                elif "自營" in cs or "Dealer" in cs: rename[col] = "自營"
            pivot = pivot.rename(columns=rename)
            for col in ["外資","投信","自營"]:
                if col not in pivot.columns: pivot[col] = 0.0
            return pivot
        return pd.DataFrame()
    except Exception: return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_margin(sid: str, token: str = "") -> pd.DataFrame:
    """融資融券"""
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    params = {"dataset":"TaiwanStockMarginPurchaseShortSale",
              "data_id":sid,"start_date":start,"end_date":end}
    if token: params["token"] = token
    try:
        r = requests.get(FINMIND_API, params=params, timeout=15)
        d = r.json()
        if d.get("status") != 200 or not d.get("data"): return pd.DataFrame()
        df = pd.DataFrame(d["data"])
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception: return pd.DataFrame()


@st.cache_data(ttl=7200, show_spinner=False)
def fetch_taiex(start: str, end: str, token: str = "") -> pd.DataFrame:
    # 方法一：標準大盤指數 API
    for did in ["TAIEX", "Y9999", ""]:
        params = {"dataset":"TaiwanStockMarketIndex","start_date":start,"end_date":end}
        if did: params["data_id"] = did
        if token: params["token"] = token
        try:
            r = requests.get(FINMIND_API, params=params, timeout=20)
            d = r.json()
            if d.get("status") != 200 or not d.get("data"): continue
            df = pd.DataFrame(d["data"])
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            for col in ["price","Price","close","Close"]:
                if col in df.columns:
                    df["Close"] = pd.to_numeric(df[col], errors="coerce"); break
            df = df.dropna(subset=["Close"])
            if len(df) < 10: continue
            df["Volume"] = df["Open"] = df["High"] = df["Low"] = df["Close"]
            return df
        except Exception: continue

    # 方法二：用 0050 當大盤代理（免費 Token 也能取）
    try:
        params = {"dataset":"TaiwanStockPrice","data_id":"0050",
                  "start_date":start,"end_date":end}
        if token: params["token"] = token
        r = requests.get(FINMIND_API, params=params, timeout=20)
        d = r.json()
        if d.get("status") == 200 and d.get("data"):
            df = pd.DataFrame(d["data"])
            df = df.rename(columns={"close":"Close","open":"Open",
                                     "max":"High","min":"Low","Trading_Volume":"Volume"})
            df["date"]  = pd.to_datetime(df["date"])
            df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
            df = df.sort_values("date").dropna(subset=["Close"]).reset_index(drop=True)
            if len(df) >= 10:
                df.attrs["is_proxy"] = True   # 標記為代理
                return df
    except Exception: pass

    return pd.DataFrame()


@st.cache_data(ttl=7200, show_spinner=False)
def fetch_news_sentiment(sid: str, name: str, token: str = "") -> dict:
    """
    新聞情緒分析。
    先嘗試 FinMind 新聞，用關鍵字快速分類（不依賴外部 API Key）。
    若標題數量足夠，再嘗試 Claude API（需部署環境有 API Key）。
    """
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=14)).strftime("%Y-%m-%d")
    headlines = []
    try:
        params = {"dataset":"TaiwanStockNews","data_id":sid,
                  "start_date":start,"end_date":end}
        if token: params["token"] = token
        r = requests.get(FINMIND_API, params=params, timeout=10)
        d = r.json()
        if d.get("status") == 200 and d.get("data"):
            df_news = pd.DataFrame(d["data"])
            if "title" in df_news.columns:
                headlines = df_news["title"].dropna().tolist()[-10:]
    except Exception:
        pass

    if not headlines:
        return {"score": 0.0, "label": "無新聞", "color": "#5a8fa8",
                "summary": "", "headlines": [], "count": 0}

    # ── 關鍵字快速分類（不需要 API Key）──────────────────────
    pos_kw = ["創高","突破","法說","營收成長","獲利","配息","EPS",
               "買超","增持","升評","目標價調升","訂單","新客戶",
               "看好","強勁","超預期","利多","入選","漲停"]
    neg_kw = ["衰退","下修","虧損","賣超","降評","裁員","罰款",
               "調降","利空","減資","停損","風險","警示","跌停",
               "庫存","下滑","衝擊"]

    pos_count = sum(1 for h in headlines for k in pos_kw if k in h)
    neg_count = sum(1 for h in headlines for k in neg_kw if k in h)
    total = len(headlines)

    if pos_count > neg_count * 1.5:
        score = min(0.3 + pos_count / total * 0.5, 0.8)
        label = "偏多" if score < 0.7 else "強多"
        color = "#00c87a"
    elif neg_count > pos_count * 1.5:
        score = max(-0.3 - neg_count / total * 0.5, -0.8)
        label = "偏空" if score > -0.7 else "強空"
        color = "#ff5c5c"
    else:
        score = 0.0
        label = "中性"
        color = "#f0c040"

    # 嘗試 Claude API（若部署環境有 Key 則加強分析）
    try:
        news_text = "\n".join([f"- {h}" for h in headlines[:6]])
        prompt = (f"台股{sid}{name}新聞：\n{news_text}\n\n"
                  f"只回傳JSON，不加說明：{{\"score\":0.6,\"label\":\"偏多\",\"summary\":\"20字摘要\"}}\n"
                  f"score範圍 -1到1，正=利多，負=利空")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":150,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=8
        )
        if resp.status_code == 200:
            text = resp.json()["content"][0]["text"]
            text = text.replace("```json","").replace("```","").strip()
            p    = json.loads(text)
            sc2  = float(p.get("score", score))
            lbl2 = p.get("label", label)
            clr2 = "#00c87a" if sc2 > 0.3 else "#f0c040" if sc2 > -0.3 else "#ff5c5c"
            return {"score": sc2, "label": lbl2, "color": clr2,
                    "summary": p.get("summary",""), "headlines": headlines,
                    "count": len(headlines)}
    except Exception:
        pass  # Claude API 不可用時沿用關鍵字結果

    return {"score": score, "label": label, "color": color,
            "summary": f"共 {len(headlines)} 則新聞，正面{pos_count}則，負面{neg_count}則",
            "headlines": headlines, "count": len(headlines)}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_monthly_revenue(sid: str, token: str = "") -> pd.DataFrame:
    """月營收 YoY 資料"""
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=450)).strftime("%Y-%m-%d")
    params = {"dataset":"TaiwanStockMonthRevenue","data_id":sid,
              "start_date":start,"end_date":end}
    if token: params["token"] = token
    try:
        r = requests.get(FINMIND_API, params=params, timeout=15)
        d = r.json()
        if d.get("status") != 200 or not d.get("data"): return pd.DataFrame()
        df = pd.DataFrame(d["data"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for col in ["revenue","Revenue","revenue_month"]:
            if col in df.columns:
                df["revenue"] = pd.to_numeric(df[col], errors="coerce"); break
        return df.dropna(subset=["revenue"])
    except Exception: return pd.DataFrame()


# ── 長線/存股 特殊評分：基本面 + 殖利率 ───────────────────────────

# 已知高殖利率/護城河股票（2024 年統計）
DIVIDEND_STOCKS = {
    "2881": {"div_yield": 5.5, "type": "金融"},
    "2882": {"div_yield": 5.2, "type": "金融"},
    "2886": {"div_yield": 5.0, "type": "金融"},
    "2891": {"div_yield": 4.8, "type": "金融"},
    "2892": {"div_yield": 5.1, "type": "金融"},
    "5880": {"div_yield": 5.3, "type": "金融"},
    "2884": {"div_yield": 4.6, "type": "金融"},
    "2885": {"div_yield": 4.2, "type": "金融"},
    "2887": {"div_yield": 4.5, "type": "金融"},
    "2412": {"div_yield": 5.5, "type": "電信"},
    "3045": {"div_yield": 4.8, "type": "電信"},
    "4904": {"div_yield": 4.5, "type": "電信"},
    "2912": {"div_yield": 4.2, "type": "零售"},
    "5903": {"div_yield": 3.8, "type": "零售"},
    "1101": {"div_yield": 4.0, "type": "水泥"},
    "1102": {"div_yield": 3.8, "type": "水泥"},
    "2330": {"div_yield": 2.5, "type": "半導體"},
    "6505": {"div_yield": 6.0, "type": "石化"},
}

def score_value(inst_df, price_df, rev_df, news, sid) -> dict:
    """
    長線/存股模式評分（100分制）
    F 基本面品質    45分
    G 法人長期持有  30分
    T 技術趨勢     25分
    """
    bd = []; raw = 0.0

    # ── F 基本面（45分）────────────────────────────────────
    # F1：月營收 YoY > 15% (+20)
    yoy = 0.0
    if rev_df is not None and len(rev_df) >= 14:
        try:
            latest   = float(rev_df.iloc[-1]["revenue"])
            year_ago = float(rev_df.iloc[-13]["revenue"])
            yoy = (latest - year_ago) / year_ago * 100 if year_ago > 0 else 0
        except Exception: pass
    if yoy > 20:    f1, f1l = 20, f"月營收 YoY {yoy:+.1f}%（高速成長）"
    elif yoy > 15:  f1, f1l = 15, f"月營收 YoY {yoy:+.1f}%（穩健成長）"
    elif yoy > 0:   f1, f1l = 8,  f"月營收 YoY {yoy:+.1f}%（微幅成長）"
    elif yoy > -10: f1, f1l = 0,  f"月營收 YoY {yoy:+.1f}%（持平）"
    else:           f1, f1l = -10,f"月營收 YoY {yoy:+.1f}%（衰退）"
    raw += f1
    bd.append({"stage":"F","label":f1l,"pts":f1,"met":f1>0,
               "detail":"近12月同比成長"})

    # F2：殖利率 / 護城河 (+25)
    div_info = DIVIDEND_STOCKS.get(sid, {})
    dy = div_info.get("div_yield", 0)
    if dy >= 5.0:   f2, f2l = 25, f"高殖利率 {dy:.1f}%（存股首選）"
    elif dy >= 4.0: f2, f2l = 18, f"殖利率 {dy:.1f}%（穩定配息）"
    elif dy >= 3.0: f2, f2l = 10, f"殖利率 {dy:.1f}%（尚可）"
    elif sid in {"2330","2454","6415","3529"}:
        f2, f2l = 15, "半導體龍頭（成長護城河）"
    else: f2, f2l = 0, "護城河資料不足"
    raw += f2
    bd.append({"stage":"F","label":f2l,"pts":f2,"met":f2>0,"detail":""})

    # ── G 法人長期（30分）────────────────────────────────
    f_30d = 0.0; t_30d = 0.0
    if not inst_df.empty and len(inst_df) >= 5:
        if "外資" in inst_df.columns:
            f_30d = float(inst_df["外資"].fillna(0).sum())
        if "投信" in inst_df.columns:
            t_30d = float(inst_df["投信"].fillna(0).sum())

        if f_30d > 5e8:   g1, g1l = 20, f"外資月累計大量買超 {f_30d/1e8:.1f}億"
        elif f_30d > 1e8: g1, g1l = 12, f"外資月累計買超 {f_30d/1e8:.1f}億"
        elif f_30d > 0:   g1, g1l = 5,  f"外資月累計小量買進"
        else:             g1, g1l = -5, f"外資月累計賣超 {abs(f_30d)/1e8:.1f}億"
        raw += g1
        bd.append({"stage":"G","label":g1l,"pts":g1,"met":g1>0,"detail":""})

        if t_30d > 5e7:   g2, g2l = 10, f"投信月累計積極買超 {t_30d/1e6:.0f}萬"
        elif t_30d > 0:   g2, g2l = 5,  f"投信月累計輕量買進"
        else:             g2, g2l = 0,  "投信月累計賣出"
        raw += g2
        bd.append({"stage":"G","label":g2l,"pts":g2,"met":g2>0,"detail":""})

    # ── T 技術趨勢（25分）───────────────────────────────
    if not price_df.empty and len(price_df) >= 20:
        df2 = compute_indicators(price_df)
        last = df2.iloc[-1]
        def _v2(c): v=last.get(c); return float(v) if v is not None and not pd.isna(v) else np.nan
        ma20=_v2("MA20"); ma60=_v2("MA60"); rsi=_v2("RSI"); close=float(last["Close"])

        t1 = not np.isnan(ma60) and close > ma60
        raw += 15 if t1 else 0
        bd.append({"stage":"T","label":"站上季線MA60（長線趨勢向上）",
                   "pts":15,"met":t1,"detail":f"MA60={ma60:.1f}" if not np.isnan(ma60) else "N/A"})

        t2 = not np.isnan(ma20) and close > ma20
        raw += 10 if t2 else 0
        bd.append({"stage":"T","label":"站上月線MA20（中線多頭）",
                   "pts":10,"met":t2,"detail":f"MA20={ma20:.1f}" if not np.isnan(ma20) else "N/A"})

    # 新聞加分
    if news and news.get("count", 0) > 0:
        np_s = round(float(news.get("score",0)) * 10)
        raw += np_s
        bd.append({"stage":"N","label":f"新聞情緒 {news.get('label','')} ({np_s:+d}分)",
                   "pts":np_s,"met":np_s>0,"detail":news.get("summary","")})

    final = float(max(0, min(100, raw)))
    if final >= 75:   grade,lbl,act,gc="AAA","優質存股","長線核心持倉，定期定額","#00c87a"
    elif final >= 60: grade,lbl,act,gc="AA","成長+配息","建議分批買進","#80d840"
    elif final >= 45: grade,lbl,act,gc="A","觀察追蹤","等回測月線再進場","#f0c040"
    else:             grade,lbl,act,gc="B","暫緩觀望","基本面或法人不理想","#f0a500"

    pos=[b["label"] for b in bd if b["met"] and b["pts"]>0]
    neg=[b["label"] for b in bd if b["met"] and b["pts"]<0]
    parts=[]
    if pos: parts.append("✅ "+" ｜ ".join(pos))
    if neg: parts.append("🔴 "+" ｜ ".join(neg))

    # 計算 foreign_5d etc. for card compatibility
    f5d = float(inst_df["外資"].tail(5).fillna(0).sum()) if not inst_df.empty and "外資" in inst_df.columns else 0
    t5d = float(inst_df["投信"].tail(5).fillna(0).sum()) if not inst_df.empty and "投信" in inst_df.columns else 0
    fs  = sum(1 for v in (inst_df["外資"].tail(5).fillna(0).tolist() if not inst_df.empty and "外資" in inst_df.columns else []) if v > 0)

    return {
        "signal": final >= 60, "score": final,
        "grade": grade, "grade_label": lbl, "grade_action": act, "grade_color": gc,
        "reason": "  ".join(parts) if parts else "⬜ 無明確信號",
        "breakdown": bd, "yoy": yoy, "div_yield": dy,
        "foreign_5d": f5d, "trust_5d": t5d, "dealer_5d": 0,
        "foreign_streak": fs, "trust_streak": 0,
        "score_G": sum(b["pts"] for b in bd if b["stage"]=="G" and b["met"] and b["pts"]>0),
        "score_T": sum(b["pts"] for b in bd if b["stage"]=="T" and b["met"] and b["pts"]>0),
        "score_N": sum(b["pts"] for b in bd if b["stage"]=="N" and b["met"] and b["pts"]>0),
    }


    """新聞情緒分析"""
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=14)).strftime("%Y-%m-%d")
    headlines = []
    try:
        params = {"dataset":"TaiwanStockNews","data_id":sid,
                  "start_date":start,"end_date":end}
        if token: params["token"] = token
        r = requests.get(FINMIND_API, params=params, timeout=15)
        d = r.json()
        if d.get("status") == 200 and d.get("data"):
            df = pd.DataFrame(d["data"])
            if "title" in df.columns:
                headlines = df["title"].dropna().tolist()[-10:]
    except Exception: pass

    if not headlines:
        return {"score":0.0,"label":"無資料","color":"#5a8fa8",
                "summary":"","headlines":[],"count":0}

    prompt = f"""以下是台股 {sid} {name} 近期新聞：
{chr(10).join(['- '+h for h in headlines])}

只回傳 JSON，不加說明：
{{"score": 0.6, "label": "偏多", "summary": "30字以內摘要"}}

score: 0.8-1.0強多 / 0.4-0.8偏多 / -0.4-0.4中性 / -0.8--0.4偏空 / -1.0--0.8強空"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":200,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=20
        )
        text = resp.json()["content"][0]["text"]
        text = text.replace("```json","").replace("```","").strip()
        p = json.loads(text)
        sc = float(p.get("score",0))
        lbl= p.get("label","中性")
        clr = ("#00c87a" if sc>0.4 else "#f0c040" if sc>-0.4 else "#ff5c5c")
        return {"score":sc,"label":lbl,"color":clr,
                "summary":p.get("summary",""),"headlines":headlines,"count":len(headlines)}
    except Exception:
        return {"score":0.0,"label":"分析失敗","color":"#5a8fa8",
                "summary":"","headlines":headlines,"count":len(headlines)}


# ════════════════════════════════════════════════════════════════
# ⑤ 指標計算（日線）
# ════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c   = df["Close"].astype(float)
    vol = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(1.0, index=df.index)

    for n in [5,10,20,60]: df[f"MA{n}"] = c.rolling(n, min_periods=max(2,n//4)).mean()
    df["VolMA20"] = vol.rolling(20, min_periods=5).mean()

    delta = c.diff()
    g = delta.clip(lower=0).ewm(com=13,adjust=False).mean()
    l = (-delta).clip(lower=0).ewm(com=13,adjust=False).mean()
    df["RSI"] = 100 - 100/(1 + g/l.replace(0,np.nan))

    ema12 = c.ewm(span=12,adjust=False).mean()
    ema26 = c.ewm(span=26,adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_sig"] = df["MACD"].ewm(span=9,adjust=False).mean()
    df["MACD_h"]   = df["MACD"] - df["MACD_sig"]

    if "High" in df.columns and "Low" in df.columns:
        hi = df["High"].astype(float); lo = df["Low"].astype(float)
        pc = c.shift(1)
        tr = pd.concat([hi-lo,(hi-pc).abs(),(lo-pc).abs()],axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14,min_periods=5).mean()
    else:
        df["ATR"] = c * 0.02

    return df


# ════════════════════════════════════════════════════════════════
# ⑥ VWAP 盤前模組
# ════════════════════════════════════════════════════════════════

def compute_vwap(minute_df: pd.DataFrame) -> dict:
    """
    從分鐘 K 線計算 VWAP 與開盤區間。
    回傳：{vwap, open_range_high, open_range_low, trend, key_levels}
    """
    if minute_df.empty or len(minute_df) < 10:
        return {}

    df = minute_df.copy()
    df["typical"] = (df["High"] + df["Low"] + df["Close"]) / 3
    df["tp_vol"]  = df["typical"] * df["Volume"]
    df["cum_vol"] = df["Volume"].cumsum()
    df["cum_tpv"] = df["tp_vol"].cumsum()
    df["vwap"]    = df["cum_tpv"] / df["cum_vol"].replace(0, np.nan)

    vwap_last = float(df["vwap"].iloc[-1])
    close_last = float(df["Close"].iloc[-1])

    # 開盤區間（前 30 分鐘 ≈ 30 根 1 分鐘 K）
    first30 = df.head(30)
    or_high  = float(first30["High"].max()) if not first30.empty else close_last
    or_low   = float(first30["Low"].min())  if not first30.empty else close_last

    # 尾盤趨勢（後 30 分鐘）
    last30   = df.tail(30)
    late_vwap= float(last30["vwap"].mean()) if len(last30) >= 10 else vwap_last
    late_close= float(last30["Close"].mean())
    trend = "多" if late_close > late_vwap else "空"

    # 今日關鍵價位
    hi52 = float(df["High"].max())
    lo52 = float(df["Low"].min())

    return {
        "vwap":          round(vwap_last, 2),
        "or_high":       round(or_high, 2),
        "or_low":        round(or_low, 2),
        "trend":         trend,
        "close":         close_last,
        "above_vwap":    close_last > vwap_last,
        "day_high":      hi52,
        "day_low":       lo52,
        "vwap_gap_pct":  round((close_last - vwap_last) / vwap_last * 100, 2),
    }


def build_vwap_chart(minute_df: pd.DataFrame, sid: str, name: str,
                     vwap_info: dict) -> go.Figure:
    """分鐘 K + VWAP + 開盤區間圖"""
    df = minute_df.copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.7,0.3], vertical_spacing=0.03)

    # K 線
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="分鐘K",
        increasing_line_color="#00c87a", increasing_fillcolor="#00c87a",
        decreasing_line_color="#ff5c5c", decreasing_fillcolor="#ff5c5c",
        line=dict(width=1),
    ), row=1, col=1)

    # VWAP 線
    if "vwap" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["vwap"], name="VWAP",
            line=dict(color="#f0c040", width=2),
        ), row=1, col=1)

    # 開盤區間水平線
    if vwap_info:
        for price, lbl, clr in [
            (vwap_info["or_high"],  "開盤區間高", "#4ab3ff"),
            (vwap_info["or_low"],   "開盤區間低", "#c084fc"),
            (vwap_info["vwap"],     "VWAP",       "#f0c040"),
        ]:
            fig.add_hline(y=price, row=1, col=1,
                line=dict(color=clr, width=1, dash="dash"),
                annotation_text=f" {lbl} {price:.2f}",
                annotation_font=dict(color=clr, size=10))

    # 成交量
    vol_c = ["rgba(0,200,122,0.5)" if float(c) >= float(o) else "rgba(255,92,92,0.5)"
             for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df["date"], y=df["Volume"],
        marker_color=vol_c, showlegend=False), row=2, col=1)

    _BG = "#050e1a"; _GRID = "#0e2035"
    fig.update_layout(
        title=dict(text=f"<b>{sid} {name}</b>  分鐘K + VWAP",
                   font=dict(size=14,color="#e8f4f8"), x=0.01),
        paper_bgcolor="#030b14", plot_bgcolor=_BG,
        font=dict(family="IBM Plex Mono", color="#7aacb8", size=10),
        legend=dict(orientation="h", x=0.01, y=1.02, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=8,r=8,t=55,b=8), height=500,
        xaxis_rangeslider_visible=False, hovermode="x unified",
    )
    for row in [1,2]:
        fig.update_xaxes(row=row, gridcolor=_GRID, zeroline=False)
    fig.update_yaxes(row=1, gridcolor=_GRID, zeroline=False)
    fig.update_yaxes(row=2, gridcolor=_GRID, tickformat=".2s")
    return fig


# ════════════════════════════════════════════════════════════════
# ⑦ 核心評分：法人優先選股
# ════════════════════════════════════════════════════════════════

def score_institutional_first(
    inst_df:   pd.DataFrame,
    price_df:  pd.DataFrame,
    margin_df: pd.DataFrame,
    news:      dict,
    sid:       str = "",
) -> dict:
    """
    法人優先評分（100分制）

    G 大錢方向（法人）   55分  ← 最重要
    T 技術確認           30分
    N 新聞情緒           15分
    """
    bd  = []
    raw = 0.0

    # ══════════════════════════════════════════
    # G 大錢方向（55分）
    # ══════════════════════════════════════════

    foreign_5d = 0.0; trust_5d = 0.0; dealer_5d = 0.0
    foreign_days_positive = 0   # 外資連買天數
    trust_days_positive   = 0

    if not inst_df.empty and len(inst_df) >= 3:
        tail = inst_df.tail(10)

        if "外資" in tail.columns:
            foreign_5d = float(tail["外資"].tail(5).fillna(0).sum())
            # 連買天數
            vals = tail["外資"].fillna(0).tolist()
            for v in reversed(vals):
                if v > 0: foreign_days_positive += 1
                else: break

        if "投信" in tail.columns:
            trust_5d = float(tail["投信"].tail(5).fillna(0).sum())
            vals = tail["投信"].fillna(0).tolist()
            for v in reversed(vals):
                if v > 0: trust_days_positive += 1
                else: break

        if "自營" in tail.columns:
            dealer_5d = float(tail["自營"].tail(5).fillna(0).sum())

        # G1：外資買超力度（0~25分）
        if foreign_5d > 1e9:       g1, g1_l = 25, f"外資大量買超 {foreign_5d/1e8:.1f}億"
        elif foreign_5d > 2e8:     g1, g1_l = 18, f"外資持續買超 {foreign_5d/1e8:.1f}億"
        elif foreign_5d > 0:       g1, g1_l = 10, f"外資小量買超 {foreign_5d/1e6:.0f}萬"
        elif foreign_5d > -2e8:    g1, g1_l =  0, f"外資小幅賣超 {abs(foreign_5d)/1e6:.0f}萬"
        else:                      g1, g1_l = -15, f"外資大量賣超 {abs(foreign_5d)/1e8:.1f}億⚠️"
        raw += g1
        bd.append({"stage":"G","label":f"外資5日淨額：{g1_l}","pts":g1,
                   "met":g1>0,"detail":f"連買{foreign_days_positive}日"})

        # G2：外資連買天數加分（最高 +10）
        streak_pts = min(foreign_days_positive * 2, 10)
        if streak_pts > 0:
            raw += streak_pts
            bd.append({"stage":"G","label":f"外資連買{foreign_days_positive}日（動能持續）",
                       "pts":streak_pts,"met":True,"detail":""})

        # G3：投信買超（0~15分）
        if trust_5d > 5e7:         g3, g3_l = 15, f"投信積極買超 {trust_5d/1e6:.0f}萬"
        elif trust_5d > 0:         g3, g3_l =  8, f"投信輕量買超 {trust_5d/1e6:.0f}萬"
        elif trust_5d > -5e7:      g3, g3_l =  0, f"投信小幅賣超"
        else:                      g3, g3_l = -8, f"投信大量賣超⚠️"
        raw += g3
        bd.append({"stage":"G","label":f"投信5日：{g3_l}","pts":g3,
                   "met":g3>0,"detail":f"連買{trust_days_positive}日"})

        # G4：三大法人共識（外資+投信同向買超，+5）
        if foreign_5d > 0 and trust_5d > 0:
            raw += 5
            bd.append({"stage":"G","label":"外資+投信同向買超（籌碼共識）",
                       "pts":5,"met":True,"detail":"大錢方向一致，最強信號"})
    else:
        bd.append({"stage":"G","label":"法人資料無法取得（需Token）",
                   "pts":0,"met":False,"detail":""})

    # ── 融資過熱懲罰 ──────────────────────────────────────────
    if not margin_df.empty:
        mc = next((c for c in margin_df.columns if "MarginPurchase" in c and "Balance" in c), None)
        if mc and len(margin_df) >= 6:
            latest   = float(margin_df[mc].iloc[-1])
            wk_ago   = float(margin_df[mc].iloc[-6])
            chg_pct  = (latest - wk_ago) / (wk_ago + 1) * 100
            if chg_pct > 25:
                raw -= 12
                bd.append({"stage":"G","label":f"⚠️ 融資暴增{chg_pct:.0f}%（散戶接刀）",
                           "pts":-12,"met":True,"detail":"高風險，主力可能趁機出貨"})

    # ══════════════════════════════════════════
    # T 技術確認（30分）
    # ══════════════════════════════════════════

    if not price_df.empty and len(price_df) >= 10:
        df = compute_indicators(price_df)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        close = float(last["Close"])

        def _v(col):
            v = last.get(col)
            return float(v) if v is not None and not pd.isna(v) else np.nan

        ma5=_v("MA5"); ma10=_v("MA10"); ma20=_v("MA20"); ma60=_v("MA60")
        rsi=_v("RSI"); macd_h=_v("MACD_h"); atr=_v("ATR")
        vol=float(last.get("Volume",0))
        vol5=float(df["Volume"].tail(6).iloc[:-1].mean()) if len(df)>=6 else 0
        p_close = float(prev["Close"])

        # T1：價格站上 MA20（+12）
        t1 = not np.isnan(ma20) and close > ma20
        raw += 12 if t1 else 0
        bd.append({"stage":"T","label":"收盤站上20MA月線",
                   "pts":12,"met":t1,
                   "detail":f"收{close:.1f} / MA20={ma20:.1f}" if not np.isnan(ma20) else "N/A"})

        # T2：均線多頭排列（+10）
        t2 = (not any(np.isnan(x) for x in [ma5,ma10,ma20]) and ma5>ma10>ma20)
        raw += 10 if t2 else 0
        bd.append({"stage":"T","label":"短中線多頭排列（MA5>MA10>MA20）",
                   "pts":10,"met":t2,"detail":""})

        # T3：MACD 動能（+8）
        t3 = not np.isnan(macd_h) and macd_h > 0
        raw += 8 if t3 else 0
        bd.append({"stage":"T","label":f"MACD 柱狀圖偏多（{macd_h:.2f}）",
                   "pts":8,"met":t3,"detail":""})

        # RSI 過熱懲罰
        if not np.isnan(rsi) and rsi > 78:
            raw -= 8
            bd.append({"stage":"T","label":f"⚠️ RSI過熱（{rsi:.0f}），追高風險",
                       "pts":-8,"met":True,"detail":""})
    else:
        bd.append({"stage":"T","label":"技術資料不足","pts":0,"met":False,"detail":""})

    # ══════════════════════════════════════════
    # N 新聞情緒（15分）
    # ══════════════════════════════════════════

    if news and news.get("count", 0) > 0:
        ns    = float(news.get("score", 0))
        n_pts = round(ns * 15)   # -15 ~ +15
        raw  += n_pts
        lbl   = news.get("label","中性")
        bd.append({"stage":"N",
                   "label":f"新聞情緒：{lbl}（{n_pts:+d}分）",
                   "pts":int(n_pts),"met":n_pts>0,
                   "detail":news.get("summary","")})

    # ── 最終計算 ─────────────────────────────────────────────
    final = float(max(0.0, min(100.0, raw)))

    # 評級
    if final >= 80:   grade,lbl,act,gc = "AAA","強力買進","外資+投信持續佈局，強力建議分批進場","#00c87a"
    elif final >= 65: grade,lbl,act,gc = "AA","積極佈局","法人多頭明確，可積極布局","#80d840"
    elif final >= 50: grade,lbl,act,gc = "A","觀察佈局","法人輕量買進，可小量試單","#f0c040"
    elif final >= 35: grade,lbl,act,gc = "B","謹慎觀望","法人訊號不明確，待觀察","#f0a500"
    else:              grade,lbl,act,gc = "C","建議空手","法人無明顯買進或賣超，勿進場","#ff5c5c"

    signal = final >= 65 and foreign_5d >= 0

    pos = [b["label"] for b in bd if b["met"] and b["pts"] > 0]
    neg = [b["label"] for b in bd if b["met"] and b["pts"] < 0]
    parts = []
    if pos: parts.append("✅ " + " ｜ ".join(pos))
    if neg: parts.append("🔴 " + " ｜ ".join(neg))

    return {
        "signal":        signal,
        "score":         final,
        "grade":         grade,
        "grade_label":   lbl,
        "grade_action":  act,
        "grade_color":   gc,
        "reason":        "  ".join(parts) if parts else "⬜ 無明確信號",
        "breakdown":     bd,
        "foreign_5d":    foreign_5d,
        "trust_5d":      trust_5d,
        "dealer_5d":     dealer_5d,
        "foreign_streak":foreign_days_positive,
        "trust_streak":  trust_days_positive,
        "score_G":       sum(b["pts"] for b in bd if b["stage"]=="G" and b["met"] and b["pts"]>0),
        "score_T":       sum(b["pts"] for b in bd if b["stage"]=="T" and b["met"] and b["pts"]>0),
        "score_N":       sum(b["pts"] for b in bd if b["stage"]=="N" and b["met"] and b["pts"]>0),
    }


# ════════════════════════════════════════════════════════════════
# ⑧ 買賣建議價位
# ════════════════════════════════════════════════════════════════

def compute_zones(price_df: pd.DataFrame, mode: str = "mid") -> dict:
    if price_df.empty or len(price_df) < 10: return {}
    df   = compute_indicators(price_df)
    last = df.iloc[-1]
    close= float(last["Close"])

    def _v(col, fb=None):
        v = last.get(col)
        if v is None or (isinstance(v,float) and np.isnan(v)):
            return fb if fb is not None else close
        return float(v)

    atr  = _v("ATR", close*0.025)
    ma20 = _v("MA20", close)
    ma60 = _v("MA60", close)
    hi20 = float(df["High"].tail(20).max()) if "High" in df.columns else close*1.05
    lo10 = float(df["Low"].tail(10).min())  if "Low"  in df.columns else close*0.95

    if mode == "short":
        entry_a = round(close * 1.005, 1)
        entry_b = round(close * 0.985, 1)
        stop    = round(max(close - 1.5*atr, lo10*0.995), 1)
        t1      = round(close + 2.0*atr, 1)
        t2      = round(max(close + 3.5*atr, hi20*0.99), 1)
        note    = "✅ 短線：現在可進場追動能，停損設 1.5×ATR"
    elif mode == "mid":
        gap = (close-ma20)/ma20*100
        if gap <= 5:
            entry_a = round(close*1.003, 1); note = "✅ 已接近月線，可直接進場"
        else:
            entry_a = round(close*0.97, 1); note = f"⏳ 等小回 {gap:.1f}%→3%，再進場"
        entry_b = round(ma20*1.005, 1)
        stop    = round(ma20*0.97, 1)
        t1      = round(entry_a + 3.0*atr, 1)
        t2      = round(hi20*0.97, 1)
    else:
        entry_a = round(ma60*1.01, 1)
        entry_b = round(ma60*0.99, 1)
        stop    = round(ma60*0.97, 1)
        t1      = round(entry_a + 4.0*atr, 1)
        t2      = round(hi20, 1)
        note    = f"⏳ 長線：等回季線MA60附近 ({ma60:.1f})"

    risk   = max(entry_a - stop, atr*0.3)
    reward = t1 - entry_a
    rr     = round(reward/risk, 2) if risk > 0 else 0.0

    return {
        "entry_a":entry_a,"entry_b":entry_b,"stop":stop,
        "t1":t1,"t2":t2,"rr":rr,"atr":round(atr,2),"note":note,
    }


# ════════════════════════════════════════════════════════════════
# ⑨ 主掃描函式（法人優先）
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)
def run_institutional_scan(token: str, mode: str, max_stocks: int,
                           sector_filter: str = "全部產業") -> pd.DataFrame:
    universe = get_universe()

    # 套用產業篩選
    if sector_filter != "全部產業":
        universe = [s for s in universe if SECTOR_MAP.get(s,"其他") == sector_filter]

    universe = universe[:max_stocks]
    if not universe:
        return pd.DataFrame()

    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=120)).strftime("%Y-%m-%d")

    # 長線需要更多歷史資料
    if mode == "value":
        start = (datetime.today() - timedelta(days=180)).strftime("%Y-%m-%d")

    prog = st.progress(0.0)
    stat = st.empty()
    rows = []

    mode_label = {"daytrade":"當沖準備","swing":"波段操作","value":"中長線存股"}[mode]

    for i, sid in enumerate(universe):
        name = STOCK_NAMES.get(sid, sid)
        stat.markdown(
            f"<span style='color:#3a8aaa;font-size:0.8rem;'>"
            f"🏦 [{mode_label}] 分析 {sid} {name}（{i+1}/{len(universe)}）</span>",
            unsafe_allow_html=True
        )
        prog.progress((i+1)/len(universe))

        price_df  = fetch_price(sid, start, end, token)
        inst_df   = fetch_institutional(sid, token)
        margin_df = fetch_margin(sid, token)
        news      = fetch_news_sentiment(sid, name, token)

        if price_df.empty or len(price_df) < 5:
            time.sleep(0.2); continue

        # 依模式選擇評分函式
        if mode == "value":
            rev_df = fetch_monthly_revenue(sid, token)
            sc = score_value(inst_df, price_df, rev_df, news, sid)
            # 長線門檻：基本面 + 技術即可
            min_score = 35
        else:
            sc = score_institutional_first(inst_df, price_df, margin_df, news, sid)
            # 動態門檻：有法人資料用 40，沒有用 20（技術面備援）
            inst_available = not inst_df.empty and len(inst_df) >= 3
            min_score = 40 if inst_available else 20

        if sc["score"] < min_score:
            time.sleep(0.2); continue

        zone_mode = {"daytrade":"short","swing":"mid","value":"long"}[mode]
        zones = compute_zones(price_df, zone_mode)
        last  = price_df.iloc[-1]
        prev  = price_df.iloc[-2] if len(price_df) >= 2 else last
        chg   = (float(last["Close"])-float(prev["Close"]))/float(prev["Close"])*100

        # 計算昨日量能比（當沖模式額外重視）
        vol_today = float(last.get("Volume",0)) if "Volume" in last.index else 0
        vol_5d_avg= float(price_df["Volume"].tail(6).iloc[:-1].mean()) if len(price_df)>=6 else 0
        vol_ratio  = round(vol_today/vol_5d_avg, 2) if vol_5d_avg > 0 else 0

        rows.append({
            "代號":      sid,
            "名稱":      name,
            "產業":      SECTOR_MAP.get(sid,"其他"),
            "策略":      mode_label,
            "收盤價":    round(float(last["Close"]),1),
            "漲跌%":     round(chg,2),
            "評分":      round(sc["score"],0),
            "評級":      sc["grade"],
            "行動":      sc["grade_action"],
            "評級色":    sc["grade_color"],
            "信號":      "✅ 買進" if sc["signal"] else "⬜ 觀察",
            "G法人":     sc["score_G"],
            "T技術":     sc["score_T"],
            "N新聞":     sc["score_N"],
            "外資5日億": round(sc["foreign_5d"]/1e8, 2),
            "外資連買日":sc["foreign_streak"],
            "投信5日萬": round(sc["trust_5d"]/1e4, 0),
            "投信連買日":sc["trust_streak"],
            "量比":      vol_ratio,
            "新聞情緒":  news.get("label","—"),
            "新聞色":    news.get("color","#5a8fa8"),
            "殖利率%":   sc.get("div_yield", 0) if mode=="value" else 0,
            "YoY%":      sc.get("yoy", 0)       if mode=="value" else 0,
            "進場價":    zones.get("entry_a",0),
            "停損價":    zones.get("stop",0),
            "目標一":    zones.get("t1",0),
            "目標二":    zones.get("t2",0),
            "風報比":    zones.get("rr",0),
            "原因":      sc["reason"],
            "_sc":       sc,
            "_zones":    zones,
            "_price_df": price_df,
        })
        time.sleep(0.3)

    prog.empty(); stat.empty()
    if not rows: return pd.DataFrame()

    df = pd.DataFrame(rows)
    # 排序：當沖按量比，波段按外資連買，長線按殖利率+評分
    if mode == "daytrade":
        df = df.sort_values(["量比","評分"], ascending=[False,False])
    elif mode == "value":
        df = df.sort_values(["殖利率%","評分"], ascending=[False,False])
    else:
        df = df.sort_values(["外資連買日","評分"], ascending=[False,False])

    return df.reset_index(drop=True)
    universe = get_universe()[:max_stocks]
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=120)).strftime("%Y-%m-%d")

    prog = st.progress(0.0)
    stat = st.empty()
    rows = []

    for i, sid in enumerate(universe):
        name = STOCK_NAMES.get(sid, sid)
        stat.markdown(
            f"<span style='color:#3a8aaa;font-size:0.8rem;'>"
            f"🏦 分析法人動向：{sid} {name}（{i+1}/{len(universe)}）</span>",
            unsafe_allow_html=True
        )
        prog.progress((i+1)/len(universe))

        price_df  = fetch_price(sid, start, end, token)
        inst_df   = fetch_institutional(sid, token)
        margin_df = fetch_margin(sid, token)
        news      = fetch_news_sentiment(sid, name, token)

        if price_df.empty or len(price_df) < 5:
            time.sleep(0.2); continue

        sc = score_institutional_first(inst_df, price_df, margin_df, news, sid)

        # 低於 B 級（35分）不列出，避免塞爆
        if sc["score"] < 35:
            time.sleep(0.2); continue

        zones = compute_zones(price_df, mode)
        last  = price_df.iloc[-1]
        prev  = price_df.iloc[-2] if len(price_df) >= 2 else last
        chg   = (float(last["Close"])-float(prev["Close"]))/float(prev["Close"])*100

        rows.append({
            "代號":      sid,
            "名稱":      name,
            "產業":      SECTOR_MAP.get(sid,"其他"),
            "收盤價":    round(float(last["Close"]),1),
            "漲跌%":     round(chg,2),
            "評分":      round(sc["score"],0),
            "評級":      sc["grade"],
            "行動":      sc["grade_action"],
            "評級色":    sc["grade_color"],
            "信號":      "✅ 買進" if sc["signal"] else "⬜ 觀察",
            "G法人":     sc["score_G"],
            "T技術":     sc["score_T"],
            "N新聞":     sc["score_N"],
            "外資5日億": round(sc["foreign_5d"]/1e8, 2),
            "外資連買日":sc["foreign_streak"],
            "投信5日萬": round(sc["trust_5d"]/1e4, 0),
            "投信連買日":sc["trust_streak"],
            "新聞情緒":  news.get("label","—"),
            "新聞色":    news.get("color","#5a8fa8"),
            "進場價":    zones.get("entry_a",0),
            "停損價":    zones.get("stop",0),
            "目標一":    zones.get("t1",0),
            "目標二":    zones.get("t2",0),
            "風報比":    zones.get("rr",0),
            "原因":      sc["reason"],
            "_sc":       sc,
            "_zones":    zones,
            "_price_df": price_df,
        })
        time.sleep(0.3)

    prog.empty(); stat.empty()
    if not rows: return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values(["評分","外資連買日"], ascending=[False,False]).reset_index(drop=True)
    return df


# ════════════════════════════════════════════════════════════════
# ⑩ K 線圖（日線）
# ════════════════════════════════════════════════════════════════

def build_daily_chart(price_df: pd.DataFrame, sid: str, name: str,
                      zones: dict = None) -> go.Figure:
    df = compute_indicators(price_df.tail(120).reset_index(drop=True))
    fig = make_subplots(rows=3,cols=1,shared_xaxes=True,
                        row_heights=[0.55,0.22,0.23],vertical_spacing=0.02)

    _BG="#050e1a"; _GRID="#0e2035"; _UP="#00c87a"; _DN="#ff5c5c"

    fig.add_trace(go.Candlestick(
        x=df["date"],open=df["Open"],high=df["High"],
        low=df["Low"],close=df["Close"],name="K線",
        increasing_line_color=_UP,increasing_fillcolor=_UP,
        decreasing_line_color=_DN,decreasing_fillcolor=_DN,
        line=dict(width=1),
    ),row=1,col=1)

    for col,clr,w,d in [("MA5","#f0c040",1.0,"dot"),("MA20","#4ab3ff",1.6,"solid"),("MA60","#c084fc",1.8,"dash")]:
        if col in df.columns and df[col].notna().any():
            fig.add_trace(go.Scatter(x=df["date"],y=df[col],name=col,
                line=dict(color=clr,width=w,dash=d)),row=1,col=1)

    # 進場線標注
    if zones:
        for price,lbl,clr in [
            (zones.get("entry_a",0),"進場A","#f0e060"),
            (zones.get("entry_b",0),"進場B","#80d840"),
            (zones.get("stop",0),   "停損", "#ff5c5c"),
            (zones.get("t1",0),     "目標1","#00c87a"),
            (zones.get("t2",0),     "目標2","#4ab3ff"),
        ]:
            if price > 0:
                fig.add_hline(y=price,row=1,col=1,
                    line=dict(color=clr,width=1.2,dash="dash"),
                    annotation_text=f" {lbl} {price:.1f}",
                    annotation_font=dict(color=clr,size=10))

    if "Volume" in df.columns:
        vc = ["rgba(0,200,122,0.45)" if float(c)>=float(o) else "rgba(255,92,92,0.45)"
              for c,o in zip(df["Close"],df["Open"])]
        fig.add_trace(go.Bar(x=df["date"],y=df["Volume"],marker_color=vc,
            showlegend=False),row=2,col=1)

    if "RSI" in df.columns and df["RSI"].notna().any():
        fig.add_trace(go.Scatter(x=df["date"],y=df["RSI"],
            line=dict(color="#f0a500",width=1.4),name="RSI"),row=3,col=1)
    if "MACD_h" in df.columns and df["MACD_h"].notna().any():
        hc=["rgba(0,200,122,0.6)" if v>0 else "rgba(255,92,92,0.6)"
            for v in df["MACD_h"].fillna(0)]
        fig.add_trace(go.Bar(x=df["date"],y=df["MACD_h"],
            marker_color=hc,showlegend=False),row=3,col=1)
    for lvl,clr in [(70,"#ff5c5c"),(50,"#4ab3ff"),(30,"#00c87a")]:
        fig.add_hline(y=lvl,row=3,col=1,
            line=dict(color=clr,width=0.8,dash="dot"))

    fig.update_layout(
        title=dict(text=f"<b>{sid} {name}</b>  日K + 進場標注",
                   font=dict(size=14,color="#e8f4f8"),x=0.01),
        paper_bgcolor="#030b14",plot_bgcolor=_BG,
        font=dict(family="IBM Plex Mono",color="#7aacb8",size=10),
        legend=dict(orientation="h",x=0.01,y=1.02,bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=8,r=8,t=55,b=8),height=680,
        xaxis_rangeslider_visible=False,hovermode="x unified",
    )
    for r in [1,2,3]:
        fig.update_xaxes(row=r,gridcolor=_GRID,zeroline=False)
    fig.update_yaxes(row=1,gridcolor=_GRID,zeroline=False)
    fig.update_yaxes(row=2,gridcolor=_GRID,tickformat=".2s")
    fig.update_yaxes(row=3,gridcolor=_GRID,range=[0,100],dtick=20)
    return fig


# ════════════════════════════════════════════════════════════════
# ⑪ UI：法人流向卡片渲染
# ════════════════════════════════════════════════════════════════

def _rr_color(rr):
    return "#00c87a" if rr>=2 else ("#f0a500" if rr>=1 else "#ff5c5c")

def _mk_bar(val, max_abs, pos_color, neg_color):
    """雙向流量條"""
    pct = min(abs(val)/max(max_abs,1)*100, 100)
    clr = pos_color if val >= 0 else neg_color
    return (f'<div class="fb-bar"><div class="fb-fill" '
            f'style="width:{pct:.0f}%;background:{clr};"></div></div>')

def render_inst_card(row) -> str:
    gc   = row.get("評級色","#5a8fa8")
    sc   = float(row.get("評分",0))
    sig  = row.get("信號","") == "✅ 買進"
    card_cls = "ic-buy" if sig else ("ic-sell" if sc < 35 else "ic-neut")

    chg  = float(row.get("漲跌%",0))
    chg_c= "#00c87a" if chg>=0 else "#ff5c5c"
    chg_s= "▲" if chg>=0 else "▼"

    f5 = float(row.get("外資5日億",0))
    t5 = float(row.get("投信5日萬",0))
    f_str = f'{f5:+.2f}億'
    t_str = f'{int(t5):+d}萬'
    f_c   = "#00c87a" if f5>=0 else "#ff5c5c"
    t_c   = "#00c87a" if t5>=0 else "#ff5c5c"

    fs = int(row.get("外資連買日",0))
    ts = int(row.get("投信連買日",0))

    # 評分進度條（G/T/N三段）
    sg = float(row.get("G法人",0))
    st = float(row.get("T技術",0))
    sn = float(row.get("N新聞",0))
    def _seg(val,mx,clr,lbl):
        p=min(val/max(mx,1)*100,100)
        return (f'<div style="flex:1;margin:0 2px;">'
                f'<div style="font-size:0.58rem;color:#3a6a8a;margin-bottom:2px;">{lbl}</div>'
                f'<div style="background:#0e2030;border-radius:3px;height:5px;">'
                f'<div style="width:{p:.0f}%;height:100%;border-radius:3px;background:{clr};"></div></div>'
                f'<div style="font-size:0.6rem;color:{clr};text-align:center;">{val:.0f}</div>'
                f'</div>')
    bars = (f'<div style="display:flex;margin:6px 0 10px;gap:2px;">'
            f'{_seg(sg,55,"#f0c040","G法人")}'
            f'{_seg(st,30,"#4ab3ff","T技術")}'
            f'{_seg(max(sn,0),15,"#00c87a","N新聞")}'
            f'</div>')

    # 進場建議
    z = row.get("_zones",{}) or {}
    entry_a = z.get("entry_a",0); stop = z.get("stop",0)
    t1 = z.get("t1",0); rr = z.get("rr",0)
    rc = _rr_color(rr)
    zone_html = ""
    if entry_a and sig:
        zone_html = f"""
      <div class="entry-box">
        <div style="font-size:0.64rem;color:#2a6a8a;letter-spacing:0.08em;margin-bottom:8px;">💡 操作建議</div>
        <div class="entry-grid">
          <div><div class="eg-label">📥 進場價</div>
               <div class="eg-val" style="color:#f0e060;">{entry_a:,.1f}</div></div>
          <div><div class="eg-label">🛑 停損價</div>
               <div class="eg-val" style="color:#ff7878;">{stop:,.1f}</div></div>
          <div><div class="eg-label">🎯 目標一</div>
               <div class="eg-val" style="color:#00c87a;">{t1:,.1f}</div></div>
          <div><div class="eg-label">⚖️ 風報比</div>
               <div class="eg-val" style="color:{rc};">1:{rr:.1f}</div></div>
        </div>
        <div style="font-size:0.68rem;color:#3a6a8a;margin-top:6px;">{z.get('note','')}</div>
      </div>"""

    news_lbl  = str(row.get("新聞情緒",""))
    news_c    = str(row.get("新聞色","#5a8fa8"))
    news_html = f'<span style="color:{news_c};font-size:0.72rem;">📰 {news_lbl}</span>' if news_lbl else ""

    return f"""
    <div class="inst-card {card_cls}">
      <div style="position:absolute;top:12px;right:14px;text-align:right;">
        <div class="score-ring" style="border:2.5px solid {gc};color:{gc};">{sc:.0f}</div>
        <div style="font-size:0.65rem;color:{gc};margin-top:2px;">{row.get('評級','')}</div>
      </div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;color:#3a7a9a;">
        {row.get('代號','')} · {row.get('產業','')}
      </div>
      <div style="font-size:1.1rem;font-weight:700;color:#e8f4f8;margin:2px 0 2px;">
        {row.get('名稱','')}
      </div>
      <div style="font-size:0.7rem;color:#2a6a8a;margin-bottom:4px;">{row.get('行動','')}</div>
      {bars}
      <span style="font-family:'IBM Plex Mono',monospace;font-size:1.4rem;color:#e8f4f8;">
        {float(row.get('收盤價',0)):,.1f}
      </span>
      <span style="color:{chg_c};font-size:0.88rem;">&nbsp;{chg_s} {abs(chg):.2f}%</span>
      <div style="margin-top:8px;display:flex;flex-direction:column;gap:3px;">
        <div class="flow-bar">
          <span class="fb-label">外資</span>
          {_mk_bar(f5, max(abs(f5),0.1), "#00c87a","#ff5c5c")}
          <span class="fb-val" style="color:{f_c};">{f_str}
            {"🔥" if fs>=5 else ""}{f" ×{fs}日" if fs>0 else ""}</span>
        </div>
        <div class="flow-bar">
          <span class="fb-label">投信</span>
          {_mk_bar(t5, max(abs(t5),1), "#4ab3ff","#ff9090")}
          <span class="fb-val" style="color:{t_c};">{t_str}
            {f" ×{ts}日" if ts>0 else ""}</span>
        </div>
      </div>
      {news_html}
      {zone_html}
    </div>"""


# ════════════════════════════════════════════════════════════════
# ⑫ 盤前 VWAP 掃描模組
# ════════════════════════════════════════════════════════════════

def render_vwap_card(sid: str, name: str, vi: dict, price: float) -> str:
    if not vi: return ""

    trend_c  = "#00c87a" if vi["trend"] == "多" else "#ff5c5c"
    above_c  = "#00c87a" if vi["above_vwap"] else "#ff5c5c"
    above_lbl= "收盤在 VWAP 之上 ✅" if vi["above_vwap"] else "收盤在 VWAP 之下 ⚠️"
    gap_str  = f"{vi['vwap_gap_pct']:+.2f}%"

    return f"""
    <div class="vwap-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;">
        <div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:#3a7a9a;">{sid}</div>
          <div class="vc-stock">{name}</div>
          <div style="font-size:0.72rem;margin-top:3px;color:{above_c};">{above_lbl}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.64rem;color:#3a6a8a;">尾盤趨勢</div>
          <div style="font-size:1.2rem;font-weight:700;color:{trend_c};">
            {"↑ 多頭" if vi["trend"]=="多" else "↓ 空頭"}</div>
        </div>
      </div>
      <div class="vc-grid">
        <div class="vg-item">
          <div class="vg-label">📊 VWAP</div>
          <div class="vg-value" style="color:#f0c040;">{vi['vwap']:,.2f}</div>
          <div style="font-size:0.62rem;color:#3a6a8a;">距離 {gap_str}</div>
        </div>
        <div class="vg-item">
          <div class="vg-label">📈 開盤區間高</div>
          <div class="vg-value" style="color:#4ab3ff;">{vi['or_high']:,.2f}</div>
          <div style="font-size:0.62rem;color:#3a6a8a;">前30分鐘高點</div>
        </div>
        <div class="vg-item">
          <div class="vg-label">📉 開盤區間低</div>
          <div class="vg-value" style="color:#c084fc;">{vi['or_low']:,.2f}</div>
          <div style="font-size:0.62rem;color:#3a6a8a;">前30分鐘低點</div>
        </div>
      </div>
      <div style="margin-top:8px;font-size:0.72rem;color:#3a6a8a;padding:6px 8px;
                  background:#0a1a2a;border-radius:5px;">
        🎯 明日關鍵價位：突破開盤區間高 <span style="color:#4ab3ff;">{vi['or_high']:,.2f}</span> 可追；
        跌破 VWAP <span style="color:#f0c040;">{vi['vwap']:,.2f}</span> 轉空
      </div>
    </div>"""


# ════════════════════════════════════════════════════════════════
# ⑬ 主程式
# ════════════════════════════════════════════════════════════════

def main():
    # ── Sidebar ──────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ 設定")

        token = st.text_input("FinMind Token（選填）", type="password",
                              placeholder="有Token速度更快、資料更完整")

        st.divider()
        st.markdown("**🎯 選股策略模式**")
        mode = st.radio("我的目標是",
            options=["daytrade","swing","value"],
            format_func=lambda x: {
                "daytrade": "⚡ 當沖準備（盤前選標的）",
                "swing":    "📊 波段操作（7-30日）",
                "value":    "🏦 中長線存股（配息+成長）",
            }[x],
            index=1)

        # 各模式說明
        mode_tips = {
            "daytrade": (
                "**當沖準備邏輯**\n"
                "- 找昨日量能異常、有催化劑的股票\n"
                "- 開盤後看 VWAP 突破再進場\n"
                "- ⚠️ 本系統提供盤前準備，不能取代即時盤口判斷\n"
                "- 建議搭配「盤前VWAP」Tab 使用"
            ),
            "swing": (
                "**波段操作邏輯（最推薦）**\n"
                "- 外資連買 3日+ 為核心訊號\n"
                "- 技術面確認（突破均線+量能）\n"
                "- 族群輪動加分\n"
                "- 持有 7-30 天，等強勢結束再出場"
            ),
            "value": (
                "**中長線存股邏輯**\n"
                "- 月營收年增率 > 15%（成長股）\n"
                "- 金融股/電信股殖利率 > 4%（存股）\n"
                "- 法人長期持有（3個月累積）\n"
                "- 適合分批買進，持有 3個月-1年以上"
            ),
        }
        st.info(mode_tips[mode])

        st.divider()
        st.markdown("**🏭 產業篩選**")

        # 整理所有產業（從 SECTOR_MAP 取）
        all_sectors = sorted(set(SECTOR_MAP.values()))
        all_sectors = ["全部產業"] + all_sectors

        sel_sector = st.selectbox(
            "選擇聚焦產業",
            options=all_sectors,
            index=0,
            help="選擇特定產業可縮短掃描時間，並聚焦在你熟悉的領域"
        )

        st.divider()
        st.markdown("**📡 掃描設定**")

        # 根據模式設定預設掃描數量
        default_max = {"daytrade": 30, "swing": 40, "value": 60}[mode]
        max_stocks = st.slider(
            "掃描股票數量", 20, len(get_universe()), default_max, 10,
            help="數量越多越完整，但需更多時間"
        )

        universe_size = len(get_universe())
        if sel_sector != "全部產業":
            filtered_size = sum(1 for s in get_universe() if SECTOR_MAP.get(s,"其他") == sel_sector)
            st.caption(f"篩選後：{filtered_size} 檔 / 宇宙共 {universe_size} 檔")
        else:
            st.caption(f"股票宇宙：{universe_size} 檔（0050 + 0051 + 法人重倉）")

        col1, col2 = st.columns(2)
        run_btn = col1.button("🔍 開始掃描", type="primary", use_container_width=True)
        clr_btn = col2.button("🗑️ 清快取", use_container_width=True)
        if clr_btn:
            st.cache_data.clear()
            st.session_state.clear()
            st.success("已清除")

        st.divider()
        # 評分權重說明（依模式）
        weight_info = {
            "daytrade": "G 昨日量能異常  +35\nG 法人當日動向  +25\nT 技術位置(VWAP) +25\nN 新聞催化劑     +15",
            "swing":    "G 外資連買天數  +35\nG 投信同向買超  +20\nT 技術突破確認  +30\nN 新聞情緒       +15",
            "value":    "F 營收年增率    +25\nF 殖利率/護城河 +20\nG 法人長期持有  +30\nT 均線多頭排列   +25",
        }
        st.markdown(
            f'<div style="font-size:0.7rem;color:#3a5a70;line-height:1.8;'
            f'background:#060f1c;border:1px solid #1a3050;border-radius:8px;padding:10px;">'
            f'<b style="color:#4a8aaa;">本模式評分邏輯</b><br>'
            + weight_info[mode].replace("\n","<br>") + "</div>",
            unsafe_allow_html=True
        )
        st.divider()
        st.caption("⚠️ 僅供研究，不構成投資建議")

    # ── Header ───────────────────────────────────────────────
    st.markdown("""
    <div class="header">
      <div class="h-title">🏦 台股法人追蹤 × 盤前 VWAP 決策系統 v3.0</div>
      <div class="h-sub">外資 · 投信 · 三大法人 · 新聞情緒 · VWAP 盤前準備</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 大盤狀態 ─────────────────────────────────────────────
    end_mkt  = datetime.today().strftime("%Y-%m-%d")
    start_mkt= (datetime.today()-timedelta(days=120)).strftime("%Y-%m-%d")
    with st.spinner("載入大盤…"):
        tdf = fetch_taiex(start_mkt, end_mkt, token)

    if not tdf.empty and len(tdf) >= 20:
        tdf = compute_indicators(tdf)
        last_t = tdf.iloc[-1]
        cl  = float(last_t["Close"])
        m20 = float(last_t["MA20"]) if not pd.isna(last_t.get("MA20")) else None
        m60 = float(last_t["MA60"]) if not pd.isna(last_t.get("MA60")) else None
        bull = m60 is not None and cl > m60
        barcls = "ok-bar" if bull else "warn-bar"
        m20s = f"{m20:,.2f}" if m20 else "N/A"
        m60s = f"{m60:,.2f}" if m60 else "N/A"
        date_s = last_t["date"].strftime("%Y-%m-%d")
        is_proxy = tdf.attrs.get("is_proxy", False)
        proxy_note = "（以 0050 代理大盤）" if is_proxy else ""
        st.markdown(
            f'<div class="{barcls}">'
            f'大盤參考 {date_s}{proxy_note}：<b>{cl:,.2f}</b>'
            f'&nbsp;｜&nbsp; 20MA {m20s} &nbsp; 60MA {m60s}'
            f'&nbsp;｜&nbsp;<b>{"多頭格局 ✅" if bull else "空頭警示 ⚠️"}</b>'
            f'{"&nbsp;｜&nbsp;建議持倉 100%" if bull else "&nbsp;｜&nbsp;建議倉位降至 30%"}'
            f'</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="info-bar">⚠️ 大盤資料暫時無法取得，選股功能不受影響</div>',
            unsafe_allow_html=True
        )

    # ── Tabs ─────────────────────────────────────────────────
    tab_inst, tab_vwap, tab_custom = st.tabs([
        "🏦 法人追蹤選股", "📊 盤前 VWAP 準備", "🔍 自選股分析"
    ])

    # ════════════════════════════════════════
    # Tab 1：法人追蹤選股
    # ════════════════════════════════════════
    with tab_inst:
        if "scan_df" not in st.session_state:
            st.session_state["scan_df"] = None

        if run_btn:
            with st.spinner("掃描法人動向中，請稍候…"):
                st.session_state["scan_df"]   = run_institutional_scan(
                    token, mode, max_stocks, sel_sector
                )
                st.session_state["scan_mode"] = mode

        scan_df = st.session_state.get("scan_df")

        if scan_df is None:
            st.markdown("""
            <div class="info-bar">
            👈 點左側「🔍 開始掃描」啟動法人追蹤選股<br><br>
            <b>這套系統的選股邏輯：</b><br>
            ① 先找外資連續買超的股票（最重要）<br>
            ② 再確認投信是否同向佈局<br>
            ③ 技術面確認（MA均線、MACD）<br>
            ④ 新聞情緒加分<br>
            ⑤ 輸出評分 + 進場價位
            </div>""", unsafe_allow_html=True)
            return

        if scan_df.empty:
            st.markdown(
                '<div class="warn-bar">'
                '<b>掃描結果為空，可能原因：</b><br>'
                '① 今日法人整體賣超，技術面也偏弱（正常現象，可改選「全部產業」重掃）<br>'
                '② FinMind API 速率限制（請等 30 秒後點「清快取」再掃）<br>'
                '③ 請試著把「掃描股票數量」調低到 20 檔，排除速率問題<br>'
                '④ 確認 Token 已正確填入（法人資料需要 Token）'
                '</div>',
                unsafe_allow_html=True
            )
            return

        # 篩選器
        f1, f2, f3 = st.columns([2,2,2])
        with f1:
            grade_f = st.multiselect("評級",["AAA","AA","A","B"],
                                     default=["AAA","AA","A"])
        with f2:
            buy_only = st.checkbox("只看買進信號", value=False)
        with f3:
            min_foreign = st.slider("外資最低連買天數", 0, 10, 0, 1)

        view = scan_df.copy()
        if grade_f:     view = view[view["評級"].isin(grade_f)]
        if buy_only:    view = view[view["信號"] == "✅ 買進"]
        if min_foreign: view = view[view["外資連買日"] >= min_foreign]

        # Top 5 置頂卡片
        mode_lbl = {"short":"⚡短線","mid":"📊中線","long":"🔭長線"}[mode]
        st.markdown(
            f'<div class="sec-title">今日最佳標的 Top 5 &nbsp;'
            f'<span style="font-size:0.72rem;color:#3a6a8a;">{mode_lbl} · 依外資買超排序</span></div>',
            unsafe_allow_html=True
        )

        top5 = view.sort_values(["外資連買日","評分"], ascending=[False,False]).head(5)

        if top5.empty:
            st.markdown(
                '<div class="warn-bar">目前篩選條件下無標的，可嘗試調整「外資連買天數」或取消評級篩選</div>',
                unsafe_allow_html=True
            )
        else:
            for chunk in [top5.iloc[:3], top5.iloc[3:]]:
                if chunk.empty: continue
                cols = st.columns(len(chunk))
                for i, (_, row) in enumerate(chunk.iterrows()):
                    cols[i].markdown(render_inst_card(row), unsafe_allow_html=True)

        scan_mode_used = st.session_state.get("scan_mode", mode)
        mode_labels = {"daytrade":"當沖準備","swing":"波段操作","value":"中長線存股"}
        mode_lbl2 = mode_labels.get(scan_mode_used, "")

        # 完整排行榜
        st.markdown(f'<div class="sec-title">完整排行（{len(view)} 筆）· {mode_lbl2}</div>',
                    unsafe_allow_html=True)

        # 依模式顯示不同欄位
        if scan_mode_used == "value":
            dcols = ["代號","名稱","產業","收盤價","漲跌%","評分","評級",
                     "殖利率%","YoY%","外資5日億","外資連買日","投信5日萬",
                     "新聞情緒","G法人","T技術","進場價","停損價","目標一"]
        elif scan_mode_used == "daytrade":
            dcols = ["代號","名稱","產業","收盤價","漲跌%","評分","評級",
                     "量比","外資5日億","新聞情緒","G法人","T技術","N新聞",
                     "進場價","停損價","目標一","風報比"]
        else:
            dcols = ["代號","名稱","產業","收盤價","漲跌%","評分","評級",
                     "外資5日億","外資連買日","投信5日萬","投信連買日",
                     "新聞情緒","G法人","T技術","N新聞","進場價","停損價","目標一","風報比"]
        disp = view[[c for c in dcols if c in view.columns]].copy()

        def _cn(v): return "color:#00c87a" if isinstance(v,(int,float)) and v>0 else ("color:#ff5c5c" if isinstance(v,(int,float)) and v<0 else "")
        def _cs(v): return f"color:{'#00c87a' if v>=65 else '#f0a500' if v>=35 else '#ff5c5c'};font-weight:bold" if isinstance(v,(int,float)) else ""

        fmt_cols = {k:v for k,v in {
            "收盤價":"{:.1f}","漲跌%":"{:+.2f}%","評分":"{:.0f}",
            "外資5日億":"{:+.2f}","投信5日萬":"{:+.0f}",
            "G法人":"{:.0f}","T技術":"{:.0f}","N新聞":"{:.0f}",
            "進場價":"{:.1f}","停損價":"{:.1f}","目標一":"{:.1f}","風報比":"{:.2f}",
        }.items() if k in disp.columns}

        styled = (disp.style
            .map(_cn, subset=[c for c in ["漲跌%","外資5日億","投信5日萬"] if c in disp.columns])
            .map(_cs, subset=[c for c in ["評分"] if c in disp.columns])
            .format(fmt_cols)
            .set_properties(**{"font-size":"0.82rem"}))

        st.dataframe(styled, use_container_width=True, height=420, hide_index=True)

        csv = disp.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("⬇️ 匯出 CSV", csv,
            f"inst_{mode}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", "text/csv")

        # K 線圖
        st.markdown('<div class="sec-title">個股 K 線圖</div>', unsafe_allow_html=True)
        if not view.empty:
            opts = [f"{row['代號']}  {row['名稱']}  ({row['評級']} {row['評分']:.0f}分  外資×{int(row['外資連買日'])}日)"
                    for _, row in view.iterrows()]
            sel = st.selectbox("選擇股票", opts, index=0)
            sel_id = sel.strip().split()[0]
            sel_name = STOCK_NAMES.get(sel_id, sel_id)
            matched = view[view["代號"]==sel_id]
            if not matched.empty:
                z = matched.iloc[0].get("_zones",{})
                pdf = matched.iloc[0].get("_price_df", pd.DataFrame())
                if not pdf.empty:
                    st.plotly_chart(build_daily_chart(pdf, sel_id, sel_name, z),
                        use_container_width=True,
                        config={"displayModeBar":True,
                                "toImageButtonOptions":{"filename":f"{sel_id}_chart","scale":2}})

    # ════════════════════════════════════════
    # Tab 2：盤前 VWAP 準備
    # ════════════════════════════════════════
    with tab_vwap:
        st.markdown('<div class="sec-title">盤前 VWAP 準備（昨日分鐘線分析）</div>',
                    unsafe_allow_html=True)

        st.markdown("""
        <div class="info-bar">
        <b>使用說明：</b>系統抓取「昨日」的分鐘 K 線，計算 VWAP 與開盤區間，
        幫你在今日開盤前做好功課，知道每支股票的關鍵價位。<br><br>
        <b>操作邏輯（Williams + Cameron）：</b><br>
        · 今日開盤後若<b>突破昨日開盤區間高</b>且量放大 → 追多<br>
        · 股價回測至 <b>VWAP</b> 附近獲得支撐 → 逢低買進<br>
        · 跌破 VWAP 且量縮 → 不追，等待
        </div>""", unsafe_allow_html=True)

        # 選股來源
        vwap_source = st.radio("分析標的來源",
            ["從掃描結果取前10名","手動輸入代號"],
            horizontal=True)

        if vwap_source == "從掃描結果取前10名":
            scan_df2 = st.session_state.get("scan_df")
            if scan_df2 is None or scan_df2.empty:
                st.warning("請先在「法人追蹤選股」Tab 完成掃描")
                return
            vwap_targets = scan_df2.head(10)[["代號","名稱"]].values.tolist()
        else:
            custom_input = st.text_input("輸入代號（逗號分隔）",
                                          placeholder="例：2330,2317,2454")
            if not custom_input.strip():
                st.info("輸入代號後按 Enter")
                return
            vwap_targets = [(sid.strip(), STOCK_NAMES.get(sid.strip(), sid.strip()))
                            for sid in custom_input.split(",") if sid.strip()]

        # 選擇日期（預設昨日）
        yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        # 若昨日是週末，往前找
        dt = datetime.today() - timedelta(days=1)
        while dt.weekday() >= 5:  # 0=Mon, 6=Sun
            dt -= timedelta(days=1)
        default_date = dt.strftime("%Y-%m-%d")

        vwap_date = st.date_input("選擇日期", value=dt).strftime("%Y-%m-%d")

        if st.button("📊 計算 VWAP", type="primary"):
            st.session_state["vwap_results"] = {}
            prog_v = st.progress(0.0)

            for i, (sid, name) in enumerate(vwap_targets):
                prog_v.progress((i+1)/len(vwap_targets))
                min_df = fetch_minute(sid, vwap_date, token)
                if min_df.empty:
                    st.session_state["vwap_results"][sid] = {"error": True, "name": name}
                    continue
                vi = compute_vwap(min_df)
                # 日收盤
                pdf = fetch_price(sid, vwap_date, vwap_date, token)
                price = float(pdf.iloc[-1]["Close"]) if not pdf.empty else 0
                st.session_state["vwap_results"][sid] = {
                    "vi": vi, "name": name, "min_df": min_df, "price": price
                }
                time.sleep(0.3)
            prog_v.empty()

        vwap_res = st.session_state.get("vwap_results", {})
        if vwap_res:
            # 分類：多頭（昨日尾盤在VWAP上方）vs 空頭
            bull_list = [(sid,d) for sid,d in vwap_res.items()
                         if not d.get("error") and d.get("vi",{}).get("above_vwap")]
            bear_list = [(sid,d) for sid,d in vwap_res.items()
                         if not d.get("error") and not d.get("vi",{}).get("above_vwap")]

            st.markdown(
                f'<div class="ok-bar">✅ 昨日尾盤站上 VWAP（今日偏多）：{len(bull_list)} 檔</div>',
                unsafe_allow_html=True
            )
            if bull_list:
                bc = st.columns(min(3, len(bull_list)))
                for i, (sid, d) in enumerate(bull_list[:3]):
                    bc[i].markdown(
                        render_vwap_card(sid, d["name"], d["vi"], d["price"]),
                        unsafe_allow_html=True
                    )

            if bear_list:
                st.markdown(
                    f'<div class="warn-bar">⚠️ 昨日尾盤跌破 VWAP（今日謹慎）：{len(bear_list)} 檔</div>',
                    unsafe_allow_html=True
                )

            # 選一檔看分鐘圖
            st.markdown('<div class="sec-title">昨日分鐘 K + VWAP 圖</div>',
                        unsafe_allow_html=True)
            valid = [(sid,d) for sid,d in vwap_res.items() if not d.get("error")]
            if valid:
                chart_opts = [f"{sid}  {d['name']}" for sid,d in valid]
                sel_v = st.selectbox("選擇查看", chart_opts, index=0)
                sel_vsid = sel_v.strip().split()[0]
                d = vwap_res.get(sel_vsid, {})
                if d and not d.get("error"):
                    min_df2 = d.get("min_df", pd.DataFrame())
                    vi2     = d.get("vi", {})
                    if not min_df2.empty and vi2:
                        # 重新算 VWAP 欄位
                        min_df2 = min_df2.copy()
                        min_df2["typical"] = (min_df2["High"]+min_df2["Low"]+min_df2["Close"])/3
                        min_df2["tp_vol"]  = min_df2["typical"]*min_df2["Volume"]
                        min_df2["cum_vol"] = min_df2["Volume"].cumsum()
                        min_df2["cum_tpv"] = min_df2["tp_vol"].cumsum()
                        min_df2["vwap"]    = min_df2["cum_tpv"]/min_df2["cum_vol"].replace(0,np.nan)
                        fig_v = build_vwap_chart(min_df2, sel_vsid,
                                                  STOCK_NAMES.get(sel_vsid,sel_vsid), vi2)
                        st.plotly_chart(fig_v, use_container_width=True)

    # ════════════════════════════════════════
    # Tab 3：自選股分析
    # ════════════════════════════════════════
    with tab_custom:
        st.markdown('<div class="sec-title">輸入任意台股代號 → 法人 + 技術 + 新聞全面分析</div>',
                    unsafe_allow_html=True)

        ci, cb = st.columns([3,1])
        cid    = ci.text_input("股票代號", placeholder="例：2330").strip()
        do_it  = cb.button("🔬 分析", type="primary", use_container_width=True)

        if do_it and cid:
            cname = STOCK_NAMES.get(cid, cid)
            end_c = datetime.today().strftime("%Y-%m-%d")
            start_c = (datetime.today()-timedelta(days=120)).strftime("%Y-%m-%d")
            with st.spinner(f"分析 {cid} {cname}…"):
                pdf_c  = fetch_price(cid, start_c, end_c, token)
                inst_c = fetch_institutional(cid, token)
                mg_c   = fetch_margin(cid, token)
                news_c = fetch_news_sentiment(cid, cname, token)
            if pdf_c.empty:
                st.error(f"找不到 {cid} 資料，請確認代號")
            else:
                sc_c   = score_institutional_first(inst_c, pdf_c, mg_c, news_c, cid)
                zones_c= compute_zones(pdf_c, mode)
                st.session_state["custom_result"] = {
                    "sc":sc_c,"zones":zones_c,"pdf":pdf_c,"news":news_c,
                    "sid":cid,"name":cname,
                    "inst_df":inst_c,
                }

        cr = st.session_state.get("custom_result",{})
        if cr:
            sc   = cr["sc"]
            z    = cr["zones"]
            pdf  = cr["pdf"]
            news = cr["news"]
            sid  = cr["sid"]
            name = cr["name"]
            inst = cr.get("inst_df", pd.DataFrame())

            st.markdown(f'<div class="sec-title">{sid} {name} · 綜合分析報告</div>',
                        unsafe_allow_html=True)

            # 三欄指標
            c1,c2,c3 = st.columns(3)
            gc = sc["grade_color"]
            c1.markdown(
                f'<div class="inst-card" style="border-color:{gc};">'
                f'<div style="font-size:0.75rem;color:#3a7a9a;">GPS 總評分</div>'
                f'<div style="font-family:monospace;font-size:2.5rem;font-weight:700;color:{gc};">'
                f'{sc["score"]:.0f}</div>'
                f'<div style="font-size:0.85rem;color:{gc};">{sc["grade"]} {sc["grade_label"]}</div>'
                f'<div style="font-size:0.72rem;color:#4a7a9a;margin-top:4px;">{sc["grade_action"]}</div>'
                f'</div>', unsafe_allow_html=True
            )
            c2.markdown(
                f'<div class="inst-card">'
                f'<div style="font-size:0.75rem;color:#3a7a9a;">法人動向（5日）</div>'
                f'<div style="margin-top:8px;">'
                f'<div style="font-size:0.82rem;color:{"#00c87a" if sc["foreign_5d"]>=0 else "#ff5c5c"};">'
                f'外資：{sc["foreign_5d"]/1e8:+.2f} 億（連買 {sc["foreign_streak"]} 日）</div>'
                f'<div style="font-size:0.82rem;color:{"#4ab3ff" if sc["trust_5d"]>=0 else "#ff9090"};">'
                f'投信：{sc["trust_5d"]/1e4:+.0f} 萬（連買 {sc["trust_streak"]} 日）</div>'
                f'</div></div>', unsafe_allow_html=True
            )
            ns_c = news.get("color","#5a8fa8")
            c3.markdown(
                f'<div class="inst-card">'
                f'<div style="font-size:0.75rem;color:#3a7a9a;">新聞情緒</div>'
                f'<div style="font-size:1.6rem;font-weight:700;color:{ns_c};margin-top:8px;">'
                f'{news.get("label","N/A")}</div>'
                f'<div style="font-size:0.75rem;color:#5a8fa8;margin-top:4px;">'
                f'{news.get("summary","")}</div>'
                f'<div style="font-size:0.68rem;color:#3a5a70;">{news.get("count",0)} 則新聞</div>'
                f'</div>', unsafe_allow_html=True
            )

            # 評分明細
            with st.expander("📋 評分明細", expanded=True):
                bd_rows = [{"階段": b["stage"], "條件": b["label"],
                            "分值": b["pts"], "達標": "✅" if (b["met"] and b["pts"]>0)
                            else "🔴" if (b["met"] and b["pts"]<0) else "❌",
                            "說明": b.get("detail","")}
                           for b in sc["breakdown"]]
                st.dataframe(pd.DataFrame(bd_rows), use_container_width=True,
                             hide_index=True)

            # 進場建議
            if z:
                el=z.get("entry_a",0); stop=z.get("stop",0)
                t1=z.get("t1",0); t2=z.get("t2",0); rr=z.get("rr",0)
                rc=_rr_color(rr)
                st.markdown(
                    f'<div class="entry-box">'
                    f'<div style="font-size:0.68rem;color:#2a6a8a;letter-spacing:0.1em;margin-bottom:10px;">💡 操作建議（{mode}）</div>'
                    f'<div class="entry-grid">'
                    f'<div><div class="eg-label">📥 進場價</div><div class="eg-val" style="color:#f0e060;">{el:,.1f}</div></div>'
                    f'<div><div class="eg-label">🛑 停損價</div><div class="eg-val" style="color:#ff7878;">{stop:,.1f}</div></div>'
                    f'<div><div class="eg-label">🎯 目標一</div><div class="eg-val" style="color:#00c87a;">{t1:,.1f}</div></div>'
                    f'<div><div class="eg-label">🚀 目標二</div><div class="eg-val" style="color:#4ab3ff;">{t2:,.1f}</div></div>'
                    f'</div>'
                    f'<div style="margin-top:6px;font-size:0.75rem;">'
                    f'風報比 <span style="color:{rc};">1:{rr:.1f}</span> &nbsp;｜&nbsp; ATR {z.get("atr",0):.2f}</div>'
                    f'<div style="font-size:0.68rem;color:#3a6a8a;margin-top:4px;">{z.get("note","")}</div>'
                    f'</div>', unsafe_allow_html=True
                )

            # K 線圖
            st.plotly_chart(build_daily_chart(pdf, sid, name, z),
                use_container_width=True,
                config={"toImageButtonOptions":{"filename":f"{sid}_analysis","scale":2}})

            # 法人歷史明細
            if not inst.empty:
                with st.expander("📊 三大法人每日明細", expanded=False):
                    inst_show = inst.tail(20).copy()
                    inst_show["date"] = inst_show["date"].dt.strftime("%Y-%m-%d")
                    for col in ["外資","投信","自營"]:
                        if col in inst_show.columns:
                            inst_show[col] = inst_show[col].apply(
                                lambda v: f"{v/1e4:+.0f}萬" if pd.notna(v) else "—")
                    st.dataframe(inst_show[["date"]+[c for c in ["外資","投信","自營"]
                                                     if c in inst_show.columns]],
                                 use_container_width=True, hide_index=True)

            # 近期新聞
            if news.get("headlines"):
                with st.expander("📰 近期新聞標題", expanded=False):
                    for h in news["headlines"][:10]:
                        st.markdown(f"· {h}")
        else:
            st.markdown("""
            <div style="background:#060f1c;border:1px dashed #1a3050;border-radius:10px;
                        padding:30px;text-align:center;color:#2a6a8a;margin:20px 0;">
              <div style="font-size:2rem;">🏦</div>
              <div style="font-size:1rem;margin-top:8px;">輸入股票代號</div>
              <div style="font-size:0.82rem;margin-top:4px;color:#2a5a7a;">
                取得外資/投信買賣詳情 · GPS評分 · 進場建議 · 新聞情緒 · K線圖
              </div>
            </div>""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
