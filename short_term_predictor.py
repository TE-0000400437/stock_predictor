#!/usr/bin/env python3
"""
短期株価予測マルチエージェントシステム
4専門エージェント + オーケストレーターで1〜2週間後の株価動向を予測します。

使い方:
    python short_term_predictor.py                    # デフォルト銘柄リストを分析
    python short_term_predictor.py NVDA MSFT AAPL    # 指定銘柄を分析

環境変数:
    ANTHROPIC_API_KEY  (必須)
"""

import os
import sys
import json
import re
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import anthropic
import yfinance as yf
import pandas as pd
import numpy as np
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# ==============================================================================
# 設定
# ==============================================================================

MODEL = os.environ.get("STOCK_MODEL", "claude-opus-4-6")
SUPPORTS_THINKING = "haiku" not in MODEL
console = Console()

# 短期予測用エージェントの重み（テクニカル重視）
AGENT_WEIGHTS = {
    "technical": 0.40,  # 短期はテクニカルが最重要
    "momentum":  0.25,  # 価格・出来高モメンタム
    "sentiment": 0.20,  # ニュース・アナリスト
    "pattern":   0.15,  # サポート/レジスタンス・ローソク足
}

# ==============================================================================
# データ構造
# ==============================================================================

@dataclass
class AgentResult:
    name: str
    key: str
    score: float        # 0-100
    confidence: str     # 高/中/低
    reasoning: str
    signals: list[str]


@dataclass
class StockAnalysis:
    ticker: str
    company_name: str
    current_price: float
    currency: str = "USD"
    sector: str = ""
    agent_results: list[AgentResult] = field(default_factory=list)
    final_score: float = 0.0
    recommendation: str = ""
    summary: str = ""
    error: Optional[str] = None


# ==============================================================================
# ユーティリティ
# ==============================================================================

def extract_json(text: str) -> dict:
    """テキストからJSONオブジェクトを安全に抽出する"""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)

    start = text.find('{')
    if start == -1:
        return {}

    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return {}

    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def get_text_block(response) -> str:
    """レスポンスからテキストブロックを取得する（thinkingブロックは除外）"""
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def fmt(val, spec=".2f", prefix="", suffix="", divisor=1, na="N/A") -> str:
    """値を安全にフォーマットする"""
    try:
        if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
            return na
        return f"{prefix}{val / divisor:{spec}}{suffix}"
    except Exception:
        return str(val) if val is not None else na


def score_to_recommendation(score: float) -> str:
    if score >= 75: return "強い買い"
    if score >= 62: return "買い"
    if score >= 48: return "中立"
    if score >= 35: return "売り"
    return "強い売り"


# ==============================================================================
# データ取得・前処理
# ==============================================================================

def fetch_stock_data(ticker: str) -> dict:
    """yfinanceで株式データを取得し短期テクニカル指標を計算する"""
    stock = yf.Ticker(ticker)

    # 短期分析なので3ヶ月のデータを取得
    hist = stock.history(period="3mo")
    info = stock.info

    news = []
    try:
        news = stock.news[:15]
    except Exception:
        pass

    # テクニカル指標の計算（短期重視）
    if not hist.empty and len(hist) >= 14:
        close  = hist['Close']
        high   = hist['High']
        low    = hist['Low']
        volume = hist['Volume']

        # 短期EMA（短期予測に重要）
        hist['EMA5']  = close.ewm(span=5,  adjust=False).mean()
        hist['EMA10'] = close.ewm(span=10, adjust=False).mean()
        hist['EMA20'] = close.ewm(span=20, adjust=False).mean()
        hist['SMA20'] = close.rolling(20).mean()

        # RSI (14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / (loss + 1e-10)
        hist['RSI'] = 100 - (100 / (1 + rs))

        # ストキャスティクス (14, 3)
        low14  = low.rolling(14).min()
        high14 = high.rolling(14).max()
        hist['Stoch_K'] = (close - low14) / (high14 - low14 + 1e-10) * 100
        hist['Stoch_D'] = hist['Stoch_K'].rolling(3).mean()

        # MACD (12/26/9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        hist['MACD']        = ema12 - ema26
        hist['MACD_Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
        hist['MACD_Hist']   = hist['MACD'] - hist['MACD_Signal']

        # ボリンジャーバンド (20, ±2σ)
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        hist['BB_upper'] = sma20 + 2 * std20
        hist['BB_mid']   = sma20
        hist['BB_lower'] = sma20 - 2 * std20

        # ATR (14) - 短期ボラティリティ測定
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        hist['ATR'] = tr.rolling(14).mean()

        # 出来高移動平均・比率
        hist['Vol_SMA20'] = volume.rolling(20).mean()
        hist['Vol_Ratio'] = volume / (hist['Vol_SMA20'] + 1)

        # OBV (On-Balance Volume)
        obv = [0]
        for i in range(1, len(close)):
            if close.iloc[i] > close.iloc[i - 1]:
                obv.append(obv[-1] + volume.iloc[i])
            elif close.iloc[i] < close.iloc[i - 1]:
                obv.append(obv[-1] - volume.iloc[i])
            else:
                obv.append(obv[-1])
        hist['OBV'] = obv

    return {
        "ticker":  ticker,
        "info":    info,
        "history": hist,
        "news":    news,
    }


def prepare_technical_context(data: dict) -> str:
    """短期テクニカル分析コンテキスト"""
    hist = data["history"]
    if hist.empty:
        return "価格データなし"

    latest = hist.iloc[-1]
    cp = float(latest['Close'])

    def pct(n):
        if len(hist) > n:
            old = float(hist.iloc[-n - 1]['Close'])
            return f"{(cp - old) / old * 100:+.2f}%"
        return "N/A"

    lines = [
        "=== 短期テクニカル指標 ===",
        f"現在株価: ${cp:.2f}",
        "",
        "--- 直近パフォーマンス ---",
        f"1日:   {pct(1)}",
        f"3日:   {pct(3)}",
        f"5日:   {pct(5)}",
        f"10日:  {pct(10)}",
        f"20日:  {pct(20)}",
        "",
        "--- 短期EMA ---",
    ]

    for col, label in [("EMA5", "EMA5"), ("EMA10", "EMA10"), ("EMA20", "EMA20")]:
        if col in hist.columns:
            v = latest.get(col)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                pos = "上方" if cp > float(v) else "下方"
                lines.append(f"{label}: ${float(v):.2f}  (現在株価は{pos})")

    # EMAクロス判定
    if 'EMA5' in hist.columns and 'EMA10' in hist.columns and len(hist) >= 2:
        try:
            ema5_now  = float(hist['EMA5'].iloc[-1])
            ema5_prev = float(hist['EMA5'].iloc[-2])
            ema10_now  = float(hist['EMA10'].iloc[-1])
            ema10_prev = float(hist['EMA10'].iloc[-2])
            if ema5_prev < ema10_prev and ema5_now > ema10_now:
                lines.append("EMA5/10: ゴールデンクロス（直近発生）")
            elif ema5_prev > ema10_prev and ema5_now < ema10_now:
                lines.append("EMA5/10: デッドクロス（直近発生）")
            else:
                cross = "EMA5 > EMA10" if ema5_now > ema10_now else "EMA5 < EMA10"
                lines.append(f"EMAクロス状態: {cross}")
        except Exception:
            pass

    if 'RSI' in hist.columns:
        rsi = latest.get('RSI')
        if rsi is not None and not (isinstance(rsi, float) and np.isnan(rsi)):
            rsi = float(rsi)
            label = "買われすぎ" if rsi > 70 else "売られすぎ" if rsi < 30 else "中立圏"
            lines += ["", f"RSI(14): {rsi:.1f}  ({label})"]
            # RSIダイバージェンス簡易チェック
            if len(hist) >= 5 and 'RSI' in hist.columns:
                rsi_5d   = float(hist['RSI'].iloc[-5])
                close_5d = float(hist['Close'].iloc[-5])
                if cp > close_5d and rsi < rsi_5d:
                    lines.append("  ⚠ 弱気ダイバージェンス（価格↑ / RSI↓）")
                elif cp < close_5d and rsi > rsi_5d:
                    lines.append("  ↑ 強気ダイバージェンス（価格↓ / RSI↑）")

    if 'Stoch_K' in hist.columns and 'Stoch_D' in hist.columns:
        k = latest.get('Stoch_K')
        d = latest.get('Stoch_D')
        if k is not None and d is not None:
            try:
                k, d = float(k), float(d)
                stoch_label = "買われすぎ圏" if k > 80 else "売られすぎ圏" if k < 20 else "中立"
                lines += [
                    "",
                    f"ストキャスティクス %K: {k:.1f}  %D: {d:.1f}  ({stoch_label})",
                ]
            except Exception:
                pass

    if 'MACD' in hist.columns:
        macd  = latest.get('MACD')
        sig   = latest.get('MACD_Signal')
        hist_v = latest.get('MACD_Hist')
        if macd is not None and sig is not None:
            try:
                macd_f, sig_f = float(macd), float(sig)
                cross = "ゴールデンクロス" if macd_f > sig_f else "デッドクロス"
                h_trend = ""
                if len(hist) >= 3 and 'MACD_Hist' in hist.columns:
                    h_now  = float(hist['MACD_Hist'].iloc[-1])
                    h_prev = float(hist['MACD_Hist'].iloc[-2])
                    h_trend = "拡大中" if abs(h_now) > abs(h_prev) else "縮小中"
                lines += [
                    "",
                    f"MACD: {macd_f:.4f}  シグナル: {sig_f:.4f}  ({cross})",
                    f"ヒストグラム: {float(hist_v):.4f}  {h_trend}",
                ]
            except Exception:
                pass

    if 'BB_upper' in hist.columns:
        bu = latest.get('BB_upper')
        bm = latest.get('BB_mid')
        bl = latest.get('BB_lower')
        if bu is not None and bl is not None:
            try:
                bu, bm, bl = float(bu), float(bm), float(bl)
                pct_bb   = (cp - bl) / (bu - bl) * 100 if bu != bl else 50
                bb_width = (bu - bl) / bm * 100 if bm > 0 else 0
                lines += [
                    "",
                    "--- ボリンジャーバンド ---",
                    f"上限: ${bu:.2f}  中間: ${bm:.2f}  下限: ${bl:.2f}",
                    f"バンド内位置: {pct_bb:.1f}%  バンド幅: {bb_width:.1f}%",
                ]
            except Exception:
                pass

    return "\n".join(lines)


def prepare_momentum_context(data: dict) -> str:
    """モメンタム・出来高分析コンテキスト"""
    hist = data["history"]
    if hist.empty:
        return "データなし"

    latest = hist.iloc[-1]
    cp = float(latest['Close'])

    avg_vol  = float(hist['Volume'].mean())
    last_vol = float(latest['Volume'])
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0
    vol_label = '↑ 急増' if vol_ratio > 2 else '↑ 増加' if vol_ratio > 1.2 else '↓ 減少' if vol_ratio < 0.8 else '→ 平常'

    lines = [
        "=== モメンタム・出来高分析 ===",
        "",
        "--- 出来高分析 ---",
        f"直近出来高:     {last_vol:,.0f}",
        f"平均出来高(3ヶ月):{avg_vol:,.0f}",
        f"出来高比率:     {vol_ratio:.2f}x  ({vol_label})",
    ]

    # 直近5日の出来高トレンド
    if len(hist) >= 5:
        recent_vols = hist['Volume'].tail(5).tolist()
        vol_trend = "増加傾向" if recent_vols[-1] > recent_vols[0] else "減少傾向"
        lines.append(f"5日出来高トレンド: {vol_trend}")

    if 'ATR' in hist.columns:
        atr = latest.get('ATR')
        if atr is not None and not (isinstance(atr, float) and np.isnan(atr)):
            atr = float(atr)
            atr_pct = atr / cp * 100
            lines += [
                "",
                "--- ボラティリティ (ATR) ---",
                f"ATR(14): ${atr:.2f}  ({atr_pct:.2f}%/日)",
                f"予想1週間レンジ: ±${atr * 3.5:.2f}  (${cp - atr*3.5:.2f} 〜 ${cp + atr*3.5:.2f})",
            ]

    # 価格モメンタム
    lines += ["", "--- 価格モメンタム ---"]
    returns = hist['Close'].pct_change().dropna()
    if len(returns) >= 5:
        mom_5d  = float(returns.tail(5).sum())
        lines.append(f"5日モメンタム:  {mom_5d*100:+.2f}%")
    if len(returns) >= 10:
        mom_10d = float(returns.tail(10).sum())
        lines.append(f"10日モメンタム: {mom_10d*100:+.2f}%")

    if 'OBV' in hist.columns and len(hist) >= 5:
        try:
            obv_now  = float(hist['OBV'].iloc[-1])
            obv_prev = float(hist['OBV'].iloc[-5])
            obv_change = (obv_now - obv_prev) / abs(obv_prev) * 100 if obv_prev != 0 else 0
            lines += [
                "",
                "--- OBV (On-Balance Volume) ---",
                f"OBV 5日変化: {obv_change:+.1f}%",
                f"OBVトレンド: {'買い圧力↑' if obv_change > 0 else '売り圧力↑'}",
            ]
        except Exception:
            pass

    if len(returns) > 10:
        vol_ann = float(returns.std()) * np.sqrt(252) * 100
        lines.append(f"\n年率ボラティリティ: {vol_ann:.1f}%")

    return "\n".join(lines)


def prepare_sentiment_context(data: dict) -> str:
    """センチメント・ニュースコンテキスト"""
    info = data["info"]
    news = data["news"]

    lines = [
        "=== センチメント・ニュース分析 ===",
        "",
        "--- アナリスト評価 ---",
        f"推奨スコア:       {info.get('recommendationMean', 'N/A')}  (1=強買い, 5=強売り)",
        f"推奨キー:         {info.get('recommendationKey', 'N/A')}",
        f"アナリスト数:     {info.get('numberOfAnalystOpinions', 'N/A')}",
        f"目標株価（平均）: {fmt(info.get('targetMeanPrice'), '.2f', '$')}",
        f"現在株価:         {fmt(info.get('currentPrice'), '.2f', '$')}",
    ]

    target  = info.get('targetMeanPrice')
    current = info.get('currentPrice')
    if target and current and float(current) > 0:
        upside = (float(target) - float(current)) / float(current) * 100
        lines.append(f"目標価格との乖離: {upside:+.1f}%")

    lines += [
        "",
        "--- 空売り状況 ---",
        f"空売り残高(日数): {fmt(info.get('shortRatio'))}",
        f"空売り比率:       {fmt(info.get('shortPercentOfFloat'), '.1%')}",
    ]

    if news:
        lines += ["", "--- 最新ニュース ---"]
        for i, article in enumerate(news[:10], 1):
            # yfinance の新旧両構造に対応
            content   = article.get('content', article)
            title     = content.get('title') or article.get('title', 'N/A')
            publisher = (content.get('provider', {}) or {}).get('displayName') or article.get('publisher', '')
            pub_date  = content.get('pubDate') or content.get('displayTime')
            ts        = article.get('providerPublishTime')

            if pub_date:
                from datetime import timezone
                try:
                    dt = datetime.fromisoformat(pub_date.replace('Z', '+00:00')).astimezone()
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                    age_str = f"{int(age.total_seconds()) // 3600}時間前" if age.days == 0 else f"{age.days}日前"
                    lines.append(f"{i}. [{age_str}] {title}  [{publisher}]")
                except Exception:
                    lines.append(f"{i}. {title}  [{publisher}]")
            elif ts:
                dt  = datetime.fromtimestamp(ts)
                age = datetime.now() - dt
                age_str = f"{age.seconds // 3600}時間前" if age.days == 0 else f"{age.days}日前"
                lines.append(f"{i}. [{age_str}] {title}  [{publisher}]")
            else:
                lines.append(f"{i}. {title}  [{publisher}]")

    return "\n".join(lines)


def prepare_pattern_context(data: dict) -> str:
    """サポート/レジスタンス・ローソク足パターン分析コンテキスト"""
    hist = data["history"]
    if hist.empty or len(hist) < 10:
        return "データ不足"

    latest = hist.iloc[-1]
    prev   = hist.iloc[-2]
    cp     = float(latest['Close'])

    lines = [
        "=== サポート/レジスタンス・パターン分析 ===",
        "",
        "--- 直近ローソク足 ---",
        f"本日: 始値${float(latest['Open']):.2f}  高値${float(latest['High']):.2f}  安値${float(latest['Low']):.2f}  終値${float(latest['Close']):.2f}",
        f"前日: 始値${float(prev['Open']):.2f}  高値${float(prev['High']):.2f}  安値${float(prev['Low']):.2f}  終値${float(prev['Close']):.2f}",
    ]

    # 簡易ローソク足パターン判定
    body         = float(latest['Close']) - float(latest['Open'])
    total_range  = float(latest['High']) - float(latest['Low'])
    upper_shadow = float(latest['High']) - max(float(latest['Open']), float(latest['Close']))
    lower_shadow = min(float(latest['Open']), float(latest['Close'])) - float(latest['Low'])

    if total_range > 0:
        body_ratio  = abs(body) / total_range
        upper_ratio = upper_shadow / total_range
        lower_ratio = lower_shadow / total_range

        pattern = ""
        if body_ratio < 0.1:
            pattern = "十字線（方向感なし）"
        elif lower_ratio > 0.6 and body > 0:
            pattern = "ハンマー（強気反転シグナル）"
        elif upper_ratio > 0.6 and body < 0:
            pattern = "流れ星（弱気反転シグナル）"
        elif body > 0 and body_ratio > 0.6:
            pattern = "大陽線（強い買い圧力）"
        elif body < 0 and body_ratio > 0.6:
            pattern = "大陰線（強い売り圧力）"

        if pattern:
            lines.append(f"ローソク足パターン: {pattern}")

    # サポート/レジスタンスレベル
    lines += ["", "--- サポート/レジスタンスレベル ---"]

    if len(hist) >= 20:
        recent20 = hist.tail(20)
        r20_high = float(recent20['High'].max())
        r20_low  = float(recent20['Low'].min())
        lines += [
            f"20日高値（レジスタンス）: ${r20_high:.2f}  ({(r20_high - cp) / cp * 100:+.2f}%)",
            f"20日安値（サポート）:     ${r20_low:.2f}  ({(r20_low - cp) / cp * 100:+.2f}%)",
        ]

    if len(hist) >= 5:
        recent5 = hist.tail(5)
        r5_high = float(recent5['High'].max())
        r5_low  = float(recent5['Low'].min())
        lines += [
            f"5日高値:  ${r5_high:.2f}  ({(r5_high - cp) / cp * 100:+.2f}%)",
            f"5日安値:  ${r5_low:.2f}  ({(r5_low - cp) / cp * 100:+.2f}%)",
        ]

    # ブレイクアウト判定
    if len(hist) >= 11:
        try:
            prev10_high = float(hist['High'].iloc[:-1].tail(10).max())
            if float(latest['High']) > prev10_high:
                lines.append("⚡ ブレイクアウト: 直近10日高値を更新")
        except Exception:
            pass

    return "\n".join(lines)


# ==============================================================================
# AIエージェント
# ==============================================================================

RESPONSE_SCHEMA = """{
    "score": <0〜100の整数>,
    "confidence": "<高|中|低>",
    "reasoning": "<分析理由（日本語200文字以上）>",
    "signals": ["<シグナル1>", "<シグナル2>", "<シグナル3>"]
}"""


async def run_agent(
    async_client: anthropic.AsyncAnthropic,
    ticker: str,
    key: str,
    name: str,
    system: str,
    context: str,
) -> AgentResult:
    """汎用エージェント実行"""
    today = datetime.now().strftime("%Y年%m月%d日")
    prompt = f"""本日は{today}です。以下は{ticker}の{name}データです（yfinanceよりリアルタイム取得）。

【重要】あなたの学習データには含まれていない直近の情報が含まれています。
必ず下記の提供データのみに基づいて分析してください。内部知識で補完しないでください。

{context}

上記データを根拠に、本日時点から1〜2週間後の株価上昇可能性を0〜100で評価してください。
（80以上=強い上昇見込み / 60-79=上昇見込み / 40-59=中立 / 20-39=下落リスク / 20未満=強い下落リスク）

以下のJSON形式のみで回答してください（説明文不要）:
{RESPONSE_SCHEMA}"""

    kwargs = dict(model=MODEL, max_tokens=1024, system=system,
                  messages=[{"role": "user", "content": prompt}])
    if SUPPORTS_THINKING:
        kwargs["thinking"] = {"type": "adaptive"}

    for attempt in range(3):
        try:
            response = await async_client.messages.create(**kwargs)
            text = get_text_block(response)
            data = extract_json(text)
            return AgentResult(
                name=name,
                key=key,
                score=float(data.get("score", 50)),
                confidence=data.get("confidence", "低"),
                reasoning=data.get("reasoning", text[:400]),
                signals=data.get("signals", []),
            )
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))  # 5秒 → 10秒
                continue
            return AgentResult(name=name, key=key, score=50.0, confidence="低",
                               reasoning=f"エラー: {e}", signals=[])
        except Exception as e:
            return AgentResult(name=name, key=key, score=50.0, confidence="低",
                               reasoning=f"エラー: {e}", signals=[])


async def technical_agent(ac, ticker, ctx):
    return await run_agent(
        ac, ticker, "technical", "短期テクニカル分析",
        ("あなたは短期株式トレードのテクニカル分析専門家です。"
         "EMA・RSI・ストキャスティクス・MACD・ボリンジャーバンドを分析し、"
         "1〜2週間後の価格動向を評価します。必ずJSON形式のみで回答してください。"),
        ctx,
    )


async def momentum_agent(ac, ticker, ctx):
    return await run_agent(
        ac, ticker, "momentum", "モメンタム分析",
        ("あなたは株式のモメンタム・出来高分析専門家です。"
         "価格モメンタム・出来高トレンド・ATR・OBVを分析し、"
         "1〜2週間の短期的な価格の勢いを評価します。必ずJSON形式のみで回答してください。"),
        ctx,
    )


async def sentiment_agent(ac, ticker, ctx):
    return await run_agent(
        ac, ticker, "sentiment", "センチメント分析",
        ("あなたは株式市場の短期センチメント分析専門家です。"
         "最新ニュース・アナリスト評価・空売り動向を分析し、"
         "市場の短期的な心理が1〜2週間の株価に与える影響を評価します。必ずJSON形式のみで回答してください。"),
        ctx,
    )


async def pattern_agent(ac, ticker, ctx):
    return await run_agent(
        ac, ticker, "pattern", "パターン・レベル分析",
        ("あなたはローソク足パターンとサポート/レジスタンス分析の専門家です。"
         "重要な価格レベル・ローソク足パターン・ブレイクアウトを分析し、"
         "1〜2週間の短期的な価格の方向性を評価します。必ずJSON形式のみで回答してください。"),
        ctx,
    )


async def orchestrator_agent(
    async_client: anthropic.AsyncAnthropic,
    ticker: str,
    company_name: str,
    agent_results: list[AgentResult],
) -> tuple[float, str, str]:
    """オーケストレーター: 全エージェントの結果を統合して最終判断を下す"""

    key_map  = {r.key: r.score for r in agent_results}
    weighted = sum(key_map.get(k, 50) * w for k, w in AGENT_WEIGHTS.items())

    summary_text = "\n\n".join(
        f"【{r.name}】スコア: {r.score:.0f}/100  信頼度: {r.confidence}\n"
        f"分析: {r.reasoning[:400]}\n"
        f"シグナル: {' | '.join(r.signals[:3])}"
        for r in agent_results
    )

    today = datetime.now().strftime("%Y年%m月%d日")
    prompt = f"""本日は{today}です。以下は{company_name}({ticker})の各専門エージェント分析結果です（本日リアルタイム取得データに基づく）。

【重要】各エージェントの分析は本日取得した最新データに基づいています。
あなたの学習データで知っている過去の情報ではなく、以下の分析結果のみを根拠に最終判断してください。

{summary_text}

基本加重平均スコア (テクニカル40%/モメンタム25%/センチメント20%/パターン15%): {weighted:.1f}

これらを統合し、{today}時点から1〜2週間後の株価見通しの最終判断を行ってください。
短期予測であるため、テクニカルとモメンタムの信号を特に重視してください。

以下のJSON形式のみで回答してください:
{{
    "final_score": <0〜100の整数>,
    "recommendation": "<強い買い|買い|中立|売り|強い売り>",
    "summary": "<総合投資判断（日本語400文字以上）>",
    "key_catalysts": ["<主要シグナルまたは注意点1>", "<主要シグナルまたは注意点2>", "<主要リスク1>"]
}}

推奨基準: 75以上→強い買い, 62-74→買い, 48-61→中立, 35-47→売り, 35未満→強い売り"""

    kwargs = dict(model=MODEL, max_tokens=2048,
                  system=(
            "あなたは短期株式トレードの経験豊富なアナリストです。"
            "複数の専門エージェントの分析を統合し、1〜2週間の短期的な投資判断を提供します。"
            "必ずJSON形式のみで回答してください。"
        ),
        messages=[{"role": "user", "content": prompt}])
    if SUPPORTS_THINKING:
        kwargs["thinking"] = {"type": "adaptive"}

    for attempt in range(3):
        try:
            response = await async_client.messages.create(**kwargs)
            text = get_text_block(response)
            data = extract_json(text)
            return (
                float(data.get("final_score", weighted)),
                data.get("recommendation", score_to_recommendation(weighted)),
                data.get("summary", ""),
            )
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
                continue
            return weighted, score_to_recommendation(weighted), f"統合分析エラー: {e}"
        except Exception as e:
            return weighted, score_to_recommendation(weighted), f"統合分析エラー: {e}"


# ==============================================================================
# メイン分析フロー
# ==============================================================================

async def analyze_stock(
    async_client: anthropic.AsyncAnthropic,
    ticker: str,
) -> StockAnalysis:
    """1銘柄の完全分析パイプライン"""

    try:
        data = fetch_stock_data(ticker)
    except Exception as e:
        return StockAnalysis(
            ticker=ticker, company_name=ticker,
            current_price=0.0, error=f"データ取得失敗: {e}",
        )

    info         = data["info"]
    company_name = info.get("longName") or info.get("shortName") or ticker
    sector       = info.get("sector", "N/A")
    currency     = info.get("currency", "JPY" if ticker.endswith(".T") else "USD")

    current_price = float(info.get("currentPrice") or 0)
    if not current_price and not data["history"].empty:
        current_price = float(data["history"].iloc[-1]["Close"])

    # コンテキスト準備（短期特化）
    tech_ctx     = prepare_technical_context(data)
    momentum_ctx = prepare_momentum_context(data)
    senti_ctx    = prepare_sentiment_context(data)
    pattern_ctx  = prepare_pattern_context(data)

    # 4エージェントを並行実行
    raw_results = await asyncio.gather(
        technical_agent(async_client, ticker, tech_ctx),
        momentum_agent(async_client, ticker, momentum_ctx),
        sentiment_agent(async_client, ticker, senti_ctx),
        pattern_agent(async_client, ticker, pattern_ctx),
        return_exceptions=True,
    )

    valid_results = [r for r in raw_results if isinstance(r, AgentResult)]

    if not valid_results:
        return StockAnalysis(
            ticker=ticker, company_name=company_name,
            current_price=current_price, sector=sector,
            error="全エージェントが失敗しました",
        )

    # オーケストレーターで統合
    final_score, recommendation, summary = await orchestrator_agent(
        async_client, ticker, company_name, valid_results
    )

    return StockAnalysis(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        currency=currency,
        sector=sector,
        agent_results=valid_results,
        final_score=final_score,
        recommendation=recommendation,
        summary=summary,
    )


# ==============================================================================
# 結果表示
# ==============================================================================

def display_results(analyses: list[StockAnalysis]) -> None:
    valid  = sorted([a for a in analyses if not a.error], key=lambda x: x.final_score, reverse=True)
    errors = [a for a in analyses if a.error]

    rec_styles = {
        "強い買い": "bold green",
        "買い":     "green",
        "中立":     "yellow",
        "売り":     "red",
        "強い売い": "bold red",
        "強い売り": "bold red",
    }

    def colored_score(s: float) -> str:
        if s >= 70: return f"[bold green]{s:.1f}[/bold green]"
        if s >= 55: return f"[green]{s:.1f}[/green]"
        if s >= 45: return f"[yellow]{s:.1f}[/yellow]"
        return f"[red]{s:.1f}[/red]"

    table = Table(
        title=f"📊  1〜2週間後 短期株価予測ランキング  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        show_lines=True,
    )
    table.add_column("順位",       style="bold white", justify="center", width=5)
    table.add_column("銘柄",       style="bold cyan",  width=6)
    table.add_column("企業名",                         width=24)
    table.add_column("現在株価",   justify="right",    width=10)
    table.add_column("総合スコア", justify="center",   width=10)
    table.add_column("推奨",       justify="center",   width=10)
    table.add_column("テクニカル", justify="center",   width=9)
    table.add_column("モメンタム", justify="center",   width=9)
    table.add_column("センチメント", justify="center", width=11)
    table.add_column("パターン",   justify="center",   width=8)

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for rank, a in enumerate(valid, 1):
        scores = {r.key: r.score for r in a.agent_results}
        style  = rec_styles.get(a.recommendation, "white")
        table.add_row(
            medals.get(rank, f"#{rank}"),
            a.ticker,
            a.company_name[:24],
            f"${a.current_price:.2f}",
            colored_score(a.final_score),
            f"[{style}]{a.recommendation}[/{style}]",
            colored_score(scores.get("technical",  50)),
            colored_score(scores.get("momentum",   50)),
            colored_score(scores.get("sentiment",  50)),
            colored_score(scores.get("pattern",    50)),
        )

    console.print()
    console.print(table)

    if errors:
        console.print(
            f"\n[yellow]⚠ 分析失敗: "
            f"{', '.join(f'{a.ticker}({a.error[:40]})' for a in errors)}[/yellow]"
        )

    # 上位3銘柄の詳細パネル
    console.print("\n[bold blue]━━━  上位銘柄 詳細分析  ━━━[/bold blue]\n")

    for a in valid[:3]:
        style   = rec_styles.get(a.recommendation, "white")
        content = (
            f"[bold]スコア: {a.final_score:.1f}/100  "
            f"推奨: [{style}]{a.recommendation}[/{style}]  "
            f"セクター: {a.sector}[/bold]\n\n"
        )
        if a.summary:
            content += f"[italic]{a.summary}[/italic]\n\n"

        content += "[bold underline]エージェント別スコア:[/bold underline]\n"
        for r in a.agent_results:
            s = "green" if r.score >= 65 else "yellow" if r.score >= 45 else "red"
            content += f"\n[bold]{r.name}[/bold]: [{s}]{r.score:.0f}/100[/{s}]  信頼度: {r.confidence}\n"
            for sig in r.signals[:3]:
                content += f"  ▸ {sig}\n"

        console.print(Panel(
            content.strip(),
            title=f"[bold cyan]{a.ticker}  {a.company_name}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))

    console.print(Panel(
        "⚠️  [bold yellow]免責事項[/bold yellow]\n"
        "この分析は情報提供のみを目的としており、投資勧誘ではありません。\n"
        "短期予測はノイズが多く特に不確実性が高いです。投資は必ず自己責任で行ってください。\n"
        "テクニカル分析は将来の結果を保証するものではありません。",
        border_style="yellow",
        style="dim",
    ))


# ==============================================================================
# デフォルト銘柄リスト / エントリーポイント
# ==============================================================================

DEFAULT_TICKERS = [
    "NVDA",   # NVIDIA
    "MSFT",   # Microsoft
    "AAPL",   # Apple
    "AMZN",   # Amazon
    "META",   # Meta
    "TSLA",   # Tesla
    "AMD",    # AMD
    "PLTR",   # Palantir
]


async def async_main():
    console.print(Panel.fit(
        "[bold blue]📈  短期株価予測マルチエージェントシステム[/bold blue]\n\n"
        "[dim]テクニカル / モメンタム / センチメント / パターンの\n"
        "4専門エージェント + オーケストレーターが\n"
        "1〜2週間後の株価動向を予測します[/dim]",
        border_style="blue",
        padding=(1, 3),
    ))

    tickers = (
        [t.upper() for t in sys.argv[1:]]
        if len(sys.argv) > 1
        else DEFAULT_TICKERS
    )

    if tickers == DEFAULT_TICKERS:
        console.print(f"\n[dim]📋 分析対象（デフォルト）: {', '.join(tickers)}[/dim]")
        console.print("[dim]💡 別の銘柄: python short_term_predictor.py TICKER1 TICKER2 ...[/dim]\n")
    else:
        console.print(f"\n[dim]📋 分析対象: {', '.join(tickers)}[/dim]\n")

    async_client = anthropic.AsyncAnthropic()

    semaphore      = asyncio.Semaphore(3)
    progress_tasks: dict[str, int] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=False,
    ) as progress:
        for t in tickers:
            tid = progress.add_task(f"[dim]{t} 待機中...", total=None)
            progress_tasks[t] = tid

        async def run(ticker: str) -> StockAnalysis:
            async with semaphore:
                tid = progress_tasks[ticker]
                progress.update(tid, description=f"[cyan]{ticker}  4エージェント分析中...")
                result = await analyze_stock(async_client, ticker)
                if result.error:
                    progress.update(tid, description=f"[red]✗ {ticker}: {result.error[:50]}")
                else:
                    progress.update(
                        tid,
                        description=(
                            f"[green]✓ {ticker}  "
                            f"スコア: {result.final_score:.1f}  ({result.recommendation})"
                        ),
                    )
                return result

        analyses = await asyncio.gather(*[run(t) for t in tickers])

    display_results(list(analyses))


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[bold red]エラー: ANTHROPIC_API_KEY 環境変数が設定されていません[/bold red]")
        sys.exit(1)
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
